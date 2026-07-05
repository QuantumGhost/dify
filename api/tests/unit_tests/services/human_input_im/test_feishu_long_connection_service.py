import pytest

from models.im_integration import IMInstallMode, IMProvider, IMScopeType
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.app_config_service import (
    IMAppConfigStatus,
    IMAppContext,
    IMEventMode,
    IMTokenStatus,
)
from services.human_input_im.callback_service import IMBindingCompletionResult
from services.human_input_im.feishu_long_connection_service import FeishuLongConnectionBindingConsumer
from services.human_input_im.provider_types import IMParsedProviderSubmission, IMParsedSubmissionPayload, IMSubmissionEvent


def _configured_context() -> IMAppContext:
    return IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=IMAppConfigStatus.CONFIGURED,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=IMEventMode.LONG_CONNECTION,
        app_id="cli_a",
        app_secret_configured=True,
        errors=[],
    )


def test_long_connection_consumer_requires_long_connection_mode() -> None:
    consumer = FeishuLongConnectionBindingConsumer()
    context = _configured_context().model_copy(update={"event_mode": IMEventMode.WEBHOOK})

    with pytest.raises(IMBindingValidationError):
        consumer.build_binding_completion_event(
            app_context=context,
            raw_event={
                "event_id": "event-1",
                "binding_session_token": "imbs_token",
                "provider_workspace_id": "ws-1",
                "provider_user_id": "user-1",
            },
        )


def test_long_connection_consumer_builds_binding_completion_event() -> None:
    consumer = FeishuLongConnectionBindingConsumer()
    event = consumer.build_binding_completion_event(
        app_context=_configured_context(),
        raw_event={
            "event_id": "event-1",
            "binding_session_token": "imbs_token",
            "provider_workspace_id": "ws-1",
            "provider_user_id": "user-1",
            "provider_union_id": "union-1",
        },
    )

    assert event.provider == IMProvider.FEISHU
    assert event.event_id == "event-1"
    assert event.binding_session_token == "imbs_token"
    assert event.provider_workspace_id == "ws-1"
    assert event.provider_user_id == "user-1"
    assert event.provider_union_id == "union-1"


@pytest.mark.parametrize(
    "missing_field",
    [
        "event_id",
        "binding_session_token",
        "provider_workspace_id",
        "provider_user_id",
    ],
)
def test_long_connection_consumer_rejects_malformed_binding_completion_payload(missing_field: str) -> None:
    consumer = FeishuLongConnectionBindingConsumer()
    raw_event = {
        "event_id": "event-1",
        "binding_session_token": "imbs_token",
        "provider_workspace_id": "ws-1",
        "provider_user_id": "user-1",
    }
    raw_event.pop(missing_field)

    with pytest.raises(
        IMBindingValidationError,
        match=f"missing required feishu long-connection field: {missing_field}",
    ):
        consumer.build_binding_completion_event(
            app_context=_configured_context(),
            raw_event=raw_event,
        )


def test_long_connection_consumer_delegates_to_callback_service() -> None:
    im_service = type("IMService", (), {})()
    captured: dict[str, object] = {}
    completion_result = IMBindingCompletionResult(
        binding=None,
        duplicate_event=True,
        acknowledgement={"result": "accepted", "event_id": "event-1"},
    )

    def _handle_binding_completion_callback(*, session, event):
        captured["session"] = session
        captured["event"] = event
        return completion_result

    im_service.handle_binding_completion_callback = _handle_binding_completion_callback
    consumer = FeishuLongConnectionBindingConsumer(im_service=im_service)
    session = object()
    result = consumer.consume_binding_completion_event(
        session=session,
        app_context=_configured_context(),
        raw_event={
            "event_id": "event-1",
            "binding_session_token": "imbs_token",
            "provider_workspace_id": "ws-1",
            "provider_user_id": "user-1",
        },
    )

    assert result == completion_result
    assert captured["session"] is session
    assert captured["event"].event_id == "event-1"


def test_long_connection_consumer_parses_submission_payload_via_provider_callback_parser() -> None:
    provider = type("Provider", (), {})()
    captured: dict[str, object] = {}
    parsed_submission = IMParsedProviderSubmission(
        event=IMSubmissionEvent(
            provider=IMProvider.FEISHU,
            event_id="event-1",
            provider_workspace_id="tenant-1",
            provider_user_id="open-id-1",
            interaction_id="interaction-1",
        ),
        parsed_payload=IMParsedSubmissionPayload(
            provider_action_id="provider_action_approve",
            provider_inputs={"provider_component_reason": "looks good"},
        ),
    )

    def _parse_submission_callback(*, app_context, payload, assume_verified):
        captured["app_context"] = app_context
        captured["payload"] = payload
        captured["assume_verified"] = assume_verified
        return parsed_submission

    provider.parse_submission_callback = _parse_submission_callback
    consumer = FeishuLongConnectionBindingConsumer(provider=provider)

    event, parsed_payload = consumer.parse_submission_payload(
        app_context=_configured_context(),
        raw_payload='{"schema":"2.0"}',
    )

    assert event == parsed_submission.event
    assert parsed_payload == parsed_submission.parsed_payload
    assert captured["app_context"] == _configured_context()
    assert captured["payload"] == b'{"schema":"2.0"}'
    assert captured["assume_verified"] is True


def test_long_connection_consumer_rejects_submission_parse_without_long_connection_mode() -> None:
    consumer = FeishuLongConnectionBindingConsumer()
    context = _configured_context().model_copy(update={"event_mode": IMEventMode.WEBHOOK})

    with pytest.raises(
        IMBindingValidationError,
        match="feishu long-connection consumer requires a configured long_connection app",
    ):
        consumer.parse_submission_payload(
            app_context=context,
            raw_payload=b'{"schema":"2.0"}',
        )
