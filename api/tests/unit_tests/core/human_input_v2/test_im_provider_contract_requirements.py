"""Requirement-level tests for immutable IM provider boundary values."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AuthenticatedIMEvent,
    CardAction,
    CardActionKind,
    CardAssessment,
    CardIntent,
    CredentialTestSuccess,
    DingTalkUserDestination,
    DirectoryEntry,
    DirectorySnapshot,
    FeishuLarkAdapterConfig,
    FeishuUserDestination,
    ImmutableJSONObject,
    MessageAccepted,
    OpaqueMetadata,
    PermissionFact,
    SlackUserDestination,
    WebhookRequest,
    WebhookResponse,
    WeComUserDestination,
    freeze_json_value,
    thaw_json_value,
)

_NOW = datetime(2026, 8, 2, 8, tzinfo=UTC)


@pytest.mark.parametrize(
    "permissions",
    [
        (),
        (PermissionFact(name="directory.read", granted=False),),
        (
            PermissionFact(name="directory.read", granted=True),
            PermissionFact(name="message.write", granted=False),
        ),
    ],
)
def test_credential_success_requires_confirmed_baseline_permissions(
    permissions: tuple[PermissionFact, ...],
) -> None:
    with pytest.raises(ValueError, match="permission"):
        CredentialTestSuccess(
            provider=IMProvider.SLACK,
            provider_tenant_id="tenant-1",
            permissions=permissions,
        )


def test_directory_snapshot_rejects_mutable_entry_collections() -> None:
    entries = [DirectoryEntry("user-1", "Ada", None, True)]

    with pytest.raises(TypeError, match="tuple"):
        DirectorySnapshot(
            provider=IMProvider.SLACK,
            provider_tenant_id="tenant-1",
            entries=entries,  # type: ignore[arg-type]
        )


def test_card_intent_rejects_mutable_nested_collections() -> None:
    facts = [("Environment", "Staging")]
    actions = [CardAction("approve", "Approve", CardActionKind.SUBMIT, "approved")]

    with pytest.raises(TypeError, match="tuple"):
        CardIntent(
            title="Approval",
            body="Review this request.",
            facts=facts,  # type: ignore[arg-type]
            actions=actions,  # type: ignore[arg-type]
            fallback_text="Review this request.",
        )


def test_opaque_metadata_requires_an_immutable_tuple_of_string_pairs() -> None:
    with pytest.raises(TypeError, match="entries must be a tuple"):
        OpaqueMetadata(entries=[("form_id", "form-1")])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="string pairs"):
        OpaqueMetadata(entries=(["form_id", "form-1"],))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="string pairs"):
        OpaqueMetadata(entries=((1, "form-1"),))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="string pairs"):
        OpaqueMetadata(entries=(("form_id", 1),))  # type: ignore[arg-type]


def test_opaque_metadata_rejects_duplicate_keys_without_collapsing_values() -> None:
    with pytest.raises(ValueError, match="keys must be unique"):
        OpaqueMetadata(entries=(("form_id", "form-1"), ("form_id", "form-2")))


def test_opaque_metadata_rejects_blank_keys_but_preserves_nonblank_keys_and_empty_values() -> None:
    empty = OpaqueMetadata(entries=())
    metadata = OpaqueMetadata(entries=((" form_id ", ""),))

    assert empty.as_dict() == {}
    assert metadata.as_dict() == {" form_id ": ""}
    for blank_key in ("", "   "):
        with pytest.raises(ValueError, match="keys must not be blank"):
            OpaqueMetadata(entries=((blank_key, "value"),))


def test_authenticated_event_rejects_mutable_provider_payload() -> None:
    mutable_payload = {"event": {"type": "message.created"}}

    with pytest.raises(TypeError, match="immutable"):
        AuthenticatedIMEvent(
            provider=IMProvider.SLACK,
            provider_tenant_id="tenant-1",
            provider_event_id="event-1",
            provider_event_time=None,
            received_at=_NOW,
            provider_event_type="message.created",
            provider_payload=mutable_payload,  # type: ignore[arg-type]
        )


def test_feishu_lark_configuration_has_no_transport_support_flag() -> None:
    config = FeishuLarkAdapterConfig(
        provider=IMProvider.FEISHU,
        app_id="cli_test",
        app_secret="secret-test",
        verification_token="verification-test",
        encrypt_key=None,
    )

    assert not hasattr(config, "stream_enabled")


def test_time_values_must_be_timezone_aware() -> None:
    naive_time = datetime(2026, 8, 2, 8)

    with pytest.raises(ValueError, match="timezone-aware"):
        WebhookRequest("POST", (), (), b"{}", naive_time)

    with pytest.raises(ValueError, match="timezone-aware"):
        AuthenticatedIMEvent(
            provider=IMProvider.SLACK,
            provider_tenant_id="tenant-1",
            provider_event_id=None,
            provider_event_time=naive_time,
            received_at=_NOW,
            provider_event_type=None,
            provider_payload=(),
        )


def test_authenticated_event_recursively_validates_immutable_json() -> None:
    provider_payload = freeze_json_value(
        {
            "object": {"nested": [1, "two", None]},
            "array": [True, 3.5],
        }
    )
    assert isinstance(provider_payload, ImmutableJSONObject)
    event = AuthenticatedIMEvent(
        provider=IMProvider.SLACK,
        provider_tenant_id="tenant-1",
        provider_event_id=None,
        provider_event_time=_NOW,
        received_at=_NOW,
        provider_event_type=None,
        provider_payload=provider_payload,
    )

    assert thaw_json_value(event.provider_payload) == {
        "object": {"nested": [1, "two", None]},
        "array": [True, 3.5],
    }

    with pytest.raises(TypeError, match="immutable JSON"):
        AuthenticatedIMEvent(
            provider=IMProvider.SLACK,
            provider_tenant_id="tenant-1",
            provider_event_id=None,
            provider_event_time=None,
            received_at=_NOW,
            provider_event_type=None,
            provider_payload=(("nested", ["mutable"]),),  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="string-keyed pairs"):
        AuthenticatedIMEvent(
            provider=IMProvider.SLACK,
            provider_tenant_id="tenant-1",
            provider_event_id=None,
            provider_event_time=None,
            received_at=_NOW,
            provider_event_type=None,
            provider_payload=((1, "invalid key"),),  # type: ignore[arg-type]
        )


def test_optional_diagnostic_values_reject_blank_strings() -> None:
    with pytest.raises(ValueError, match="card title"):
        CardIntent(" ", "Body", (), (), "Fallback")
    with pytest.raises(ValueError, match="assessment reason"):
        CardAssessment(False, " ")
    with pytest.raises(ValueError, match="provider request id"):
        MessageAccepted(reference="message-1", provider_request_id=" ")


@pytest.mark.parametrize("status_code", [99, 600])
def test_webhook_response_rejects_invalid_http_status(status_code: int) -> None:
    with pytest.raises(ValueError, match="valid HTTP status"):
        WebhookResponse(status_code, (), b"")


def test_provider_specific_destinations_validate_their_addressing_facts() -> None:
    with pytest.raises(ValueError, match="Feishu or Lark provider"):
        FeishuLarkAdapterConfig(IMProvider.SLACK, "app", "secret", "verify", None)
    with pytest.raises(ValueError, match="Slack user id"):
        SlackUserDestination(" ")
    with pytest.raises(ValueError, match="receive id"):
        FeishuUserDestination(" ", "open_id")
    with pytest.raises(ValueError, match="receive id type"):
        FeishuUserDestination("ou_1", " ")
    with pytest.raises(ValueError, match="DingTalk user id"):
        DingTalkUserDestination(" ")
    with pytest.raises(ValueError, match="WeCom user id"):
        WeComUserDestination(" ")


def test_wecom_destination_normalizes_one_personal_user_id() -> None:
    assert WeComUserDestination(" user-1 ").user_id == "user-1"
