import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from models.base import TypeBase
from models.im_delivery import IMMessageCardStatus, IMMessageCorrelation, IMMessageDeliveryStatus
from models.im_integration import IMProvider
from services.human_input_im.message_status_service import IMMessageCorrelationStatusService


def test_message_status_service_marks_submitted_and_clears_error_reason() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMMessageCorrelation.__table__])
    correlation_id = _insert_correlation(engine, error_reason="stale error")

    service = IMMessageCorrelationStatusService()
    with Session(engine, expire_on_commit=False) as session:
        correlation = service.mark_submitted(
            session=session,
            correlation_id=correlation_id,
            provider_event_id="event-submitted",
        )
        session.commit()

    assert correlation.delivery_status == IMMessageDeliveryStatus.SUBMITTED
    assert correlation.target_card_status == IMMessageCardStatus.SUBMITTED
    assert correlation.last_provider_event_id == "event-submitted"
    assert correlation.error_reason is None


@pytest.mark.parametrize(
    ("marker_name", "expected_delivery_status", "expected_card_status", "error_reason"),
    [
        ("mark_validation_error", IMMessageDeliveryStatus.VALIDATION_ERROR, IMMessageCardStatus.ERROR, "invalid field"),
        ("mark_expired", IMMessageDeliveryStatus.EXPIRED, IMMessageCardStatus.EXPIRED, "form expired"),
        (
            "mark_already_handled",
            IMMessageDeliveryStatus.ALREADY_HANDLED,
            IMMessageCardStatus.ALREADY_HANDLED,
            "already submitted",
        ),
    ],
)
def test_message_status_service_marks_non_success_outcomes(
    marker_name: str,
    expected_delivery_status: IMMessageDeliveryStatus,
    expected_card_status: IMMessageCardStatus,
    error_reason: str,
) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMMessageCorrelation.__table__])
    correlation_id = _insert_correlation(engine)

    service = IMMessageCorrelationStatusService()
    with Session(engine, expire_on_commit=False) as session:
        marker = getattr(service, marker_name)
        correlation = marker(
            session=session,
            correlation_id=correlation_id,
            provider_event_id="event-error",
            error_reason=error_reason,
        )
        session.commit()

    assert correlation.delivery_status == expected_delivery_status
    assert correlation.target_card_status == expected_card_status
    assert correlation.last_provider_event_id == "event-error"
    assert correlation.error_reason == error_reason


def test_message_status_service_raises_lookup_error_for_missing_correlation() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMMessageCorrelation.__table__])

    service = IMMessageCorrelationStatusService()
    with Session(engine, expire_on_commit=False) as session:
        with pytest.raises(LookupError, match="IM message correlation not found: missing-correlation"):
            service.mark_submitted(
                session=session,
                correlation_id="missing-correlation",
                provider_event_id="event-submitted",
            )


def _insert_correlation(
    engine: sa.Engine,
    *,
    error_reason: str | None = None,
) -> str:
    with Session(engine) as session:
        correlation = IMMessageCorrelation(
            form_id="form-1",
            recipient_id="recipient-1",
            provider=IMProvider.FEISHU,
            interaction_mapping_snapshot="{}",
            provider_workspace_id="workspace-1",
            provider_message_id="message-1",
            error_reason=error_reason,
        )
        session.add(correlation)
        session.commit()
        return correlation.id
