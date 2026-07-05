from unittest.mock import MagicMock

import pytest

from models.im_integration import IMProvider
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.callback_service import IMBindingCompletionEvent
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
