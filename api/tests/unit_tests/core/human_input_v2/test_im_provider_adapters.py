"""Behavior tests for immutable IM provider adapter composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import override
from unittest.mock import patch

import pytest

from core.human_input_v2 import im_provider
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AdapterCloseError,
    AuthenticatedIMEvent,
    CardAction,
    CardActionKind,
    CardAssessment,
    CardIntent,
    CredentialTestSuccess,
    DingTalkAdapter,
    DingTalkAdapterConfig,
    DingTalkMessageReference,
    DingTalkUserDestination,
    DirectoryEntry,
    DirectorySnapshot,
    EventAcceptance,
    FeishuLarkAdapter,
    FeishuLarkAdapterConfig,
    FeishuMessageReference,
    FeishuUserDestination,
    IMEventSink,
    MessageAccepted,
    MicrosoftTeamsAdapter,
    MicrosoftTeamsAdapterConfig,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
    PermissionFact,
    SlackAdapter,
    SlackAdapterConfig,
    SlackMessageReference,
    SlackUserDestination,
    TeamsMessageReference,
    TeamsPersonalConversationDestination,
    WebhookChallenge,
    WebhookDelivery,
    WebhookRejected,
    WebhookRequest,
    WebhookResponse,
    WeComAdapter,
    WeComAdapterConfig,
    WeComMessageReference,
    WeComUserDestination,
)
from core.human_input_v2.im_provider.client_roles import _ProviderClientContext

_NOW = datetime(2026, 8, 2, 8, tzinfo=UTC)
_SUCCESS_RESPONSE = WebhookResponse(status_code=200, headers=(), body=b"ok")
_RETRY_RESPONSE = WebhookResponse(status_code=503, headers=(), body=b"retry")


@dataclass
class _RecordingGateway[DestinationT, ReferenceT]:
    provider: IMProvider
    reference: ReferenceT
    credential_result: CredentialTestSuccess | OperationFailure
    directory_result: DirectorySnapshot | OperationFailure
    destination_result: OperationFailure | None = None
    send_result: OperationFailure | None = None
    webhook_result: WebhookChallenge | WebhookDelivery | WebhookRejected | None = None
    calls: list[str] = field(default_factory=list)
    closed_count: int = 0
    close_failures_remaining: int = 0
    stream_acceptances: list[EventAcceptance] = field(default_factory=list)

    def test_credentials(self) -> CredentialTestSuccess | OperationFailure:
        self.calls.append("test_credentials")
        return self.credential_result

    def read_directory(self) -> DirectorySnapshot | OperationFailure:
        self.calls.append("read_directory")
        return self.directory_result

    def test_destination(self, destination: DestinationT) -> OperationFailure | None:
        self.calls.append("test_destination")
        return self.destination_result

    def send_text(self, destination: DestinationT, body: str):
        self.calls.append("send_text")
        if self.send_result is not None:
            return self.send_result
        from core.human_input_v2.im_provider import MessageAccepted

        return MessageAccepted(reference=self.reference, provider_request_id="request-1")

    def assess_card(self, intent: CardIntent) -> CardAssessment:
        self.calls.append("assess_card")
        return CardAssessment(representable=True, reason=None)

    def send_card(self, destination: DestinationT, intent: CardIntent, metadata: OpaqueMetadata):
        self.calls.append("send_card")
        from core.human_input_v2.im_provider import MessageAccepted

        return MessageAccepted(reference=self.reference, provider_request_id="request-2")

    def update_card(self, reference: ReferenceT, intent: CardIntent, metadata: OpaqueMetadata):
        self.calls.append("update_card")
        from core.human_input_v2.im_provider import MessageAccepted

        return MessageAccepted(reference=self.reference, provider_request_id="request-3")

    def parse_webhook(self, request: WebhookRequest):
        self.calls.append("parse_webhook")
        assert self.webhook_result is not None
        return self.webhook_result

    def run_stream(
        self,
        accept: Callable[[AuthenticatedIMEvent], EventAcceptance],
        stop,
    ) -> OperationFailure | None:
        self.calls.append("run_stream")
        if not stop.is_set():
            self.stream_acceptances.append(accept(_event(self.provider)))
        return None

    def close(self) -> None:
        self.closed_count += 1
        if self.close_failures_remaining > 0:
            self.close_failures_remaining -= 1
            raise RuntimeError("provider cleanup failed")


@dataclass
class _GatewayFactory[ConfigT, DestinationT, ReferenceT]:
    gateway: _RecordingGateway[DestinationT, ReferenceT]
    calls: int = 0
    configurations: list[ConfigT] = field(default_factory=list)

    def __call__(self, config: ConfigT) -> _ProviderClientContext[DestinationT, ReferenceT]:
        self.calls += 1
        self.configurations.append(config)
        return _ProviderClientContext(
            credentials=self.gateway,
            directory=self.gateway,
            messaging=self.gateway,
            card=self.gateway,
            webhook=self.gateway,
            stream=self.gateway,
            owned_resources=(self.gateway,),
        )


@dataclass
class _Sink(IMEventSink):
    acceptance: EventAcceptance
    events: list[AuthenticatedIMEvent] = field(default_factory=list)
    error: RuntimeError | None = None

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return self.acceptance


@dataclass
class _Stop:
    stopped: bool = False

    def is_set(self) -> bool:
        return self.stopped


@dataclass
class _CloseRecorder:
    failures_remaining: int = 0
    calls: int = 0

    def close(self) -> None:
        self.calls += 1
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise RuntimeError("client cleanup failed")


def _credential_success(provider: IMProvider) -> CredentialTestSuccess:
    return CredentialTestSuccess(
        provider=provider,
        provider_tenant_id=f"{provider.value}-tenant",
        permissions=(PermissionFact(name="directory.read", granted=True),),
    )


def _directory(provider: IMProvider) -> DirectorySnapshot:
    return DirectorySnapshot(
        provider=provider,
        provider_tenant_id=f"{provider.value}-tenant",
        entries=(
            DirectoryEntry(provider_user_id="user-1", display_name="Ada", email="ada@example.com", available=True),
            DirectoryEntry(provider_user_id="user-2", display_name="Lin", email=None, available=False),
        ),
    )


def _event(provider: IMProvider, *, event_id: str | None = "event-1") -> AuthenticatedIMEvent:
    return AuthenticatedIMEvent(
        provider=provider,
        provider_tenant_id=f"{provider.value}-tenant",
        provider_event_id=event_id,
        provider_event_time=None,
        received_at=_NOW,
        provider_event_type="message.created",
        provider_payload=(("type", "message.created"), ("sequence", 1)),
    )


def _request() -> WebhookRequest:
    return WebhookRequest(
        method="POST", headers=(("content-type", "application/json"),), query=(), body=b"{}", received_at=_NOW
    )


def _card() -> CardIntent:
    return CardIntent(
        title="Approval",
        body="Please **review** the request.",
        facts=(("Environment", "Staging"),),
        actions=(CardAction(action_id="approve", label="Approve", kind=CardActionKind.SUBMIT, value="approved"),),
        fallback_text="Please review the request.",
    )


def _slack_adapter():
    gateway = _RecordingGateway[SlackUserDestination, SlackMessageReference](
        provider=IMProvider.SLACK,
        reference=SlackMessageReference(channel_id="C1", message_timestamp="1000.1"),
        credential_result=_credential_success(IMProvider.SLACK),
        directory_result=_directory(IMProvider.SLACK),
    )
    factory = _GatewayFactory(gateway)
    with patch("core.human_input_v2.im_provider.adapters._create_slack_client_context", new=factory):
        adapter = SlackAdapter(
            SlackAdapterConfig(bot_token="xoxb-test", signing_secret="signing-test", app_token="xapp-test")
        )
    return adapter, gateway, factory


def _feishu_adapter():
    gateway = _RecordingGateway[FeishuUserDestination, FeishuMessageReference](
        provider=IMProvider.FEISHU,
        reference=FeishuMessageReference(message_id="om_1"),
        credential_result=_credential_success(IMProvider.FEISHU),
        directory_result=_directory(IMProvider.FEISHU),
    )
    factory = _GatewayFactory(gateway)
    with patch("core.human_input_v2.im_provider.adapters._create_feishu_lark_client_context", new=factory):
        adapter = FeishuLarkAdapter(
            FeishuLarkAdapterConfig(
                provider=IMProvider.FEISHU,
                app_id="cli_test",
                app_secret="secret-test",
                verification_token="verification-test",
                encrypt_key="encrypt-test",
            )
        )
    return adapter, gateway, factory


def _dingtalk_adapter():
    gateway = _RecordingGateway[DingTalkUserDestination, DingTalkMessageReference](
        provider=IMProvider.DING_TALK,
        reference=DingTalkMessageReference(user_id="user-1", message_id="msg-1"),
        credential_result=_credential_success(IMProvider.DING_TALK),
        directory_result=_directory(IMProvider.DING_TALK),
    )
    factory = _GatewayFactory(gateway)
    with patch("core.human_input_v2.im_provider.adapters._create_dingtalk_client_context", new=factory):
        adapter = DingTalkAdapter(
            DingTalkAdapterConfig(
                corp_id="ding-tenant-test",
                client_id="client-test",
                client_secret="secret-test",
            )
        )
    return adapter, gateway, factory


def _wecom_adapter():
    gateway = _RecordingGateway[WeComUserDestination, WeComMessageReference](
        provider=IMProvider.WE_COM,
        reference=WeComMessageReference(message_id="msg-1"),
        credential_result=_credential_success(IMProvider.WE_COM),
        directory_result=_directory(IMProvider.WE_COM),
    )
    factory = _GatewayFactory(gateway)
    with patch("core.human_input_v2.im_provider.adapters._create_wecom_client_context", new=factory):
        adapter = WeComAdapter(
            WeComAdapterConfig(
                corp_id="corp-test",
                agent_id="agent-test",
                corp_secret="secret-test",
            )
        )
    return adapter, gateway, factory


def _teams_adapter():
    gateway = _RecordingGateway[TeamsPersonalConversationDestination, TeamsMessageReference](
        provider=IMProvider.MS_TEAMS,
        reference=TeamsMessageReference(
            service_url="https://smba.example",
            conversation_id="conv-1",
            user_id="user-1",
            activity_id="activity-1",
        ),
        credential_result=_credential_success(IMProvider.MS_TEAMS),
        directory_result=_directory(IMProvider.MS_TEAMS),
    )
    factory = _GatewayFactory(gateway)
    with patch("core.human_input_v2.im_provider.adapters._create_microsoft_teams_client_context", factory):
        adapter = MicrosoftTeamsAdapter(
            MicrosoftTeamsAdapterConfig(
                tenant_id="tenant-test",
                client_id="client-test",
                client_secret="secret-test",
                bot_app_id="bot-test",
            )
        )
    return adapter, gateway, factory


def test_provider_client_gateway_is_not_part_of_the_public_contract() -> None:
    assert not hasattr(im_provider, "ProviderClientGateway")


def test_slack_adapter_constructs_without_a_caller_supplied_client_context() -> None:
    adapter = SlackAdapter(
        SlackAdapterConfig(bot_token="xoxb-test", signing_secret="signing-test", app_token="xapp-test")
    )

    adapter.close()


def test_dingtalk_adapter_constructs_without_a_caller_supplied_client_context() -> None:
    adapter = DingTalkAdapter(
        DingTalkAdapterConfig(
            corp_id="ding-tenant-test",
            client_id="client-test",
            client_secret="secret-test",
        )
    )

    assert adapter.dynamic_card_messaging is None
    assert adapter.webhook_events is None
    assert adapter.stream_events is None
    adapter.close()


def test_feishu_lark_adapter_constructs_without_a_caller_supplied_client_context() -> None:
    adapter = FeishuLarkAdapter(
        FeishuLarkAdapterConfig(
            provider=IMProvider.LARK,
            app_id="cli_test",
            app_secret="secret-test",
            verification_token="verification-test",
            encrypt_key=None,
        )
    )

    assert adapter.stream_events is not None
    adapter.close()


@pytest.mark.parametrize(
    ("build_adapter", "has_card", "has_webhook", "has_stream"),
    [
        (_slack_adapter, True, True, True),
        (_feishu_adapter, True, True, True),
        (_dingtalk_adapter, False, False, False),
        (_wecom_adapter, False, False, False),
        (_teams_adapter, True, True, False),
    ],
    ids=("slack", "feishu_lark", "dingtalk", "wecom", "microsoft_teams"),
)
def test_concrete_adapter_capabilities_are_stable_and_side_effect_free(
    build_adapter, has_card: bool, has_webhook: bool, has_stream: bool
) -> None:
    adapter, _, factory = build_adapter()

    assert adapter.directory is adapter.directory
    assert adapter.messaging is adapter.messaging
    assert (adapter.dynamic_card_messaging is not None) is has_card
    assert (adapter.webhook_events is not None) is has_webhook
    assert adapter.webhook_events is adapter.webhook_events
    assert (adapter.stream_events is not None) is has_stream
    assert factory.calls == 0


@pytest.mark.parametrize(
    "build_adapter",
    [_slack_adapter, _feishu_adapter, _dingtalk_adapter, _wecom_adapter, _teams_adapter],
    ids=("slack", "feishu_lark", "dingtalk", "wecom", "microsoft_teams"),
)
def test_concrete_adapter_credential_test_uses_one_bound_gateway(build_adapter) -> None:
    adapter, gateway, factory = build_adapter()

    credential_result = adapter.test_credentials()
    directory_result = adapter.directory.read_snapshot()

    assert credential_result == gateway.credential_result
    assert directory_result == gateway.directory_result
    assert factory.calls == 1
    assert len(factory.configurations) == 1
    assert not hasattr(adapter, "config")
    assert gateway.calls == ["test_credentials", "read_directory"]


@pytest.mark.parametrize(
    "failure_code",
    [
        OperationFailureCode.AUTHENTICATION,
        OperationFailureCode.TENANT_IDENTIFICATION,
        OperationFailureCode.MISSING_PERMISSION,
    ],
)
def test_slack_credential_failures_remain_typed_and_safe(failure_code: OperationFailureCode) -> None:
    adapter, gateway, _ = _slack_adapter()
    gateway.credential_result = OperationFailure(IMProvider.SLACK, failure_code, "safe failure")

    assert adapter.test_credentials() == OperationFailure(IMProvider.SLACK, failure_code, "safe failure")
    assert "xoxb-test" not in repr(adapter.test_credentials())


@pytest.mark.parametrize(
    "build_adapter",
    [_feishu_adapter, _dingtalk_adapter, _wecom_adapter, _teams_adapter],
    ids=("feishu_lark", "dingtalk", "wecom", "microsoft_teams"),
)
def test_other_provider_credential_failures_remain_typed(build_adapter) -> None:
    adapter, gateway, _ = build_adapter()
    gateway.credential_result = OperationFailure(gateway.provider, OperationFailureCode.AUTHENTICATION, "safe failure")

    assert adapter.test_credentials() == gateway.credential_result


def test_directory_snapshot_is_immutable_and_late_failure_has_no_partial_value() -> None:
    adapter, gateway, _ = _slack_adapter()

    snapshot = adapter.directory.read_snapshot()
    assert snapshot == _directory(IMProvider.SLACK)
    assert isinstance(snapshot, DirectorySnapshot)
    assert snapshot.entries[1].email is None
    entries_field = "entries"
    with pytest.raises((AttributeError, TypeError)):
        setattr(snapshot, entries_field, snapshot.entries + (DirectoryEntry("user-3", "Grace", None, True),))

    gateway.directory_result = OperationFailure(
        IMProvider.SLACK, OperationFailureCode.DIRECTORY_INCOMPLETE, "page 2 failed"
    )
    assert adapter.directory.read_snapshot() == gateway.directory_result


def test_messaging_keeps_destination_and_exact_reference_provider_specific() -> None:
    adapter, gateway, _ = _slack_adapter()
    destination = SlackUserDestination(user_id="U1")

    destination_result = adapter.messaging.test_destination(destination)
    send_result = adapter.messaging.send_text(destination, "Hello **team**")
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None
    card_result = card_messaging.send_card(
        destination,
        _card(),
        OpaqueMetadata(entries=(("form_id", "form-1"),)),
    )
    update_result = card_messaging.update_card(gateway.reference, _card(), OpaqueMetadata(entries=()))

    assert destination_result is None
    assert isinstance(send_result, MessageAccepted)
    assert isinstance(card_result, MessageAccepted)
    assert isinstance(update_result, MessageAccepted)
    assert send_result.reference == SlackMessageReference(channel_id="C1", message_timestamp="1000.1")
    assert card_result.reference == gateway.reference
    assert update_result.reference == gateway.reference
    assert gateway.calls == ["test_destination", "send_text", "send_card", "update_card"]


def test_messaging_does_not_replay_ambiguous_outcome() -> None:
    adapter, gateway, _ = _teams_adapter()
    gateway.send_result = OperationFailure(IMProvider.MS_TEAMS, OperationFailureCode.AMBIGUOUS, "request timed out")
    destination = TeamsPersonalConversationDestination(
        service_url="https://smba.example",
        conversation_id="conv-1",
        user_id="user-1",
    )

    send_result = adapter.messaging.send_text(destination, "Hello")

    assert send_result == gateway.send_result
    assert gateway.calls == ["send_text"]


def test_card_assessment_is_side_effect_free_at_the_provider_boundary() -> None:
    adapter, gateway, factory = _feishu_adapter()
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    assessment = card_messaging.assess(_card())

    assert assessment == CardAssessment(representable=True, reason=None)
    assert gateway.calls == ["assess_card"]
    assert factory.calls == 1


def test_webhook_challenge_and_rejection_do_not_call_sink() -> None:
    adapter, gateway, _ = _feishu_adapter()
    sink = _Sink(EventAcceptance.ACCEPTED)
    challenge_response = WebhookResponse(status_code=200, headers=(), body=b"challenge")
    gateway.webhook_result = WebhookChallenge(challenge_response)

    challenge_result = adapter.webhook_events.handle(_request(), sink)
    assert challenge_result == challenge_response
    assert sink.events == []

    rejection_response = WebhookResponse(status_code=401, headers=(), body=b"invalid")
    gateway.webhook_result = WebhookRejected(rejection_response)
    rejection_result = adapter.webhook_events.handle(_request(), sink)
    assert rejection_result == rejection_response
    assert sink.events == []


@pytest.mark.parametrize(
    ("acceptance", "expected_response"),
    [(EventAcceptance.ACCEPTED, _SUCCESS_RESPONSE), (EventAcceptance.RETRY, _RETRY_RESPONSE)],
)
def test_webhook_calls_sink_once_and_maps_acceptance(
    acceptance: EventAcceptance, expected_response: WebhookResponse
) -> None:
    adapter, gateway, _ = _slack_adapter()
    event = _event(IMProvider.SLACK)
    gateway.webhook_result = WebhookDelivery(
        event=event, accepted_response=_SUCCESS_RESPONSE, retry_response=_RETRY_RESPONSE
    )
    sink = _Sink(acceptance)

    result = adapter.webhook_events.handle(_request(), sink)

    assert result == expected_response
    assert sink.events == [event]


def test_webhook_maps_unexpected_sink_failure_to_retry_response() -> None:
    adapter, gateway, _ = _teams_adapter()
    event = _event(IMProvider.MS_TEAMS, event_id=None)
    gateway.webhook_result = WebhookDelivery(
        event=event, accepted_response=_SUCCESS_RESPONSE, retry_response=_RETRY_RESPONSE
    )
    sink = _Sink(EventAcceptance.ACCEPTED, error=RuntimeError("storage unavailable"))

    result = adapter.webhook_events.handle(_request(), sink)

    assert result == _RETRY_RESPONSE
    assert sink.events == [event]
    assert event.provider_event_id is None


def test_stream_keeps_ack_mapping_inside_gateway_callback() -> None:
    adapter, gateway, _ = _slack_adapter()
    sink = _Sink(EventAcceptance.RETRY)
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(sink, _Stop())

    assert result is None
    assert gateway.stream_acceptances == [EventAcceptance.RETRY]
    assert sink.events == [_event(gateway.provider)]


def test_stream_honors_preexisting_stop_without_delivering_event() -> None:
    adapter, gateway, _ = _slack_adapter()
    sink = _Sink(EventAcceptance.ACCEPTED)
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(sink, _Stop(stopped=True))

    assert result is None
    assert sink.events == []
    assert gateway.stream_acceptances == []


@pytest.mark.parametrize(
    "build_adapter",
    [_slack_adapter, _feishu_adapter, _dingtalk_adapter, _wecom_adapter, _teams_adapter],
    ids=("slack", "feishu_lark", "dingtalk", "wecom", "microsoft_teams"),
)
def test_close_is_idempotent_and_post_close_calls_do_not_recreate_gateway(build_adapter) -> None:
    adapter, gateway, factory = build_adapter()
    adapter.test_credentials()

    adapter.close()
    adapter.close()
    credential_result = adapter.test_credentials()
    directory_result = adapter.directory.read_snapshot()
    message_result = adapter.messaging.send_text(SlackUserDestination("U1"), "after close")
    webhook_events = adapter.webhook_events
    webhook_result = (
        webhook_events.handle(_request(), _Sink(EventAcceptance.ACCEPTED)) if webhook_events is not None else None
    )
    stream_events = adapter.stream_events
    stream_result = stream_events.run(_Sink(EventAcceptance.ACCEPTED), _Stop()) if stream_events is not None else None

    assert gateway.closed_count == 1
    assert factory.calls == 1
    assert isinstance(credential_result, OperationFailure)
    assert isinstance(directory_result, OperationFailure)
    assert isinstance(message_result, OperationFailure)
    if stream_events is not None:
        assert isinstance(stream_result, OperationFailure)
        assert stream_result.code is OperationFailureCode.CLOSED
    assert credential_result.code is OperationFailureCode.CLOSED
    assert directory_result.code is OperationFailureCode.CLOSED
    assert message_result.code is OperationFailureCode.CLOSED
    if webhook_events is not None:
        assert webhook_result == WebhookResponse(
            status_code=503,
            headers=(("content-type", "text/plain; charset=utf-8"),),
            body=b"adapter is closed",
        )
    assert gateway.calls == ["test_credentials"]


def test_close_before_first_use_never_constructs_gateway() -> None:
    adapter, _, factory = _wecom_adapter()

    adapter.close()
    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.CLOSED
    assert factory.calls == 0


def test_send_text_prioritizes_closed_state_while_open_blank_input_stays_local() -> None:
    open_adapter, open_gateway, open_factory = _slack_adapter()

    open_result = open_adapter.messaging.send_text(SlackUserDestination("U1"), "  ")

    assert isinstance(open_result, OperationFailure)
    assert open_result.code is OperationFailureCode.RENDERING
    assert open_gateway.calls == []
    assert open_factory.calls == 0
    open_adapter.close()

    closed_adapter, closed_gateway, closed_factory = _slack_adapter()
    closed_adapter.close()

    closed_result = closed_adapter.messaging.send_text(SlackUserDestination("U1"), "  ")

    assert isinstance(closed_result, OperationFailure)
    assert closed_result.code is OperationFailureCode.CLOSED
    assert closed_gateway.calls == []
    assert closed_factory.calls == 0


def test_close_failure_keeps_operations_closed_and_retries_same_gateway_cleanup() -> None:
    adapter, gateway, factory = _slack_adapter()
    adapter.test_credentials()
    gateway.close_failures_remaining = 1

    with pytest.raises(AdapterCloseError, match="Slack"):
        adapter.close()

    credential_result = adapter.test_credentials()
    assert isinstance(credential_result, OperationFailure)
    assert credential_result.code is OperationFailureCode.CLOSED
    assert factory.calls == 1

    adapter.close()
    adapter.close()

    assert gateway.closed_count == 2
    assert factory.calls == 1


def test_client_context_close_is_best_effort_idempotent_and_retries_only_failed_resources() -> None:
    gateway = _RecordingGateway[SlackUserDestination, SlackMessageReference](
        provider=IMProvider.SLACK,
        reference=SlackMessageReference(channel_id="C1", message_timestamp="1000.1"),
        credential_result=_credential_success(IMProvider.SLACK),
        directory_result=_directory(IMProvider.SLACK),
    )
    failing_client = _CloseRecorder(failures_remaining=1)
    healthy_client = _CloseRecorder()
    context = _ProviderClientContext(
        credentials=gateway,
        directory=gateway,
        messaging=gateway,
        card=gateway,
        webhook=gateway,
        stream=gateway,
        owned_resources=(failing_client, healthy_client),
    )

    with pytest.raises(RuntimeError, match="cleanup"):
        context.close()

    assert failing_client.calls == 1
    assert healthy_client.calls == 1

    context.close()
    context.close()

    assert failing_client.calls == 2
    assert healthy_client.calls == 1


def test_provider_configurations_are_frozen_and_hide_secrets() -> None:
    config = SlackAdapterConfig(
        bot_token="xoxb-sensitive", signing_secret="signing-sensitive", app_token="xapp-sensitive"
    )

    bot_token_field = "bot_token"
    with pytest.raises((AttributeError, TypeError)):
        setattr(config, bot_token_field, "replacement")
    assert "sensitive" not in repr(config)


@pytest.mark.parametrize(
    "build_config",
    [
        lambda: SlackAdapterConfig(bot_token=" ", signing_secret="secret", app_token="app"),
        lambda: FeishuLarkAdapterConfig(IMProvider.FEISHU, "app", " ", "verify", None),
        lambda: DingTalkAdapterConfig("ding-tenant", "client", " "),
        lambda: WeComAdapterConfig("corp", "agent", " "),
        lambda: MicrosoftTeamsAdapterConfig("tenant", "client", " ", "bot"),
    ],
)
def test_provider_configurations_reject_blank_required_fields(build_config) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        build_config()


@pytest.mark.parametrize(
    "build_config",
    [
        lambda page_size: SlackAdapterConfig("bot", "signing", "app", page_size),
        lambda page_size: FeishuLarkAdapterConfig(IMProvider.FEISHU, "app", "secret", "verify", None, page_size),
        lambda page_size: DingTalkAdapterConfig("corp", "client", "secret", page_size),
        lambda page_size: MicrosoftTeamsAdapterConfig("tenant", "client", "secret", "bot", (), page_size),
    ],
    ids=("slack", "feishu_lark", "dingtalk", "microsoft_teams"),
)
@pytest.mark.parametrize(
    ("page_size", "expected_exception"),
    [
        pytest.param(0, ValueError, id="zero"),
        pytest.param(-1, ValueError, id="negative"),
        pytest.param(True, TypeError, id="boolean"),
        pytest.param("1", TypeError, id="non_integer"),
    ],
)
def test_paginated_provider_configurations_require_a_positive_integer_directory_page_size(
    build_config,
    page_size: object,
    expected_exception: type[Exception],
) -> None:
    with pytest.raises(expected_exception, match="directory page size"):
        build_config(page_size)
