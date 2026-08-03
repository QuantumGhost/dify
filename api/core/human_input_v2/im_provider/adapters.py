"""Explicit immutable adapters for the five initial IM provider families.

Each root lazily constructs one provider client context, serializes ordinary
SDK calls for conservative client safety, and owns context disposal. Capability
views are stable wrappers over that root and never construct clients. Stream
execution is not held under the ordinary call lock because ``close`` must be
able to close a live connection; concrete stream roles must therefore make
``close`` interrupt a running stream and suppress reconnect.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import RLock
from typing import override

from core.human_input_v2.entities import IMProvider

from .client_roles import _ProviderClientContext
from .contracts import (
    AuthenticatedIMEvent,
    CardAssessmentResult,
    CardIntent,
    CredentialTestResult,
    DestinationTestResult,
    DirectoryReadResult,
    EventAcceptance,
    IMDirectory,
    IMDynamicCardMessaging,
    IMEventSink,
    IMMessaging,
    IMStreamEvents,
    IMWebhookEvents,
    MessageResult,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
    StopSignal,
    StreamRunResult,
    WebhookChallenge,
    WebhookDelivery,
    WebhookRejected,
    WebhookRequest,
    WebhookResponse,
)
from .provider_types import (
    DingTalkAdapterConfig,
    DingTalkMessageReference,
    DingTalkUserDestination,
    FeishuLarkAdapterConfig,
    FeishuMessageReference,
    FeishuUserDestination,
    MicrosoftTeamsAdapterConfig,
    SlackAdapterConfig,
    SlackMessageReference,
    SlackUserDestination,
    TeamsMessageReference,
    TeamsPersonalConversationDestination,
    WeComAdapterConfig,
    WeComMessageReference,
    WeComUserDestination,
)

logger = logging.getLogger(__name__)


def _create_slack_client_context(
    config: SlackAdapterConfig,
) -> _ProviderClientContext[SlackUserDestination, SlackMessageReference]:
    from .providers.slack import create_slack_client_context

    return create_slack_client_context(config)


def _create_feishu_lark_client_context(
    config: FeishuLarkAdapterConfig,
) -> _ProviderClientContext[FeishuUserDestination, FeishuMessageReference]:
    from .providers.feishu_lark import create_feishu_lark_client_context

    return create_feishu_lark_client_context(config)


def _create_dingtalk_client_context(
    config: DingTalkAdapterConfig,
) -> _ProviderClientContext[DingTalkUserDestination, DingTalkMessageReference]:
    from .providers.dingtalk import create_dingtalk_client_context

    return create_dingtalk_client_context(config)


def _create_wecom_client_context(
    config: WeComAdapterConfig,
) -> _ProviderClientContext[WeComUserDestination, WeComMessageReference]:
    from .providers.wecom import create_wecom_client_context

    return create_wecom_client_context(config)


def _create_microsoft_teams_client_context(
    config: MicrosoftTeamsAdapterConfig,
) -> _ProviderClientContext[TeamsPersonalConversationDestination, TeamsMessageReference]:
    from .providers.microsoft_teams import create_microsoft_teams_client_context

    return create_microsoft_teams_client_context(config)


class AdapterCloseError(RuntimeError):
    """Safe lifecycle error raised when an owned provider context is not closed."""

    provider: IMProvider

    def __init__(self, provider: IMProvider) -> None:
        self.provider = provider
        provider_name = provider.value.replace("_", " ").title()
        super().__init__(f"{provider_name} adapter cleanup failed")


class _DirectoryView[DestinationT, ReferenceT, ConfigT](IMDirectory):
    """Stable directory view over one adapter-owned client context."""

    _root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]

    def __init__(self, root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]) -> None:
        self._root = root

    @override
    def read_snapshot(self) -> DirectoryReadResult:
        return self._root._read_directory()


class _MessagingView[DestinationT, ReferenceT, ConfigT](IMMessaging[DestinationT, ReferenceT]):
    """Stable basic messaging view over one adapter-owned client context."""

    _root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]

    def __init__(self, root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]) -> None:
        self._root = root

    @override
    def test_destination(self, destination: DestinationT) -> DestinationTestResult:
        return self._root._test_destination(destination)

    @override
    def send_text(self, destination: DestinationT, body: str) -> MessageResult[ReferenceT]:
        return self._root._send_text(destination, body)


class _DynamicCardMessagingView[DestinationT, ReferenceT, ConfigT](IMDynamicCardMessaging[DestinationT, ReferenceT]):
    """Stable optional card view over one adapter-owned client context."""

    _root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]

    def __init__(self, root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]) -> None:
        self._root = root

    @override
    def assess(self, intent: CardIntent) -> CardAssessmentResult:
        return self._root._assess_card(intent)

    @override
    def send_card(
        self,
        destination: DestinationT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]:
        return self._root._send_card(destination, intent, metadata)

    @override
    def update_card(
        self,
        reference: ReferenceT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]:
        return self._root._update_card(reference, intent, metadata)


class _WebhookEventsView[DestinationT, ReferenceT, ConfigT](IMWebhookEvents):
    """Stable Webhook view that owns sink invocation and ACK selection."""

    _root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]

    def __init__(self, root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]) -> None:
        self._root = root

    @override
    def handle(self, request: WebhookRequest, sink: IMEventSink) -> WebhookResponse:
        return self._root._handle_webhook(request, sink)


class _StreamEventsView[DestinationT, ReferenceT, ConfigT](IMStreamEvents):
    """Stable stream view that keeps ACK decisions in the provider callback."""

    _root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]

    def __init__(self, root: _AdapterRoot[DestinationT, ReferenceT, ConfigT]) -> None:
        self._root = root

    @override
    def run(self, sink: IMEventSink, stop: StopSignal) -> StreamRunResult:
        return self._root._run_stream(sink, stop)


class _AdapterRoot[DestinationT, ReferenceT, ConfigT]:
    """Shared resource lifecycle; concrete public composition remains explicit.

    The ordinary operation lock serializes API and Webhook access because the
    provider SDK concurrency guarantees are not uniform. A concrete client
    context may pool internally, but callers never coordinate provider locks or
    resources.
    """

    _provider: IMProvider
    _config: ConfigT
    _context_factory: Callable[[ConfigT], _ProviderClientContext[DestinationT, ReferenceT]]
    _context: _ProviderClientContext[DestinationT, ReferenceT] | None
    _closed: bool
    _cleanup_complete: bool
    _lifecycle_lock: RLock
    _operation_lock: RLock
    _closed_failure: OperationFailure
    _closed_webhook_response: WebhookResponse
    _accepted_webhook_replays: dict[str, float]
    _directory_view: _DirectoryView[DestinationT, ReferenceT, ConfigT]
    _messaging_view: _MessagingView[DestinationT, ReferenceT, ConfigT]
    _dynamic_card_view: _DynamicCardMessagingView[DestinationT, ReferenceT, ConfigT] | None
    _webhook_view: _WebhookEventsView[DestinationT, ReferenceT, ConfigT] | None
    _stream_view: _StreamEventsView[DestinationT, ReferenceT, ConfigT] | None

    def __init__(
        self,
        provider: IMProvider,
        config: ConfigT,
        context_factory: Callable[[ConfigT], _ProviderClientContext[DestinationT, ReferenceT]],
        *,
        dynamic_cards: bool,
        webhook_events: bool,
        stream_events: bool,
    ) -> None:
        self._provider = provider
        self._config = config
        self._context_factory = context_factory
        self._context = None
        self._closed = False
        self._cleanup_complete = False
        self._lifecycle_lock = RLock()
        self._operation_lock = RLock()
        self._closed_failure = OperationFailure(provider, OperationFailureCode.CLOSED, "adapter is closed")
        self._closed_webhook_response = WebhookResponse(
            status_code=503,
            headers=(("content-type", "text/plain; charset=utf-8"),),
            body=b"adapter is closed",
        )
        self._accepted_webhook_replays = {}
        self._directory_view = _DirectoryView(self)
        self._messaging_view = _MessagingView(self)
        self._dynamic_card_view = _DynamicCardMessagingView(self) if dynamic_cards else None
        self._webhook_view = _WebhookEventsView(self) if webhook_events else None
        self._stream_view = _StreamEventsView(self) if stream_events else None

    @property
    def directory(self) -> IMDirectory:
        return self._directory_view

    @property
    def messaging(self) -> IMMessaging[DestinationT, ReferenceT]:
        return self._messaging_view

    @property
    def dynamic_card_messaging(self) -> IMDynamicCardMessaging[DestinationT, ReferenceT] | None:
        return self._dynamic_card_view

    @property
    def webhook_events(self) -> IMWebhookEvents | None:
        return self._webhook_view

    @property
    def stream_events(self) -> IMStreamEvents | None:
        return self._stream_view

    def _context_for_operation(self) -> _ProviderClientContext[DestinationT, ReferenceT] | None:
        with self._lifecycle_lock:
            if self._closed:
                return None
            if self._context is None:
                self._context = self._context_factory(self._config)
            return self._context

    def _execute[SuccessT](
        self,
        operation: Callable[
            [_ProviderClientContext[DestinationT, ReferenceT]],
            SuccessT | OperationFailure,
        ],
    ) -> SuccessT | OperationFailure:
        with self._operation_lock:
            context = self._context_for_operation()
            if context is None:
                return self._closed_failure
            return operation(context)

    def test_credentials(self) -> CredentialTestResult:
        return self._execute(lambda context: context.credentials.test_credentials())

    def _read_directory(self) -> DirectoryReadResult:
        return self._execute(lambda context: context.directory.read_directory())

    def _test_destination(self, destination: DestinationT) -> DestinationTestResult:
        return self._execute(lambda context: context.messaging.test_destination(destination))

    def _send_text(self, destination: DestinationT, body: str) -> MessageResult[ReferenceT]:
        with self._operation_lock:
            with self._lifecycle_lock:
                if self._closed:
                    return self._closed_failure
            if not body.strip():
                return OperationFailure(
                    self._provider,
                    OperationFailureCode.RENDERING,
                    "message body must not be blank",
                )
            context = self._context_for_operation()
            if context is None:
                return self._closed_failure
            return context.messaging.send_text(destination, body)

    def _assess_card(self, intent: CardIntent) -> CardAssessmentResult:
        def assess(context: _ProviderClientContext[DestinationT, ReferenceT]) -> CardAssessmentResult:
            if context.card is None:
                raise RuntimeError("card client is missing for a card-capable adapter")
            return context.card.assess_card(intent)

        return self._execute(assess)

    def _send_card(
        self,
        destination: DestinationT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]:
        return self._execute(
            lambda context: self._send_card_with_context(context, destination, intent, metadata),
        )

    def _update_card(
        self,
        reference: ReferenceT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]:
        return self._execute(
            lambda context: self._update_card_with_context(context, reference, intent, metadata),
        )

    @staticmethod
    def _send_card_with_context(
        context: _ProviderClientContext[DestinationT, ReferenceT],
        destination: DestinationT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]:
        if context.card is None:
            raise RuntimeError("card client is missing for a card-capable adapter")
        return context.card.send_card(destination, intent, metadata)

    @staticmethod
    def _update_card_with_context(
        context: _ProviderClientContext[DestinationT, ReferenceT],
        reference: ReferenceT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]:
        if context.card is None:
            raise RuntimeError("card client is missing for a card-capable adapter")
        return context.card.update_card(reference, intent, metadata)

    def _handle_webhook(self, request: WebhookRequest, sink: IMEventSink) -> WebhookResponse:
        with self._operation_lock:
            context = self._context_for_operation()
            if context is None:
                return self._closed_webhook_response
            webhook = context.webhook
            if webhook is None:
                raise RuntimeError("webhook client is missing for a webhook-capable adapter")
            parsed_request = webhook.parse_webhook(request)
            if isinstance(parsed_request, (WebhookChallenge, WebhookRejected)):
                return parsed_request.response
            if self._is_accepted_webhook_replay(parsed_request):
                return parsed_request.accepted_response
            response, accepted = self._deliver_webhook(parsed_request, sink)
            if accepted:
                self._remember_accepted_webhook_replay(parsed_request)
            return response

    @staticmethod
    def _deliver_webhook(delivery: WebhookDelivery, sink: IMEventSink) -> tuple[WebhookResponse, bool]:
        try:
            acceptance = sink.accept(delivery.event)
        except Exception:
            # A sink is an application-supplied boundary and may fail with an
            # implementation-specific exception. It must never turn into a
            # provider success ACK or escape as raw application state.
            logger.exception(
                "IM event sink failed during Webhook acceptance; returning retry response",
                extra={
                    "im_provider": delivery.event.provider.value,
                    "provider_tenant_id": delivery.event.provider_tenant_id,
                    "provider_event_id": delivery.event.provider_event_id,
                },
            )
            return delivery.retry_response, False
        if acceptance is EventAcceptance.ACCEPTED:
            return delivery.accepted_response, True
        return delivery.retry_response, False

    def _is_accepted_webhook_replay(self, delivery: WebhookDelivery) -> bool:
        if delivery.replay_key is None:
            return False
        received_at = delivery.event.received_at.timestamp()
        self._accepted_webhook_replays = {
            replay_key: expires_at
            for replay_key, expires_at in self._accepted_webhook_replays.items()
            if expires_at > received_at
        }
        return delivery.replay_key in self._accepted_webhook_replays

    def _remember_accepted_webhook_replay(self, delivery: WebhookDelivery) -> None:
        if delivery.replay_key is None or delivery.replay_expires_at is None:
            return
        expires_at = delivery.replay_expires_at.timestamp()
        if expires_at > delivery.event.received_at.timestamp():
            self._accepted_webhook_replays[delivery.replay_key] = expires_at

    def _run_stream(self, sink: IMEventSink, stop: StopSignal) -> StreamRunResult:
        context = self._context_for_operation()
        if context is None:
            return self._closed_failure
        if context.stream is None:
            raise RuntimeError("stream client is missing for a stream-capable adapter")

        def accept(event: AuthenticatedIMEvent) -> EventAcceptance:
            try:
                return sink.accept(event)
            except Exception:
                # The provider gateway retains the callback/ACK envelope and
                # receives only this retry decision; no handle reaches the sink.
                logger.exception(
                    "IM event sink failed during stream acceptance; requesting retry",
                    extra={
                        "im_provider": event.provider.value,
                        "provider_tenant_id": event.provider_tenant_id,
                        "provider_event_id": event.provider_event_id,
                    },
                )
                return EventAcceptance.RETRY

        return context.stream.run_stream(accept, stop)

    def close(self) -> None:
        """Permanently close operations and finish idempotent context cleanup.

        A failed cleanup raises ``AdapterCloseError`` while leaving operations
        closed. A later close retries the same context, never a new resource;
        once cleanup succeeds, subsequent calls are no-ops.
        """
        with self._operation_lock:
            with self._lifecycle_lock:
                if self._cleanup_complete:
                    return
                self._closed = True
                context = self._context
                if context is None:
                    self._cleanup_complete = True
                    return
            try:
                context.close()
            except Exception:
                logger.exception(
                    "IM provider client context cleanup failed; adapter remains operation-closed",
                    extra={"im_provider": self._provider.value},
                )
                raise AdapterCloseError(self._provider) from None
            with self._lifecycle_lock:
                self._cleanup_complete = True


class SlackAdapter(_AdapterRoot[SlackUserDestination, SlackMessageReference, SlackAdapterConfig]):
    """Slack adapter with Web API, Webhook, and Socket Mode capabilities."""

    def __init__(self, config: SlackAdapterConfig) -> None:
        super().__init__(
            IMProvider.SLACK,
            config,
            _create_slack_client_context,
            dynamic_cards=True,
            webhook_events=True,
            stream_events=True,
        )


class FeishuLarkAdapter(_AdapterRoot[FeishuUserDestination, FeishuMessageReference, FeishuLarkAdapterConfig]):
    """Feishu/Lark adapter with API, Webhook, and long-connection capabilities."""

    def __init__(self, config: FeishuLarkAdapterConfig) -> None:
        super().__init__(
            config.provider,
            config,
            _create_feishu_lark_client_context,
            dynamic_cards=True,
            webhook_events=True,
            stream_events=True,
        )


class DingTalkAdapter(_AdapterRoot[DingTalkUserDestination, DingTalkMessageReference, DingTalkAdapterConfig]):
    """DingTalk adapter with credential, Directory, and basic Messaging capabilities."""

    def __init__(self, config: DingTalkAdapterConfig) -> None:
        super().__init__(
            IMProvider.DING_TALK,
            config,
            _create_dingtalk_client_context,
            dynamic_cards=False,
            webhook_events=False,
            stream_events=False,
        )


class WeComAdapter(_AdapterRoot[WeComUserDestination, WeComMessageReference, WeComAdapterConfig]):
    """WeCom adapter with credential, Directory, and basic Messaging capabilities."""

    def __init__(self, config: WeComAdapterConfig) -> None:
        super().__init__(
            IMProvider.WE_COM,
            config,
            _create_wecom_client_context,
            dynamic_cards=False,
            webhook_events=False,
            stream_events=False,
        )


class MicrosoftTeamsAdapter(
    _AdapterRoot[TeamsPersonalConversationDestination, TeamsMessageReference, MicrosoftTeamsAdapterConfig]
):
    """Teams adapter with Directory, basic/card Messaging, and Webhook only."""

    def __init__(self, config: MicrosoftTeamsAdapterConfig) -> None:
        super().__init__(
            IMProvider.MS_TEAMS,
            config,
            _create_microsoft_teams_client_context,
            dynamic_cards=True,
            webhook_events=True,
            stream_events=False,
        )
