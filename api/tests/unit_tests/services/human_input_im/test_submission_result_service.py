from unittest.mock import MagicMock

import sqlalchemy as sa
from sqlalchemy.orm import Session

from models.base import TypeBase
from models.im_delivery import IMMessageCardStatus, IMMessageCorrelation, IMMessageDeliveryStatus
from models.im_integration import IMProvider
from services.human_input_im.card_update_compensation_service import IMCardUpdateCompensationRequest
from services.human_input_im.submission_result_service import HumanInputIMSubmissionResultService


def test_submission_result_service_marks_submitted_and_enqueues_card_compensation() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMMessageCorrelation.__table__])
    correlation_id = _insert_correlation(engine, provider_message_id="message-1", error_reason="stale error")
    queue = MagicMock()

    service = HumanInputIMSubmissionResultService(compensation_queue=queue)
    with Session(engine, expire_on_commit=False) as session:
        correlation = service.mark_submitted(
            session=session,
            correlation_id=correlation_id,
            provider_event_id="event-1",
        )
        session.commit()

    assert correlation.delivery_status == IMMessageDeliveryStatus.SUBMITTED
    assert correlation.target_card_status == IMMessageCardStatus.SUBMITTED
    assert correlation.last_provider_event_id == "event-1"
    assert correlation.error_reason is None
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


def test_submission_result_service_skips_compensation_when_provider_message_is_missing() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMMessageCorrelation.__table__])
    correlation_id = _insert_correlation(engine, provider_message_id=None)
    queue = MagicMock()

    service = HumanInputIMSubmissionResultService(compensation_queue=queue)
    with Session(engine, expire_on_commit=False) as session:
        correlation = service.mark_submitted(
            session=session,
            correlation_id=correlation_id,
            provider_event_id="event-1",
        )
        session.commit()

    assert correlation.delivery_status == IMMessageDeliveryStatus.SUBMITTED
    queue.enqueue.assert_not_called()


def test_submission_result_service_marks_non_success_outcomes_without_enqueuing() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMMessageCorrelation.__table__])
    queue = MagicMock()
    service = HumanInputIMSubmissionResultService(compensation_queue=queue)

    validation_error_id = _insert_correlation(engine)
    expired_id = _insert_correlation(engine)
    already_handled_id = _insert_correlation(engine)

    with Session(engine, expire_on_commit=False) as session:
        validation_error = service.mark_validation_error(
            session=session,
            correlation_id=validation_error_id,
            provider_event_id="event-validation",
            error_reason="invalid field",
        )
        expired = service.mark_expired(
            session=session,
            correlation_id=expired_id,
            provider_event_id="event-expired",
            error_reason="form expired",
        )
        already_handled = service.mark_already_handled(
            session=session,
            correlation_id=already_handled_id,
            provider_event_id="event-handled",
            error_reason="first valid submission already won",
        )
        session.commit()

    assert validation_error.delivery_status == IMMessageDeliveryStatus.VALIDATION_ERROR
    assert validation_error.target_card_status == IMMessageCardStatus.ERROR
    assert validation_error.last_provider_event_id == "event-validation"
    assert validation_error.error_reason == "invalid field"

    assert expired.delivery_status == IMMessageDeliveryStatus.EXPIRED
    assert expired.target_card_status == IMMessageCardStatus.EXPIRED
    assert expired.last_provider_event_id == "event-expired"
    assert expired.error_reason == "form expired"

    assert already_handled.delivery_status == IMMessageDeliveryStatus.ALREADY_HANDLED
    assert already_handled.target_card_status == IMMessageCardStatus.ALREADY_HANDLED
    assert already_handled.last_provider_event_id == "event-handled"
    assert already_handled.error_reason == "first valid submission already won"

    queue.enqueue.assert_not_called()


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
