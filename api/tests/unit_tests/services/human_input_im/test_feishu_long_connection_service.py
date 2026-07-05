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
