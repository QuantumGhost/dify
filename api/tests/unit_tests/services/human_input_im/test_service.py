from unittest.mock import MagicMock

import pytest

from models.im_delivery import IMMessageCardStatus
from models.im_integration import IMInstallMode, IMProvider, IMScopeType
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.app_config_service import IMAppConfigStatus, IMAppContext, IMTokenStatus
from services.human_input_im.callback_service import IMBindingCompletionEvent
from services.human_input_im.provider_types import IMCardUpdateCommand, IMSendCommand, IMSendResult
from services.human_input_im.service import HumanInputIMService


def test_service_raises_when_provider_is_not_registered() -> None:
    orchestration_service = MagicMock()
    orchestration_service.get_provider_or_raise.side_effect = IMBindingValidationError(
        "IM provider is not registered: feishu"
    )
    service = HumanInputIMService(orchestration_service=orchestration_service)

    with pytest.raises(IMBindingValidationError, match="IM provider is not registered: feishu"):
        service.get_provider_or_raise(IMProvider.FEISHU)


def test_service_acknowledges_duplicate_binding_callback_event() -> None:
    callback_service = MagicMock()
    callback_service.complete_binding.return_value = None
    callback_service.acknowledge_event.return_value = {"result": "accepted", "event_id": "event-1"}
    service = HumanInputIMService(callback_service=callback_service)

    result = service.handle_binding_completion_callback(
        session=object(),
        event=IMBindingCompletionEvent(
            provider=IMProvider.FEISHU,
            event_id="event-1",
            binding_session_token="imbs_token",
            provider_workspace_id="ws-1",
            provider_user_id="user-1",
        ),
    )

    assert result.binding is None
    assert result.duplicate_event is True
    assert result.acknowledgement == {"result": "accepted", "event_id": "event-1"}


def test_service_raises_when_sending_form_for_unregistered_provider() -> None:
    orchestration_service = MagicMock()
    orchestration_service.get_provider_or_raise.side_effect = IMBindingValidationError(
        "IM provider is not registered: feishu"
    )
    service = HumanInputIMService(orchestration_service=orchestration_service)

    with pytest.raises(IMBindingValidationError, match="IM provider is not registered: feishu"):
        service.send_form(
            provider=IMProvider.FEISHU,
            tenant_id="tenant-1",
            recipient_id="user-1",
            form_id="form-1",
            title="Need approval",
            content="Please approve",
        )

    orchestration_service.resolve_app_context.assert_not_called()


def test_service_delegates_form_send_with_resolved_app_context() -> None:
    app_context = _build_app_context()
    provider = MagicMock()
    provider.send_form.return_value = IMSendResult(
        provider=IMProvider.FEISHU,
        accepted=True,
        provider_message_id="message-1",
    )
    orchestration_service = MagicMock()
    orchestration_service.get_provider_or_raise.return_value = provider
    orchestration_service.resolve_app_context.return_value = app_context
    service = HumanInputIMService(orchestration_service=orchestration_service)

    result = service.send_form(
        provider=IMProvider.FEISHU,
        tenant_id="tenant-1",
        recipient_id="user-1",
        form_id="form-1",
        title="Need approval",
        content="Please approve",
        metadata={"recipient_id": "recipient-1"},
    )

    assert result == IMSendResult(
        provider=IMProvider.FEISHU,
        accepted=True,
        provider_message_id="message-1",
    )
    orchestration_service.get_provider_or_raise.assert_called_once_with(IMProvider.FEISHU)
    orchestration_service.resolve_app_context.assert_called_once_with(provider=IMProvider.FEISHU, tenant_id="tenant-1")
    provider.send_form.assert_called_once_with(
        IMSendCommand(
            provider=IMProvider.FEISHU,
            app_context=app_context,
            recipient_id="user-1",
            form_id="form-1",
            title="Need approval",
            content="Please approve",
            metadata={"recipient_id": "recipient-1"},
        )
    )


def test_service_delegates_card_update_with_resolved_app_context() -> None:
    app_context = _build_app_context()
    provider = MagicMock()
    orchestration_service = MagicMock()
    orchestration_service.get_provider_or_raise.return_value = provider
    orchestration_service.resolve_app_context.return_value = app_context
    service = HumanInputIMService(orchestration_service=orchestration_service)

    service.update_card(
        provider=IMProvider.FEISHU,
        tenant_id="tenant-1",
        provider_message_id="message-1",
        target_status=IMMessageCardStatus.SUBMITTED.value,
        metadata={"correlation_id": "correlation-1"},
    )

    orchestration_service.get_provider_or_raise.assert_called_once_with(IMProvider.FEISHU)
    orchestration_service.resolve_app_context.assert_called_once_with(provider=IMProvider.FEISHU, tenant_id="tenant-1")
    provider.update_card.assert_called_once_with(
        IMCardUpdateCommand(
            provider=IMProvider.FEISHU,
            app_context=app_context,
            provider_message_id="message-1",
            target_status=IMMessageCardStatus.SUBMITTED.value,
            metadata={"correlation_id": "correlation-1"},
        )
    )


def _build_app_context() -> IMAppContext:
    return IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=IMAppConfigStatus.CONFIGURED,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        app_id="cli_a",
        app_secret_configured=True,
    )
