from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.workflow.human_input_adapter import EmailDeliveryConfig, EmailDeliveryMethod, EmailRecipients
from core.workflow.nodes.human_input.entities import (
    FileInputConfig,
    FileListInputConfig,
    FormDefinition,
    ParagraphInputConfig,
    SelectInputConfig,
    StringListSource,
    UserActionConfig,
)
from core.workflow.nodes.human_input.enums import TimeoutUnit, ValueSourceType
from models.contact import ContactSource, ContactStatus, ContactType
from models.human_input import (
    EmailExternalRecipientPayload,
    EmailMemberRecipientPayload,
    HumanInputContactSnapshot,
    RecipientType,
)
from models.im_delivery import IMMessageCorrelation, IMMessageDeliveryStatus
from models.im_integration import IMBindingStatus, IMInstallMode, IMProvider, IMScopeType
from services.entities.im_binding_entities import IMBindingRecord
from services.human_input_im import delivery_service as delivery_module
from services.human_input_im.provider_types import IMSendResult


class _DummyMail:
    def __init__(self):
        self.sent: list[dict[str, str]] = []

    def is_inited(self) -> bool:
        return True

    def send(self, *, to: str, subject: str, html: str):
        self.sent.append({"to": to, "subject": subject, "html": html})


class _FakeSession:
    def __init__(self):
        self.added: list[object] = []
        self.flush_calls: list[list[object] | None] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self, objs=None) -> None:  # type: ignore[no-untyped-def]
        if objs is None:
            self.flush_calls.append(None)
            return
        self.flush_calls.append(list(objs))


def _build_form_definition() -> FormDefinition:
    return FormDefinition(
        form_content="ignored",
        rendered_content="Rendered body",
        expiration_time=datetime(2026, 7, 5, 0, 0, 0),
        inputs=[
            ParagraphInputConfig(output_variable_name="reason"),
            SelectInputConfig(
                output_variable_name="decision",
                option_source=StringListSource(
                    type=ValueSourceType.CONSTANT,
                    value=["approve", "reject"],
                ),
            ),
            FileInputConfig(output_variable_name="attachment"),
            FileListInputConfig(output_variable_name="attachments", number_limits=2),
        ],
        user_actions=[
            UserActionConfig(id="approve", title="Approve"),
            UserActionConfig(id="reject", title="Reject"),
        ],
        node_title="Review Request",
    )


def _build_form() -> SimpleNamespace:
    definition = _build_form_definition()
    return SimpleNamespace(
        id="form-1",
        tenant_id="tenant-1",
        app_id="app-1",
        node_id="node-1",
        workflow_run_id="run-1",
        form_definition=definition.model_dump_json(),
    )


def _build_runtime(recipient: SimpleNamespace) -> object:
    return delivery_module._EmailDeliveryRuntime(
        delivery=SimpleNamespace(id="delivery-1"),
        config=EmailDeliveryMethod(
            config=EmailDeliveryConfig(
                recipients=EmailRecipients(include_bound_group=False, items=[]),
                subject="Subject",
                body="Body",
            )
        ),
        recipients=[recipient],
    )


def _build_member_snapshot(*, email: str | None) -> HumanInputContactSnapshot:
    return HumanInputContactSnapshot(
        contact_id="contact-member-1",
        tenant_id="tenant-1",
        type=ContactType.MEMBER,
        source=ContactSource.WORKSPACE_MEMBER,
        status=ContactStatus.ACTIVE,
        name="Member Contact",
        account_id="account-1",
        email=email,
    )


def _build_external_snapshot(*, email: str) -> HumanInputContactSnapshot:
    return HumanInputContactSnapshot(
        contact_id="contact-external-1",
        tenant_id="tenant-1",
        type=ContactType.EXTERNAL,
        source=ContactSource.MANUAL_EXTERNAL,
        status=ContactStatus.ACTIVE,
        name="External Contact",
        email=email,
    )


def _build_member_recipient(*, email: str, snapshot_email: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id="recipient-1",
        recipient_type=RecipientType.EMAIL_MEMBER,
        contact_snapshot=_build_member_snapshot(email=snapshot_email),
        recipient_payload=EmailMemberRecipientPayload(user_id="account-1", email=email).model_dump_json(),
        access_token="token-1",
    )


def _build_external_recipient(*, email: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="recipient-2",
        recipient_type=RecipientType.EMAIL_EXTERNAL,
        contact_snapshot=_build_external_snapshot(email=email),
        recipient_payload=EmailExternalRecipientPayload(email=email).model_dump_json(),
        access_token="token-2",
    )


def _build_binding() -> IMBindingRecord:
    return IMBindingRecord(
        id="binding-1",
        account_id="account-1",
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        provider_workspace_id="workspace-1",
        provider_user_id="provider-user-1",
        status=IMBindingStatus.ACTIVE,
    )


def test_delivery_service_bound_member_uses_im_send_and_records_failed_correlation(monkeypatch):
    form = _build_form()
    recipient = _build_member_recipient(email="member@example.com", snapshot_email="member@example.com")
    runtime = _build_runtime(recipient)
    session = _FakeSession()
    recorded_statuses: list[dict[str, object]] = []
    im_service = MagicMock()
    im_service.inspect_active_binding.return_value = _build_binding()
    im_service.send_form.return_value = IMSendResult(
        provider=IMProvider.FEISHU,
        accepted=False,
        provider_message_id=None,
        error="phase-1 provider transport adapter not implemented",
    )

    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_load_email_delivery_runtimes",
        staticmethod(lambda **_: [runtime]),
    )
    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_append_process_data_status",
        staticmethod(lambda **kwargs: recorded_statuses.append(kwargs)),
    )
    monkeypatch.setattr(delivery_module, "load_human_input_variable_pool", lambda _workflow_run_id: None)
    monkeypatch.setattr(delivery_module, "mail", _DummyMail())
    monkeypatch.setattr(
        delivery_module.FeatureService,
        "get_features",
        lambda _tenant_id, **_kwargs: SimpleNamespace(human_input_email_delivery_enabled=True),
    )

    service = delivery_module.ContactV2HumanInputDeliveryService(im_service=im_service)
    service.deliver_form(session=session, form=form, node_title="Review")

    im_service.send_form.assert_called_once()
    command = im_service.send_form.call_args.kwargs
    assert command["provider"] == IMProvider.FEISHU
    assert command["tenant_id"] == "tenant-1"
    assert command["recipient_id"] == "provider-user-1"
    assert command["form_id"] == "form-1"
    assert command["title"] == "Review"
    assert "Inline inputs:" in command["content"]
    assert "- reason: paragraph" in command["content"]
    assert "- decision: select [approve, reject]" in command["content"]
    assert "File inputs require the web form fallback:" in command["content"]
    assert "attachment, attachments" in command["content"]
    assert "Actions:" in command["content"]
    assert "- Approve (`provider_action_approve`)" in command["content"]
    assert "Web form: " in command["content"]

    correlation = next(obj for obj in session.added if isinstance(obj, IMMessageCorrelation))
    assert correlation.delivery_status == IMMessageDeliveryStatus.FAILED
    assert correlation.error_reason == "phase-1 provider transport adapter not implemented"
    snapshot = json.loads(correlation.interaction_mapping_snapshot)
    assert snapshot["schema_version"] == 1
    assert snapshot["interaction_id"] == command["metadata"]["interaction_id"]
    assert snapshot["inputs"] == {
        "provider_component_reason": {"output_variable_name": "reason", "type": "paragraph"},
        "provider_component_decision": {"output_variable_name": "decision", "type": "select"},
    }
    assert snapshot["actions"] == {
        "provider_action_approve": {"action_id": "approve"},
        "provider_action_reject": {"action_id": "reject"},
    }
    assert recorded_statuses == [
        {
            "session": session,
            "form": form,
            "status": "im_failed",
            "recipient": recipient,
            "extra": {
                "correlation_id": correlation.id,
                "error": "phase-1 provider transport adapter not implemented",
            },
        }
    ]


def test_delivery_service_missing_binding_falls_back_to_email(monkeypatch):
    form = _build_form()
    recipient = _build_member_recipient(email="member@example.com", snapshot_email="member@example.com")
    runtime = _build_runtime(recipient)
    mail = _DummyMail()
    recorded_statuses: list[dict[str, object]] = []
    im_service = MagicMock()
    im_service.inspect_active_binding.return_value = None

    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_load_email_delivery_runtimes",
        staticmethod(lambda **_: [runtime]),
    )
    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_append_process_data_status",
        staticmethod(lambda **kwargs: recorded_statuses.append(kwargs)),
    )
    monkeypatch.setattr(delivery_module, "load_human_input_variable_pool", lambda _workflow_run_id: None)
    monkeypatch.setattr(delivery_module, "mail", mail)
    monkeypatch.setattr(
        delivery_module.FeatureService,
        "get_features",
        lambda _tenant_id, **_kwargs: SimpleNamespace(human_input_email_delivery_enabled=True),
    )

    service = delivery_module.ContactV2HumanInputDeliveryService(im_service=im_service)
    service.deliver_form(session=_FakeSession(), form=form, node_title="Review")

    im_service.send_form.assert_not_called()
    assert len(mail.sent) == 1
    assert mail.sent[0]["to"] == "member@example.com"
    assert recorded_statuses[0]["status"] == "fallback_email"


def test_delivery_service_missing_binding_and_email_skips_recipient(monkeypatch):
    form = _build_form()
    recipient = _build_member_recipient(email="member@example.com", snapshot_email=None)
    runtime = _build_runtime(recipient)
    mail = _DummyMail()
    recorded_statuses: list[dict[str, object]] = []
    im_service = MagicMock()
    im_service.inspect_active_binding.return_value = None

    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_load_email_delivery_runtimes",
        staticmethod(lambda **_: [runtime]),
    )
    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_append_process_data_status",
        staticmethod(lambda **kwargs: recorded_statuses.append(kwargs)),
    )
    monkeypatch.setattr(delivery_module, "load_human_input_variable_pool", lambda _workflow_run_id: None)
    monkeypatch.setattr(delivery_module, "mail", mail)
    monkeypatch.setattr(
        delivery_module.FeatureService,
        "get_features",
        lambda _tenant_id, **_kwargs: SimpleNamespace(human_input_email_delivery_enabled=True),
    )

    service = delivery_module.ContactV2HumanInputDeliveryService(im_service=im_service)
    service.deliver_form(session=_FakeSession(), form=form, node_title="Review")

    assert mail.sent == []
    assert recorded_statuses[0]["status"] == "skipped_no_email"


def test_delivery_service_external_contact_uses_email_only(monkeypatch):
    form = _build_form()
    recipient = _build_external_recipient(email="external@example.com")
    runtime = _build_runtime(recipient)
    mail = _DummyMail()
    recorded_statuses: list[dict[str, object]] = []
    im_service = MagicMock()

    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_load_email_delivery_runtimes",
        staticmethod(lambda **_: [runtime]),
    )
    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_append_process_data_status",
        staticmethod(lambda **kwargs: recorded_statuses.append(kwargs)),
    )
    monkeypatch.setattr(delivery_module, "load_human_input_variable_pool", lambda _workflow_run_id: None)
    monkeypatch.setattr(delivery_module, "mail", mail)
    monkeypatch.setattr(
        delivery_module.FeatureService,
        "get_features",
        lambda _tenant_id, **_kwargs: SimpleNamespace(human_input_email_delivery_enabled=True),
    )

    service = delivery_module.ContactV2HumanInputDeliveryService(im_service=im_service)
    service.deliver_form(session=_FakeSession(), form=form, node_title="Review")

    im_service.inspect_active_binding.assert_not_called()
    im_service.send_form.assert_not_called()
    assert len(mail.sent) == 1
    assert mail.sent[0]["to"] == "external@example.com"
    assert recorded_statuses[0]["status"] == "external_email"


def test_delivery_service_dedupes_duplicate_member_contact_im_sends(monkeypatch):
    form = _build_form()
    recipient_one = _build_member_recipient(email="member@example.com", snapshot_email="member@example.com")
    recipient_two = SimpleNamespace(
        id="recipient-dup",
        recipient_type=RecipientType.EMAIL_MEMBER,
        contact_snapshot=recipient_one.contact_snapshot,
        recipient_payload=recipient_one.recipient_payload,
        access_token="token-dup",
    )
    runtime = delivery_module._EmailDeliveryRuntime(
        delivery=SimpleNamespace(id="delivery-1"),
        config=EmailDeliveryMethod(
            config=EmailDeliveryConfig(
                recipients=EmailRecipients(include_bound_group=False, items=[]),
                subject="Subject",
                body="Body",
            )
        ),
        recipients=[recipient_one, recipient_two],
    )
    session = _FakeSession()
    im_service = MagicMock()
    im_service.inspect_active_binding.return_value = _build_binding()
    im_service.send_form.return_value = IMSendResult(
        provider=IMProvider.FEISHU,
        accepted=False,
        provider_message_id=None,
        error="phase-1 provider transport adapter not implemented",
    )

    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_load_email_delivery_runtimes",
        staticmethod(lambda **_: [runtime]),
    )
    monkeypatch.setattr(
        delivery_module.ContactV2HumanInputDeliveryService,
        "_append_process_data_status",
        staticmethod(lambda **_kwargs: None),
    )
    monkeypatch.setattr(delivery_module, "load_human_input_variable_pool", lambda _workflow_run_id: None)
    monkeypatch.setattr(delivery_module, "mail", _DummyMail())
    monkeypatch.setattr(
        delivery_module.FeatureService,
        "get_features",
        lambda _tenant_id, **_kwargs: SimpleNamespace(human_input_email_delivery_enabled=True),
    )

    service = delivery_module.ContactV2HumanInputDeliveryService(im_service=im_service)
    service.deliver_form(session=session, form=form, node_title="Review")

    im_service.send_form.assert_called_once()
