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


def _build_definition(
    *,
    with_file: bool = False,
    form_content: str = "Please approve",
    rendered_content: str = "Please approve",
) -> FormDefinition:
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
        form_content=form_content,
        rendered_content=rendered_content,
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
    form_element = next(element for element in result.content["body"]["elements"] if element["tag"] == "form")
    assert form_element["elements"][-1]["tag"] == "column_set"


def test_render_form_card_interleaves_inputs_with_output_placeholders():
    service = HumanInputFeishuService()

    result = service.render_form_card(
        form_id="form-1",
        recipient_id="recipient-1",
        form_link="https://example.com/form/token",
        definition=_build_definition(
            form_content="Before {{#$output.reason#}} between {{#$output.priority#}} after",
            rendered_content="Before {{#$output.reason#}} between {{#$output.priority#}} after",
        ),
    )

    form_element = next(element for element in result.content["body"]["elements"] if element["tag"] == "form")
    form_elements = form_element["elements"]

    assert [element["tag"] for element in form_elements] == [
        "markdown",
        "input",
        "markdown",
        "select_static",
        "markdown",
        "column_set",
    ]
    assert [form_elements[0]["content"], form_elements[2]["content"], form_elements[4]["content"]] == [
        "Before ",
        " between ",
        " after",
    ]
    assert form_elements[1]["name"] == "reason"
    assert form_elements[3]["name"] == "priority"


def test_render_form_card_consumes_duplicate_output_placeholders_without_leaking_template_text():
    service = HumanInputFeishuService()

    result = service.render_form_card(
        form_id="form-1",
        recipient_id="recipient-1",
        form_link="https://example.com/form/token",
        definition=_build_definition(
            form_content="Before {{#$output.reason#}} between {{#$output.reason#}} after",
            rendered_content="Before {{#$output.reason#}} between {{#$output.reason#}} after",
        ),
    )

    form_element = next(element for element in result.content["body"]["elements"] if element["tag"] == "form")
    form_elements = form_element["elements"]
    markdown_contents = [element["content"] for element in form_elements if element["tag"] == "markdown"]
    reason_inputs = [element for element in form_elements if element.get("name") == "reason"]

    assert markdown_contents == ["Before ", " between ", " after"]
    assert len(reason_inputs) == 1
    assert "{{#$output.reason#}}" not in "".join(markdown_contents)


def test_render_form_card_preserves_markdown_and_appends_unreferenced_inputs():
    service = HumanInputFeishuService()

    result = service.render_form_card(
        form_id="form-1",
        recipient_id="recipient-1",
        form_link="https://example.com/form/token",
        definition=_build_definition(
            form_content="Intro\n{{#$output.priority#}}\nOutro",
            rendered_content="Intro\n{{#$output.priority#}}\nOutro",
        ),
    )

    form_element = next(element for element in result.content["body"]["elements"] if element["tag"] == "form")
    form_elements = form_element["elements"]

    assert [element["tag"] for element in form_elements] == [
        "markdown",
        "select_static",
        "markdown",
        "input",
        "column_set",
    ]
    assert form_elements[0]["content"] == "Intro\n"
    assert form_elements[1]["name"] == "priority"
    assert form_elements[2]["content"] == "\nOutro"
    assert form_elements[3]["name"] == "reason"


def test_render_form_card_uses_rendered_markdown_when_form_content_controls_output_placement():
    service = HumanInputFeishuService()

    result = service.render_form_card(
        form_id="form-1",
        recipient_id="recipient-1",
        form_link="https://example.com/form/token",
        definition=_build_definition(
            form_content="Approve {{#node1.value#}} {{#$output.reason#}} after",
            rendered_content="Approve Dify  after",
        ),
    )

    form_element = next(element for element in result.content["body"]["elements"] if element["tag"] == "form")
    form_elements = form_element["elements"]
    markdown_contents = [element["content"] for element in form_elements if element["tag"] == "markdown"]

    assert [element["tag"] for element in form_elements] == [
        "markdown",
        "input",
        "markdown",
        "select_static",
        "column_set",
    ]
    assert markdown_contents == ["Approve Dify ", " after"]
    assert "{{#node1.value#}}" not in "".join(markdown_contents)


def test_render_form_card_preserves_rendered_text_when_output_placeholder_is_adjacent_to_ordinary_template():
    service = HumanInputFeishuService()

    result = service.render_form_card(
        form_id="form-1",
        recipient_id="recipient-1",
        form_link="https://example.com/form/token",
        definition=_build_definition(
            form_content="Approve {{#node1.value#}}{{#$output.reason#}} after",
            rendered_content="Approve Dify after",
        ),
    )

    form_element = next(element for element in result.content["body"]["elements"] if element["tag"] == "form")
    form_elements = form_element["elements"]
    markdown_contents = [element["content"] for element in form_elements if element["tag"] == "markdown"]

    assert [element["tag"] for element in form_elements] == [
        "markdown",
        "input",
        "select_static",
        "column_set",
    ]
    assert markdown_contents == ["Approve Dify after"]
    assert "{{#node1.value#}}" not in "".join(markdown_contents)


def test_render_form_card_falls_back_to_rendered_content_when_projection_fails():
    service = HumanInputFeishuService()

    result = service.render_form_card(
        form_id="form-1",
        recipient_id="recipient-1",
        form_link="https://example.com/form/token",
        definition=_build_definition(
            form_content="Approve {{#node1.value#}} {{#$output.reason#}} after",
            rendered_content="Manual override",
        ),
    )

    form_element = next(element for element in result.content["body"]["elements"] if element["tag"] == "form")
    form_elements = form_element["elements"]
    markdown_contents = [element["content"] for element in form_elements if element["tag"] == "markdown"]

    assert [element["tag"] for element in form_elements] == [
        "markdown",
        "input",
        "select_static",
        "column_set",
    ]
    assert markdown_contents == ["Manual override"]
    assert "{{#node1.value#}}" not in "".join(markdown_contents)
    assert "{{#$output.reason#}}" not in "".join(markdown_contents)


def test_render_form_card_uses_placeholder_instead_of_label_for_select_static():
    service = HumanInputFeishuService()

    result = service.render_form_card(
        form_id="form-1",
        recipient_id="recipient-1",
        form_link="https://example.com/form/token",
        definition=_build_definition(),
    )

    form_element = next(element for element in result.content["body"]["elements"] if element["tag"] == "form")
    select_element = next(element for element in form_element["elements"] if element["tag"] == "select_static")
    assert select_element["tag"] == "select_static"
    assert "label" not in select_element
    assert select_element["placeholder"]["content"] == "priority"


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


def test_dispatch_form_notifications_uses_deterministic_compact_message_uuid(monkeypatch):
    form_id = "123e4567-e89b-12d3-a456-426614174000"
    recipient_id = "987e6543-e21b-12d3-a456-426614174999"
    recipient = SimpleNamespace(
        id=recipient_id,
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
        id=form_id,
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
    service.dispatch_form_notifications(session=session, form=form, variable_pool=None)

    first_request = client.im.v1.message.create.call_args_list[0].args[0]
    second_request = client.im.v1.message.create.call_args_list[1].args[0]
    first_uuid = first_request.request_body.uuid
    second_uuid = second_request.request_body.uuid

    assert len(first_uuid) <= 50
    assert first_uuid == second_uuid
    assert first_uuid != f"{form_id}:{recipient_id}"


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
    form_element = next(element for element in payload["body"]["elements"] if element["tag"] == "form")
    markdown_element = next(element for element in form_element["elements"] if element["tag"] == "markdown")
    assert markdown_element["content"] == "Approve Dify"


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
