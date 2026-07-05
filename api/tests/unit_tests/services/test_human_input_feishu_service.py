import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger  # type: ignore[import-untyped]

from core.workflow.nodes.human_input.entities import (
    FileInputConfig,
    FormDefinition,
    ParagraphInputConfig,
    SelectInputConfig,
    StringListSource,
    UserActionConfig,
)
from core.workflow.nodes.human_input.enums import FormInputType, ValueSourceType
from graphon.runtime import VariablePool
from models.human_input import EmailMemberRecipientPayload
from models.human_input_feishu import HumanInputFeishuDeliveryStatus
from services.human_input_feishu_service import HumanInputFeishuService
from services.member_contact_service import MemberContactService


class _FakeSession:
    def __init__(self, delivery, recipient):
        self._delivery = delivery
        self._recipient = recipient

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def scalar(self, _stmt):
        return self._delivery

    def get(self, _model, _id):
        return self._recipient


class _FakeRecipientQuery:
    def __init__(self, recipients):
        self._recipients = recipients

    def all(self):
        return self._recipients


def _build_definition(*, with_file: bool = False) -> FormDefinition:
    inputs: list[ParagraphInputConfig | SelectInputConfig | FileInputConfig] = [
        ParagraphInputConfig(type=FormInputType.PARAGRAPH, output_variable_name="reason"),
        SelectInputConfig(
            type=FormInputType.SELECT,
            output_variable_name="priority",
            option_source=StringListSource(type=ValueSourceType.CONSTANT, value=["P0", "P1"]),
        ),
    ]
    if with_file:
        inputs.append(FileInputConfig(type=FormInputType.FILE, output_variable_name="attachment"))

    return FormDefinition(
        form_content="Please approve",
        rendered_content="Please approve",
        expiration_time=datetime(2026, 7, 5, tzinfo=UTC),
        inputs=inputs,
        user_actions=[
            UserActionConfig(id="approve", title="Approve"),
            UserActionConfig(id="reject", title="Reject"),
        ],
        node_title="Approval",
    )


def test_render_form_card_uses_interactive_mode_for_supported_inputs():
    service = HumanInputFeishuService()

    result = service.render_form_card(
        form_id="form-1",
        recipient_id="recipient-1",
        form_link="https://example.com/form/token",
        definition=_build_definition(),
    )

    assert result.mode.value == "interactive_card"
    assert result.content["body"]["elements"][1]["tag"] == "form"


def test_render_form_card_falls_back_to_link_mode_for_unsupported_inputs():
    service = HumanInputFeishuService()

    result = service.render_form_card(
        form_id="form-1",
        recipient_id="recipient-1",
        form_link="https://example.com/form/token",
        definition=_build_definition(with_file=True),
    )

    assert result.mode.value == "link_fallback"
    assert result.content["body"]["elements"][1]["tag"] == "button"


def test_handle_card_action_submits_form_and_returns_result_card():
    delivery = SimpleNamespace(
        recipient_id="recipient-1",
        account_id="account-1",
        status=HumanInputFeishuDeliveryStatus.SENT,
    )
    recipient = SimpleNamespace(access_token="token-1")
    initial_record = SimpleNamespace(
        definition=_build_definition(),
        submitted=False,
    )
    submitted_record = SimpleNamespace(
        definition=_build_definition(),
        submitted=True,
        selected_action_id="approve",
        submitted_data={"reason": "ok", "priority": "P0"},
    )
    repository = MagicMock()
    repository.get_by_token.side_effect = [initial_record, submitted_record]
    human_input_service = MagicMock()
    human_input_service._form_repository = repository

    def session_factory() -> _FakeSession:
        return _FakeSession(delivery, recipient)

    service = HumanInputFeishuService(session_factory=session_factory, human_input_service=human_input_service)
    payload = P2CardActionTrigger(
        {
            "event": {
                "operator": {"open_id": "ou_123"},
                "action": {
                    "value": {"form_id": "form-1", "action_id": "approve"},
                    "form_value": {"reason": "ok", "priority": "P0"},
                },
            }
        }
    )

    response = service.handle_card_action(payload)

    human_input_service.submit_form_by_token.assert_called_once_with(
        "email_member",
        "token-1",
        "approve",
        {"reason": "ok", "priority": "P0"},
        submission_user_id="account-1",
    )
    assert response.card is not None
    assert response.card.type == "raw"


def test_handle_card_action_rejects_identity_mismatch():
    repository = MagicMock()
    human_input_service = MagicMock()
    human_input_service._form_repository = repository

    def session_factory() -> _FakeSession:
        return _FakeSession(None, None)

    service = HumanInputFeishuService(session_factory=session_factory, human_input_service=human_input_service)
    payload = P2CardActionTrigger(
        {
            "event": {
                "operator": {"open_id": "ou_other"},
                "action": {
                    "value": {"form_id": "form-1", "action_id": "approve"},
                    "form_value": {},
                },
            }
        }
    )

    response = service.handle_card_action(payload)

    human_input_service.submit_form_by_token.assert_not_called()
    assert response.toast is not None
    assert response.toast.type == "error"


def test_dispatch_form_notifications_records_successful_delivery(monkeypatch):
    recipient = SimpleNamespace(
        id="recipient-1",
        recipient_payload=EmailMemberRecipientPayload(
            user_id="acc-1",
            contact_id="contact-1",
            name="Demo User",
            email="demo@example.com",
        ).model_dump_json(),
        access_token="token-1",
    )
    session = MagicMock()
    session.scalars.return_value = _FakeRecipientQuery([recipient])
    session.scalar.return_value = None
    form = SimpleNamespace(
        id="form-1",
        tenant_id="tenant-1",
        form_definition=json.dumps(_build_definition().model_dump(mode="json")),
    )
    client = MagicMock()
    client.im.v1.message.create.return_value = SimpleNamespace(
        code=0,
        data=SimpleNamespace(message_id="om_123"),
    )
    monkeypatch.setattr(
        MemberContactService,
        "resolve_workspace_member_binding",
        lambda self, _session, tenant_id, account_id: SimpleNamespace(
            tenant_id=tenant_id,
            account_id=account_id,
            contact_id="contact-1",
            feishu_open_id="ou_123",
        ),
    )
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_ID", "cli_test")
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_SECRET", "secret")
    service = HumanInputFeishuService(client=client)

    service.dispatch_form_notifications(session=session, form=form, variable_pool=None)

    session.add.assert_called_once()
    delivery = session.add.call_args.args[0]
    assert delivery.status == HumanInputFeishuDeliveryStatus.SENT
    assert delivery.message_id == "om_123"


def test_dispatch_form_notifications_renders_form_body_variables_in_card_payload(monkeypatch):
    recipient = SimpleNamespace(
        id="recipient-1",
        recipient_payload=EmailMemberRecipientPayload(
            user_id="acc-1",
            contact_id="contact-1",
            name="Demo User",
            email="demo@example.com",
        ).model_dump_json(),
        access_token="token-1",
    )
    session = MagicMock()
    session.scalars.return_value = _FakeRecipientQuery([recipient])
    session.scalar.return_value = None
    definition = _build_definition().model_copy(
        update={
            "form_content": "Approve {{#node1.value#}}",
            "rendered_content": "Approve {{#node1.value#}}",
        }
    )
    form = SimpleNamespace(
        id="form-1",
        tenant_id="tenant-1",
        form_definition=json.dumps(definition.model_dump(mode="json")),
    )
    client = MagicMock()
    client.im.v1.message.create.return_value = SimpleNamespace(
        code=0,
        data=SimpleNamespace(message_id="om_123"),
    )
    variable_pool = VariablePool()
    variable_pool.add(["node1", "value"], "Dify")
    monkeypatch.setattr(
        MemberContactService,
        "resolve_workspace_member_binding",
        lambda self, _session, tenant_id, account_id: SimpleNamespace(
            tenant_id=tenant_id,
            account_id=account_id,
            contact_id="contact-1",
            feishu_open_id="ou_123",
        ),
    )
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_ID", "cli_test")
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_SECRET", "secret")
    service = HumanInputFeishuService(client=client)

    service.dispatch_form_notifications(session=session, form=form, variable_pool=variable_pool)

    delivery = session.add.call_args.args[0]
    payload = json.loads(delivery.card_payload)
    assert payload["body"]["elements"][0]["content"] == "Approve Dify"


def test_dispatch_form_notifications_records_feishu_validation_error_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    recipient = SimpleNamespace(
        id="recipient-1",
        recipient_payload=EmailMemberRecipientPayload(
            user_id="acc-1",
            contact_id="contact-1",
            name="Demo User",
            email="demo@example.com",
        ).model_dump_json(),
        access_token="token-1",
    )
    session = MagicMock()
    session.scalars.return_value = _FakeRecipientQuery([recipient])
    session.scalar.return_value = None
    form = SimpleNamespace(
        id="form-1",
        tenant_id="tenant-1",
        form_definition=json.dumps(_build_definition().model_dump(mode="json")),
    )
    response = SimpleNamespace(
        code=230099,
        msg="field validation failed",
        data=None,
        error=SimpleNamespace(
            log_id="20260705abc",
            troubleshooter="https://feishu.example/troubleshoot",
            field_violations=[
                SimpleNamespace(
                    field="content.body.elements[1]",
                    value='{"tag":"form"}',
                    description="invalid tag form",
                )
            ],
        ),
        get_log_id=lambda: None,
        get_troubleshooter=lambda: "https://feishu.example/troubleshoot",
    )
    client = MagicMock()
    client.im.v1.message.create.return_value = response
    monkeypatch.setattr(
        MemberContactService,
        "resolve_workspace_member_binding",
        lambda self, _session, tenant_id, account_id: SimpleNamespace(
            tenant_id=tenant_id,
            account_id=account_id,
            contact_id="contact-1",
            feishu_open_id="ou_123",
        ),
    )
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_ID", "cli_test")
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_SECRET", "secret")
    service = HumanInputFeishuService(client=client)

    with caplog.at_level(logging.ERROR):
        service.dispatch_form_notifications(session=session, form=form, variable_pool=None)

    delivery = session.add.call_args.args[0]
    assert delivery.status == HumanInputFeishuDeliveryStatus.FAILED
    assert delivery.failure_reason is not None
    assert "field validation failed" in delivery.failure_reason
    assert "content.body.elements[1]" in delivery.failure_reason
    assert "20260705abc" in delivery.failure_reason
    assert "content.body.elements[1]" in caplog.text
    assert "20260705abc" in caplog.text


def test_dispatch_form_notifications_handles_sdk_error_dict_with_broken_troubleshooter_accessor(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    recipient = SimpleNamespace(
        id="recipient-1",
        recipient_payload=EmailMemberRecipientPayload(
            user_id="acc-1",
            contact_id="contact-1",
            name="Demo User",
            email="demo@example.com",
        ).model_dump_json(),
        access_token="token-1",
    )
    session = MagicMock()
    session.scalars.return_value = _FakeRecipientQuery([recipient])
    session.scalar.return_value = None
    form = SimpleNamespace(
        id="form-1",
        tenant_id="tenant-1",
        form_definition=json.dumps(_build_definition().model_dump(mode="json")),
    )
    response = SimpleNamespace(
        code=230099,
        msg="field validation failed",
        data=None,
        error={
            "log_id": "20260705xyz",
            "troubleshooter": "https://feishu.example/troubleshoot",
            "field_violations": [
                {
                    "field": "content.body.elements[1]",
                    "value": '{"tag":"form"}',
                    "description": "invalid tag form",
                }
            ],
        },
        get_log_id=lambda: None,
        get_troubleshooter=lambda: (_ for _ in ()).throw(
            AttributeError("'dict' object has no attribute 'troubleshooter'")
        ),
    )
    client = MagicMock()
    client.im.v1.message.create.return_value = response
    monkeypatch.setattr(
        MemberContactService,
        "resolve_workspace_member_binding",
        lambda self, _session, tenant_id, account_id: SimpleNamespace(
            tenant_id=tenant_id,
            account_id=account_id,
            contact_id="contact-1",
            feishu_open_id="ou_123",
        ),
    )
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_ID", "cli_test")
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_SECRET", "secret")
    service = HumanInputFeishuService(client=client)

    with caplog.at_level(logging.ERROR):
        service.dispatch_form_notifications(session=session, form=form, variable_pool=None)

    delivery = session.add.call_args.args[0]
    assert delivery.status == HumanInputFeishuDeliveryStatus.FAILED
    assert "20260705xyz" in delivery.failure_reason
    assert "https://feishu.example/troubleshoot" in delivery.failure_reason
    assert "20260705xyz" in caplog.text


def test_dispatch_form_notifications_logs_context_when_feishu_send_raises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    recipient = SimpleNamespace(
        id="recipient-1",
        recipient_payload=EmailMemberRecipientPayload(
            user_id="acc-1",
            contact_id="contact-1",
            name="Demo User",
            email="demo@example.com",
        ).model_dump_json(),
        access_token="token-1",
    )
    session = MagicMock()
    session.scalars.return_value = _FakeRecipientQuery([recipient])
    session.scalar.return_value = None
    form = SimpleNamespace(
        id="form-1",
        tenant_id="tenant-1",
        form_definition=json.dumps(_build_definition().model_dump(mode="json")),
    )
    client = MagicMock()
    client.im.v1.message.create.side_effect = RuntimeError("socket closed")
    monkeypatch.setattr(
        MemberContactService,
        "resolve_workspace_member_binding",
        lambda self, _session, tenant_id, account_id: SimpleNamespace(
            tenant_id=tenant_id,
            account_id=account_id,
            contact_id="contact-1",
            feishu_open_id="ou_123",
        ),
    )
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_ID", "cli_test")
    monkeypatch.setattr("services.human_input_feishu_service.dify_config.FEISHU_APP_SECRET", "secret")
    service = HumanInputFeishuService(client=client)

    with caplog.at_level(logging.ERROR):
        service.dispatch_form_notifications(session=session, form=form, variable_pool=None)

    delivery = session.add.call_args.args[0]
    assert delivery.status == HumanInputFeishuDeliveryStatus.FAILED
    assert delivery.failure_reason == "socket closed"
    assert "form_id=form-1" in caplog.text
    assert "recipient_id=recipient-1" in caplog.text
    assert "open_id=ou_123" in caplog.text
