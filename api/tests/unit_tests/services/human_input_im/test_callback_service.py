from unittest.mock import MagicMock

import sqlalchemy as sa
from sqlalchemy.orm import Session

from models.base import TypeBase
from models.im_delivery import IMProcessedCallbackEvent
from models.im_integration import IMProvider
from services.human_input_im.callback_service import HumanInputIMCallbackService, IMBindingCompletionEvent


def test_callback_service_delegates_binding_completion() -> None:
    event = IMBindingCompletionEvent(
        provider=IMProvider.FEISHU,
        event_id="event-1",
        binding_session_token="imbs_token",
        provider_workspace_id="ws-1",
        provider_user_id="user-1",
        provider_union_id="union-1",
        provider_user_display_name="User 1",
        provider_user_avatar_url=None,
    )
    session = object()
    binding = object()
    orchestration_service = MagicMock()
    orchestration_service.complete_binding_session.return_value = binding

    service = HumanInputIMCallbackService(orchestration_service=orchestration_service)
    result = service.complete_binding(session=session, event=event)

    assert result is binding
    orchestration_service.get_provider_or_raise.assert_called_once_with(IMProvider.FEISHU)
    orchestration_service.complete_binding_session.assert_called_once_with(
        session=session,
        token="imbs_token",
        provider_workspace_id="ws-1",
        provider_user_id="user-1",
        provider_union_id="union-1",
        provider_user_display_name="User 1",
        provider_user_avatar_url=None,
    )


def test_callback_service_records_duplicate_event_ids_as_already_processed() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMProcessedCallbackEvent.__table__])

    service = HumanInputIMCallbackService(orchestration_service=MagicMock())
    with Session(engine) as session:
        first_result = service.record_event_once(
            session=session,
            provider=IMProvider.FEISHU,
            event_id="event-1",
        )
        session.commit()

        second_result = service.record_event_once(
            session=session,
            provider=IMProvider.FEISHU,
            event_id="event-1",
        )

    assert first_result is True
    assert second_result is False
