"""Application-layer seam for asynchronous IM card update compensation.

The phase-1 callback path should not block workflow resume on provider card
updates. This module defines the queue payload shape now, while the actual task
queue integration can be added later behind the same interface.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from models.im_delivery import IMMessageCardStatus, IMMessageCorrelation
from models.im_integration import IMProvider
from services.human_input_observability import build_human_input_log_context

logger = logging.getLogger(__name__)


class IMCardUpdateCompensationRequest(BaseModel):
    correlation_id: str
    provider: IMProvider
    provider_message_id: str
    target_status: IMMessageCardStatus
    last_provider_event_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


class IMCardUpdateCompensationQueue(Protocol):
    def enqueue(self, request: IMCardUpdateCompensationRequest) -> None: ...


class LoggingIMCardUpdateCompensationQueue:
    """Placeholder queue adapter until a real async task is wired in."""

    def enqueue(self, request: IMCardUpdateCompensationRequest) -> None:
        logger.info(
            "Queued IM card update compensation placeholder",
            extra=build_human_input_log_context(
                provider=request.provider,
                provider_message_id=request.provider_message_id,
                provider_event_id=request.last_provider_event_id,
                extra={
                    "correlation_id": request.correlation_id,
                    "target_card_status": request.target_status,
                    **request.metadata,
                },
            ),
        )


class IMCardUpdateCompensationService:
    _queue: IMCardUpdateCompensationQueue

    def __init__(self, queue: IMCardUpdateCompensationQueue | None = None) -> None:
        self._queue = queue or LoggingIMCardUpdateCompensationQueue()

    def enqueue_for_correlation(
        self,
        correlation: IMMessageCorrelation,
        metadata: Mapping[str, str] | None = None,
    ) -> IMCardUpdateCompensationRequest | None:
        """Build and enqueue the later async card-update task payload.

        Missing ``provider_message_id`` means the delivery never produced a
        provider-side card handle, so there is nothing meaningful to enqueue.
        """

        if not correlation.provider_message_id:
            return None

        request = IMCardUpdateCompensationRequest(
            correlation_id=correlation.id,
            provider=correlation.provider,
            provider_message_id=correlation.provider_message_id,
            target_status=correlation.target_card_status,
            last_provider_event_id=correlation.last_provider_event_id,
            metadata={
                "form_id": correlation.form_id,
                "recipient_id": correlation.recipient_id,
                **dict(metadata or {}),
            },
        )
        self._queue.enqueue(request)
        return request
