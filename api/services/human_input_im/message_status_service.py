"""Persistence helper for IM callback submission outcomes.

This module owns the narrow mapping from callback outcomes to
``IMMessageCorrelation`` status fields. It deliberately avoids queueing or
provider I/O so later callback orchestration can reuse the same status writes
without coupling persistence to transport concerns.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.im_delivery import IMMessageCardStatus, IMMessageCorrelation, IMMessageDeliveryStatus


class IMMessageCorrelationStatusService:
    def mark_submitted(
        self,
        *,
        session: Session,
        correlation_id: str,
        provider_event_id: str,
    ) -> IMMessageCorrelation:
        return self._update_status(
            session=session,
            correlation_id=correlation_id,
            provider_event_id=provider_event_id,
            delivery_status=IMMessageDeliveryStatus.SUBMITTED,
            target_card_status=IMMessageCardStatus.SUBMITTED,
            error_reason=None,
        )

    def mark_validation_error(
        self,
        *,
        session: Session,
        correlation_id: str,
        provider_event_id: str,
        error_reason: str,
    ) -> IMMessageCorrelation:
        return self._update_status(
            session=session,
            correlation_id=correlation_id,
            provider_event_id=provider_event_id,
            delivery_status=IMMessageDeliveryStatus.VALIDATION_ERROR,
            target_card_status=IMMessageCardStatus.ERROR,
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
        return self._update_status(
            session=session,
            correlation_id=correlation_id,
            provider_event_id=provider_event_id,
            delivery_status=IMMessageDeliveryStatus.EXPIRED,
            target_card_status=IMMessageCardStatus.EXPIRED,
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
        return self._update_status(
            session=session,
            correlation_id=correlation_id,
            provider_event_id=provider_event_id,
            delivery_status=IMMessageDeliveryStatus.ALREADY_HANDLED,
            target_card_status=IMMessageCardStatus.ALREADY_HANDLED,
            error_reason=error_reason,
        )

    def _update_status(
        self,
        *,
        session: Session,
        correlation_id: str,
        provider_event_id: str,
        delivery_status: IMMessageDeliveryStatus,
        target_card_status: IMMessageCardStatus,
        error_reason: str | None,
    ) -> IMMessageCorrelation:
        correlation = session.get(IMMessageCorrelation, correlation_id)
        if correlation is None:
            raise LookupError(f"IM message correlation not found: {correlation_id}")

        correlation.delivery_status = delivery_status
        correlation.target_card_status = target_card_status
        correlation.last_provider_event_id = provider_event_id
        correlation.error_reason = error_reason
        session.flush([correlation])
        return correlation
