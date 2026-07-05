from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from models.base import TypeBase
from models.human_input import RecipientType
from models.im_delivery import IMProcessedCallbackEvent
from models.im_integration import IMProvider
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.callback_service import (
    HumanInputIMCallbackService,
    HumanInputIMSubmissionCommand,
    IMBindingCompletionEvent,
    IMInteractionActionMapping,
    IMInteractionInputMapping,
    IMInteractionMappingSnapshot,
    IMParsedSubmissionPayload,
    IMSubmissionCallbackContext,
)
from services.human_input_im.provider_types import IMSubmissionEvent


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
    session = MagicMock()
    binding = object()
    orchestration_service = MagicMock()
    orchestration_service.complete_binding_session.return_value = binding

    service = HumanInputIMCallbackService(orchestration_service=orchestration_service)
    service.record_event_once = lambda **_: True
    result = service.complete_binding(session=session, event=event)

    assert result is binding
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


def test_callback_service_returns_none_for_duplicate_binding_event() -> None:
    event = IMBindingCompletionEvent(
        provider=IMProvider.FEISHU,
        event_id="event-1",
        binding_session_token="imbs_token",
        provider_workspace_id="ws-1",
        provider_user_id="user-1",
    )
    session = object()
    service = HumanInputIMCallbackService(orchestration_service=MagicMock())

    service.record_event_once = lambda **_: False
    result = service.complete_binding(session=session, event=event)

    assert result is None


def test_callback_service_rejects_submission_when_binding_user_mismatches() -> None:
    service = HumanInputIMCallbackService(orchestration_service=MagicMock())

    with pytest.raises(IMBindingValidationError, match="provider user does not match active binding"):
        service.build_submission_command(
            event=IMSubmissionEvent(
                provider=IMProvider.FEISHU,
                event_id="event-1",
                provider_workspace_id="ws-1",
                provider_user_id="user-2",
                interaction_id="interaction-1",
            ),
            context=_build_submission_context(),
            parsed_payload=IMParsedSubmissionPayload(
                provider_action_id="provider_action_approve",
                provider_inputs={"provider_component_reason": "looks good"},
            ),
        )


def test_callback_service_rejects_submission_for_unknown_interaction_mapping() -> None:
    service = HumanInputIMCallbackService(orchestration_service=MagicMock())

    with pytest.raises(IMBindingValidationError, match="unknown IM callback interaction mapping"):
        service.build_submission_command(
            event=IMSubmissionEvent(
                provider=IMProvider.FEISHU,
                event_id="event-1",
                provider_workspace_id="ws-1",
                provider_user_id="user-1",
                interaction_id="interaction-unknown",
            ),
            context=_build_submission_context(),
            parsed_payload=IMParsedSubmissionPayload(
                provider_action_id="provider_action_approve",
                provider_inputs={"provider_component_reason": "looks good"},
            ),
        )


def test_callback_service_maps_submission_payload_to_human_input_submit_arguments() -> None:
    service = HumanInputIMCallbackService(orchestration_service=MagicMock())

    result = service.build_submission_command(
        event=IMSubmissionEvent(
            provider=IMProvider.FEISHU,
            event_id="event-1",
            provider_workspace_id="ws-1",
            provider_user_id="user-1",
            interaction_id="interaction-1",
        ),
        context=_build_submission_context(),
        parsed_payload=IMParsedSubmissionPayload(
            provider_action_id="provider_action_approve",
            provider_inputs={"provider_component_reason": "looks good"},
        ),
    )

    assert result == HumanInputIMSubmissionCommand(
        recipient_type=RecipientType.STANDALONE_WEB_APP,
        form_token="form-token",
        selected_action_id="approve",
        form_data={"reason": "looks good"},
        submission_user_id="account-1",
        submission_end_user_id=None,
    )


def _build_submission_context() -> IMSubmissionCallbackContext:
    return IMSubmissionCallbackContext(
        provider=IMProvider.FEISHU,
        form_token="form-token",
        recipient_type=RecipientType.STANDALONE_WEB_APP,
        binding_provider_workspace_id="ws-1",
        binding_provider_user_id="user-1",
        recipient_provider_workspace_id="ws-1",
        recipient_provider_user_id="user-1",
        interaction_mapping=IMInteractionMappingSnapshot(
            interaction_id="interaction-1",
            inputs={
                "provider_component_reason": IMInteractionInputMapping(
                    output_variable_name="reason",
                    type="paragraph",
                )
            },
            actions={
                "provider_action_approve": IMInteractionActionMapping(
                    action_id="approve",
                )
            },
        ),
        submission_user_id="account-1",
    )
