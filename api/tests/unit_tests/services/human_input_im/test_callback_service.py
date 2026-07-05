from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from core.repositories.human_input_repository import FormNotFoundError as RepositoryFormNotFoundError
from models.base import TypeBase
from models.human_input import RecipientType
from models.im_delivery import IMMessageCardStatus, IMMessageCorrelation, IMMessageDeliveryStatus, IMProcessedCallbackEvent
from models.im_integration import IMProvider
from services.errors.im_binding import IMBindingValidationError
from services.human_input_service import FormExpiredError, FormSubmittedError, InvalidFormDataError
from services.human_input_im.callback_service import (
    HumanInputIMCallbackService,
    IMFormSubmissionSubmitter,
    HumanInputIMSubmissionCommand,
    IMBindingCompletionEvent,
    IMInteractionActionMapping,
    IMInteractionInputMapping,
    IMInteractionMappingSnapshot,
    IMParsedSubmissionPayload,
    IMSubmissionCallbackResult,
    IMSubmissionCallbackContext,
)
from services.human_input_im.card_update_compensation_service import IMCardUpdateCompensationRequest
from services.human_input_im.provider_types import IMSubmissionEvent
from services.human_input_im.submission_result_service import HumanInputIMSubmissionResultService


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


def test_callback_service_handles_submission_success_and_enqueues_compensation() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(
        engine,
        tables=[IMProcessedCallbackEvent.__table__, IMMessageCorrelation.__table__],
    )
    correlation_id = _insert_correlation(engine, provider_message_id="message-1", error_reason="stale error")
    queue = MagicMock()
    submitter = MagicMock(spec=IMFormSubmissionSubmitter)
    service = HumanInputIMCallbackService(
        orchestration_service=MagicMock(),
        submission_result_service=HumanInputIMSubmissionResultService(compensation_queue=queue),
    )

    with Session(engine, expire_on_commit=False) as session:
        result = service.handle_submission(
            session=session,
            event=IMSubmissionEvent(
                provider=IMProvider.FEISHU,
                event_id="event-1",
                provider_workspace_id="ws-1",
                provider_user_id="user-1",
                interaction_id="interaction-1",
            ),
            context=_build_submission_context(correlation_id=correlation_id),
            parsed_payload=IMParsedSubmissionPayload(
                provider_action_id="provider_action_approve",
                provider_inputs={"provider_component_reason": "looks good"},
            ),
            submitter=submitter,
        )
        session.commit()

    assert result == IMSubmissionCallbackResult(
        acknowledgement={"result": "accepted", "event_id": "event-1"},
        duplicate_event=False,
    )
    submitter.submit_form_by_token.assert_called_once_with(
        recipient_type=RecipientType.STANDALONE_WEB_APP,
        form_token="form-token",
        selected_action_id="approve",
        form_data={"reason": "looks good"},
        submission_user_id="account-1",
        submission_end_user_id=None,
    )
    queue.enqueue.assert_called_once_with(
        IMCardUpdateCompensationRequest(
            correlation_id=correlation_id,
            provider=IMProvider.FEISHU,
            provider_message_id="message-1",
            target_status=IMMessageCardStatus.SUBMITTED,
            last_provider_event_id="event-1",
            metadata={"form_id": "form-1", "recipient_id": "recipient-1"},
        )
    )

    with Session(engine) as session:
        correlation = session.get(IMMessageCorrelation, correlation_id)

    assert correlation is not None
    assert correlation.delivery_status == IMMessageDeliveryStatus.SUBMITTED
    assert correlation.target_card_status == IMMessageCardStatus.SUBMITTED
    assert correlation.last_provider_event_id == "event-1"
    assert correlation.error_reason is None


@pytest.mark.parametrize(
    (
        "case_name",
        "submitter_side_effect",
        "binding_provider_user_id",
        "expected_delivery_status",
        "expected_card_status",
        "expected_error",
    ),
    [
        (
            "context validation error",
            None,
            "user-2",
            IMMessageDeliveryStatus.VALIDATION_ERROR,
            IMMessageCardStatus.ERROR,
            "provider user does not match active binding",
        ),
        (
            "invalid form data",
            InvalidFormDataError("invalid field"),
            "user-1",
            IMMessageDeliveryStatus.VALIDATION_ERROR,
            IMMessageCardStatus.ERROR,
            "invalid field",
        ),
        (
            "expired form",
            FormExpiredError("form-1"),
            "user-1",
            IMMessageDeliveryStatus.EXPIRED,
            IMMessageCardStatus.EXPIRED,
            "This form has expired, form_id=form-1",
        ),
        (
            "already handled form",
            FormSubmittedError("form-1"),
            "user-1",
            IMMessageDeliveryStatus.ALREADY_HANDLED,
            IMMessageCardStatus.ALREADY_HANDLED,
            "This form has already been submitted by another user, form_id=form-1",
        ),
        (
            "repository already submitted race",
            RepositoryFormNotFoundError("form already submitted, id=form-1"),
            "user-1",
            IMMessageDeliveryStatus.ALREADY_HANDLED,
            IMMessageCardStatus.ALREADY_HANDLED,
            "form already submitted, id=form-1",
        ),
    ],
)
def test_callback_service_maps_submission_outcomes_to_message_status(
    case_name: str,
    submitter_side_effect: Exception | None,
    binding_provider_user_id: str,
    expected_delivery_status: IMMessageDeliveryStatus,
    expected_card_status: IMMessageCardStatus,
    expected_error: str,
) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(
        engine,
        tables=[IMProcessedCallbackEvent.__table__, IMMessageCorrelation.__table__],
    )
    correlation_id = _insert_correlation(engine)
    queue = MagicMock()
    submitter = MagicMock(spec=IMFormSubmissionSubmitter)
    if submitter_side_effect is not None:
        submitter.submit_form_by_token.side_effect = submitter_side_effect
    service = HumanInputIMCallbackService(
        orchestration_service=MagicMock(),
        submission_result_service=HumanInputIMSubmissionResultService(compensation_queue=queue),
    )

    with Session(engine, expire_on_commit=False) as session:
        result = service.handle_submission(
            session=session,
            event=IMSubmissionEvent(
                provider=IMProvider.FEISHU,
                event_id=f"event-{case_name}",
                provider_workspace_id="ws-1",
                provider_user_id="user-1",
                interaction_id="interaction-1",
            ),
            context=_build_submission_context(
                correlation_id=correlation_id,
                binding_provider_user_id=binding_provider_user_id,
            ),
            parsed_payload=IMParsedSubmissionPayload(
                provider_action_id="provider_action_approve",
                provider_inputs={"provider_component_reason": "looks good"},
            ),
            submitter=submitter,
        )
        session.commit()

    assert result == IMSubmissionCallbackResult(
        acknowledgement={"result": "accepted", "event_id": f"event-{case_name}"},
        duplicate_event=False,
    )
    if submitter_side_effect is None:
        submitter.submit_form_by_token.assert_not_called()
    else:
        submitter.submit_form_by_token.assert_called_once()
    queue.enqueue.assert_not_called()

    with Session(engine) as session:
        correlation = session.get(IMMessageCorrelation, correlation_id)

    assert correlation is not None
    assert correlation.delivery_status == expected_delivery_status
    assert correlation.target_card_status == expected_card_status
    assert correlation.last_provider_event_id == f"event-{case_name}"
    assert correlation.error_reason == expected_error


def test_callback_service_acknowledges_duplicate_submission_event_without_resubmitting() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(
        engine,
        tables=[IMProcessedCallbackEvent.__table__, IMMessageCorrelation.__table__],
    )
    correlation_id = _insert_correlation(engine, provider_message_id="message-1")
    queue = MagicMock()
    submitter = MagicMock(spec=IMFormSubmissionSubmitter)
    service = HumanInputIMCallbackService(
        orchestration_service=MagicMock(),
        submission_result_service=HumanInputIMSubmissionResultService(compensation_queue=queue),
    )
    event = IMSubmissionEvent(
        provider=IMProvider.FEISHU,
        event_id="event-duplicate",
        provider_workspace_id="ws-1",
        provider_user_id="user-1",
        interaction_id="interaction-1",
    )

    with Session(engine, expire_on_commit=False) as session:
        first_result = service.handle_submission(
            session=session,
            event=event,
            context=_build_submission_context(correlation_id=correlation_id),
            parsed_payload=IMParsedSubmissionPayload(
                provider_action_id="provider_action_approve",
                provider_inputs={"provider_component_reason": "looks good"},
            ),
            submitter=submitter,
        )
        session.commit()

    with Session(engine, expire_on_commit=False) as session:
        second_result = service.handle_submission(
            session=session,
            event=event,
            context=_build_submission_context(correlation_id=correlation_id),
            parsed_payload=IMParsedSubmissionPayload(
                provider_action_id="provider_action_approve",
                provider_inputs={"provider_component_reason": "looks good"},
            ),
            submitter=submitter,
        )

    assert first_result == IMSubmissionCallbackResult(
        acknowledgement={"result": "accepted", "event_id": "event-duplicate"},
        duplicate_event=False,
    )
    assert second_result == IMSubmissionCallbackResult(
        acknowledgement={"result": "accepted", "event_id": "event-duplicate"},
        duplicate_event=True,
    )
    submitter.submit_form_by_token.assert_called_once()
    queue.enqueue.assert_called_once()


def _build_submission_context(
    *,
    correlation_id: str = "correlation-1",
    binding_provider_user_id: str = "user-1",
) -> IMSubmissionCallbackContext:
    return IMSubmissionCallbackContext(
        correlation_id=correlation_id,
        provider=IMProvider.FEISHU,
        form_token="form-token",
        recipient_type=RecipientType.STANDALONE_WEB_APP,
        binding_provider_workspace_id="ws-1",
        binding_provider_user_id=binding_provider_user_id,
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


def _insert_correlation(
    engine: sa.Engine,
    *,
    provider_message_id: str | None = "message-1",
    error_reason: str | None = None,
) -> str:
    with Session(engine) as session:
        correlation = IMMessageCorrelation(
            form_id="form-1",
            recipient_id="recipient-1",
            provider=IMProvider.FEISHU,
            interaction_mapping_snapshot="{}",
            provider_workspace_id="workspace-1",
            provider_message_id=provider_message_id,
            error_reason=error_reason,
        )
        session.add(correlation)
        session.commit()
        return correlation.id
