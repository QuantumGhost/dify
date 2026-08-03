"""Internal provider client roles composed by one adapter-owned context.

These protocols are infrastructure seams, not consumer-facing contracts. Each
concrete provider supplies only the roles it supports; unsupported card,
Webhook, or stream operations are represented by an absent role and view.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import RLock
from typing import Protocol, TypeVar

from .contracts import (
    AuthenticatedIMEvent,
    CardAssessmentResult,
    CardIntent,
    CredentialTestResult,
    DestinationTestResult,
    DirectoryReadResult,
    EventAcceptance,
    MessageResult,
    OpaqueMetadata,
    StopSignal,
    StreamRunResult,
    WebhookParseResult,
    WebhookRequest,
)

DestinationT = TypeVar("DestinationT", contravariant=True)
ReferenceT = TypeVar("ReferenceT")
MessagingReferenceT = TypeVar("MessagingReferenceT", covariant=True)

logger = logging.getLogger(__name__)


class _ProviderClientCloseError(RuntimeError):
    """Safe aggregate error for one or more provider client cleanup failures."""

    def __init__(self, failure_count: int) -> None:
        super().__init__(f"provider client cleanup failed for {failure_count} resource(s)")


class _CredentialClient(Protocol):
    def test_credentials(self) -> CredentialTestResult: ...


class _DirectoryClient(Protocol):
    def read_directory(self) -> DirectoryReadResult: ...


class _MessagingClient(Protocol[DestinationT, MessagingReferenceT]):
    def test_destination(self, destination: DestinationT) -> DestinationTestResult: ...

    def send_text(self, destination: DestinationT, body: str) -> MessageResult[MessagingReferenceT]: ...


class _CardClient(Protocol[DestinationT, ReferenceT]):
    def assess_card(self, intent: CardIntent) -> CardAssessmentResult: ...

    def send_card(
        self,
        destination: DestinationT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]: ...

    def update_card(
        self,
        reference: ReferenceT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]: ...


class _WebhookClient(Protocol):
    def parse_webhook(self, request: WebhookRequest) -> WebhookParseResult: ...


class _StreamClient(Protocol):
    def run_stream(
        self,
        accept: Callable[[AuthenticatedIMEvent], EventAcceptance],
        stop: StopSignal,
    ) -> StreamRunResult: ...


class _ClosableClient(Protocol):
    def close(self) -> None: ...


class _ProviderClientContext[DestinationT, ReferenceT]:
    """One adapter-owned bundle of narrow provider client roles."""

    credentials: _CredentialClient
    directory: _DirectoryClient
    messaging: _MessagingClient[DestinationT, ReferenceT]
    card: _CardClient[DestinationT, ReferenceT] | None
    webhook: _WebhookClient | None
    stream: _StreamClient | None
    _pending_resources: list[_ClosableClient]
    _close_lock: RLock

    def __init__(
        self,
        *,
        credentials: _CredentialClient,
        directory: _DirectoryClient,
        messaging: _MessagingClient[DestinationT, ReferenceT],
        card: _CardClient[DestinationT, ReferenceT] | None,
        webhook: _WebhookClient | None,
        stream: _StreamClient | None,
        owned_resources: tuple[_ClosableClient, ...],
    ) -> None:
        self.credentials = credentials
        self.directory = directory
        self.messaging = messaging
        self.card = card
        self.webhook = webhook
        self.stream = stream
        self._pending_resources = list(owned_resources)
        self._close_lock = RLock()

    def close(self) -> None:
        """Best-effort close all resources and retain only failures for retry."""
        with self._close_lock:
            failed_resources: list[_ClosableClient] = []
            for resource_index, resource in enumerate(self._pending_resources):
                try:
                    resource.close()
                except Exception:
                    logger.exception(
                        "IM provider client cleanup failed; retaining resource for retry",
                        extra={"provider_client_resource_index": resource_index},
                    )
                    failed_resources.append(resource)
            self._pending_resources = failed_resources
            if failed_resources:
                raise _ProviderClientCloseError(len(failed_resources))
