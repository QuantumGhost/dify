"""Application-layer helper for IM submission outcomes.

This coordinator keeps callback result handling small: persist the
``IMMessageCorrelation`` status transition first, then enqueue a placeholder
card-compensation command only for successful submissions.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session

from models.im_delivery import IMMessageCorrelation
from services.human_input_im.card_update_compensation_service import (
    IMCardUpdateCompensationQueue,
    IMCardUpdateCompensationService,
)
from services.human_input_im.message_status_service import IMMessageCorrelationStatusService


class HumanInputIMSubmissionResultService:
    _status_service: IMMessageCorrelationStatusService
    _compensation_service: IMCardUpdateCompensationService

    def __init__(
        self,
        status_service: IMMessageCorrelationStatusService | None = None,
        compensation_queue: IMCardUpdateCompensationQueue | None = None,
    ) -> None:
        self._status_service = status_service or IMMessageCorrelationStatusService()
        self._compensation_service = IMCardUpdateCompensationService(queue=compensation_queue)

    def mark_submitted(
        self,
        *,
        session: Session,
        correlation_id: str,
        provider_event_id: str,
        compensation_metadata: Mapping[str, str] | None = None,
    ) -> IMMessageCorrelation:
        correlation = self._status_service.mark_submitted(
            session=session,
            correlation_id=correlation_id,
            provider_event_id=provider_event_id,
        )
        self._compensation_service.enqueue_for_correlation(
            correlation,
            metadata=dict(compensation_metadata or {}),
        )
        return correlation

    def mark_validation_error(
        self,
        *,
        session: Session,
        correlation_id: str,
        provider_event_id: str,
        error_reason: str,
    ) -> IMMessageCorrelation:
        return self._status_service.mark_validation_error(
            session=session,
            correlation_id=correlation_id,
            provider_event_id=provider_event_id,
            error_reason=error_reason,
        )

    def mark_expired(
        self,
        *,
        session: Session,
        correlation_id: str,
        provider_event_id: str,
        error_reason: str,
    ) -> IMMessageCorrelation:
        return self._status_service.mark_expired(
            session=session,
            correlation_id=correlation_id,
            provider_event_id=provider_event_id,
            error_reason=error_reason,
        )

    def mark_already_handled(
        self,
        *,
        session: Session,
        correlation_id: str,
        provider_event_id: str,
        error_reason: str,
    ) -> IMMessageCorrelation:
        return self._status_service.mark_already_handled(
            session=session,
            correlation_id=correlation_id,
            provider_event_id=provider_event_id,
            error_reason=error_reason,
        )
