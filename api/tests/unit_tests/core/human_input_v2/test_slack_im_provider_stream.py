"""Slack Socket Mode public capability and construction contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC
from threading import Event, Thread
from typing import cast, override
from urllib.parse import urlsplit
from urllib.request import Request

import pytest
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

import core.human_input_v2.im_provider.providers.slack as slack_provider
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AdapterCloseError,
    AuthenticatedIMEvent,
    EventAcceptance,
    IMEventSink,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
    SlackAdapter,
    SlackAdapterConfig,
    thaw_json_value,
)


def _config() -> SlackAdapterConfig:
    return SlackAdapterConfig(
        bot_token="xoxb-test",
        signing_secret="signing-test",
        app_token="xapp-test",
    )


def _submit_action_value() -> str:
    return slack_provider._encode_submit_action_value("approved", OpaqueMetadata(entries=()))


@dataclass(slots=True)
class _RejectUnexpectedEventSink(IMEventSink):
    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        raise AssertionError("pre-lifecycle STREAM test must not deliver an event")


@dataclass(slots=True)
class _SequencedSink(IMEventSink):
    decisions: list[EventAcceptance | RuntimeError]
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        decision = self.decisions[len(self.events)]
        self.events.append(event)
        if isinstance(decision, RuntimeError):
            raise decision
        return decision


@dataclass(slots=True)
class _SessionRunner:
    event: Event = field(default_factory=Event)
    thread: Thread | None = None


class _SocketModeSDKClient:
    socket_mode_request_listeners: list[Callable[[object, SocketModeRequest], None]]
    requests: tuple[SocketModeRequest, ...]
    responses: list[SocketModeResponse]
    connect_calls: int
    close_calls: int
    connected: Event
    current_session_runner: _SessionRunner
    _stop: Event | None
    _connect_error: RuntimeError | None
    _close_failures_remaining: int

    def __init__(
        self,
        requests: tuple[SocketModeRequest, ...] = (),
        *,
        stop: Event | None = None,
        connect_error: RuntimeError | None = None,
        close_failures_remaining: int = 0,
    ) -> None:
        self.socket_mode_request_listeners = []
        self.requests = requests
        self.responses = []
        self.connect_calls = 0
        self.close_calls = 0
        self.connected = Event()
        self.current_session_runner = _SessionRunner()
        self._stop = stop
        self._connect_error = connect_error
        self._close_failures_remaining = close_failures_remaining

    def connect(self) -> None:
        self.connect_calls += 1
        self.connected.set()
        if self._connect_error is not None:
            raise self._connect_error
        assert len(self.socket_mode_request_listeners) == 1
        listener = self.socket_mode_request_listeners[0]
        for request in self.requests:
            listener(self, request)
        if self._stop is not None:
            self._stop.set()

    def send_socket_mode_response(self, response: SocketModeResponse) -> None:
        self.responses.append(response)

    def close(self) -> None:
        self.close_calls += 1
        if self._close_failures_remaining > 0:
            self._close_failures_remaining -= 1
            raise RuntimeError("raw SDK close failure")


class _BlockingListenerRegistry:
    def __init__(self) -> None:
        self.registration_started = Event()
        self.registration_release = Event()
        self.listeners: list[Callable[[object, SocketModeRequest], None]] = []

    def append(self, listener: Callable[[object, SocketModeRequest], None], /) -> None:
        self.registration_started.set()
        assert self.registration_release.wait(timeout=2)
        self.listeners.append(listener)


class _FailingListenerRegistry:
    def append(self, listener: Callable[[object, SocketModeRequest], None], /) -> None:
        del listener
        raise RuntimeError("listener registration failed")


def _events_api_request(
    envelope_number: int,
    *,
    event_id: str | None = "Ev-integration",
) -> SocketModeRequest:
    payload: dict[str, object] = {
        "type": "event_callback",
        "team_id": "T-integration",
        "api_app_id": "A-integration",
        "event_time": 1_785_600_123,
        "event": {
            "type": "message",
            "user": f"U-{envelope_number}",
            "text": "Hello",
            "attributes": {"active": True},
            "roles": ["admin", "reviewer"],
        },
    }
    if event_id is not None:
        payload["event_id"] = event_id
    return SocketModeRequest(
        type="events_api",
        envelope_id=f"envelope-{envelope_number}",
        payload=payload,
    )


def _slash_commands_request(
    envelope_id: str,
    *,
    team_id: str | None = "T-slash",
) -> SocketModeRequest:
    payload: dict[str, object] = {
        "team_domain": "test-workspace",
        "channel_id": "C-test",
        "user_id": "U-test",
        "command": "/approve",
        "text": "request-1",
    }
    if team_id is not None:
        payload = {"team_id": team_id, **payload}
    return SocketModeRequest(
        type="slash_commands",
        envelope_id=envelope_id,
        payload=payload,
    )


def _interactive_request(
    envelope_id: str,
    *,
    team_id: str | None = "T-interactive",
) -> SocketModeRequest:
    payload: dict[str, object] = {
        "type": "block_actions",
        "user": {"id": "U-test"},
        "actions": [{"type": "button", "action_id": "approve", "value": _submit_action_value()}],
    }
    if team_id is not None:
        payload = {"type": "block_actions", "team": {"id": team_id, "domain": "test-workspace"}, **payload}
    return SocketModeRequest(
        type="interactive",
        envelope_id=envelope_id,
        payload=payload,
    )


def _install_sdk_client(
    monkeypatch: pytest.MonkeyPatch,
    sdk_client: _SocketModeSDKClient,
) -> list[SlackAdapterConfig]:
    configurations: list[SlackAdapterConfig] = []

    def build(config: SlackAdapterConfig) -> _SocketModeSDKClient:
        configurations.append(config)
        return sdk_client

    monkeypatch.setattr(slack_provider, "_build_slack_stream_sdk_client", build)
    return configurations


def _run_in_thread(
    operation: Callable[[], OperationFailure | None],
) -> tuple[Thread, list[OperationFailure | None]]:
    results: list[OperationFailure | None] = []
    thread = Thread(target=lambda: results.append(operation()), daemon=True)
    thread.start()
    return thread, results


def _close_in_thread(adapter: SlackAdapter) -> tuple[Thread, Event, list[AdapterCloseError], list[None]]:
    finished = Event()
    errors: list[AdapterCloseError] = []
    returns: list[None] = []

    def close() -> None:
        try:
            returns.append(adapter.close())
        except AdapterCloseError as error:
            errors.append(error)
        finally:
            finished.set()

    thread = Thread(target=close, daemon=True)
    thread.start()
    return thread, finished, errors, returns


def test_slack_public_adapter_exposes_socket_mode_and_preexisting_stop_skips_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configurations: list[SlackAdapterConfig] = []

    def build_stream_sdk_client(config: SlackAdapterConfig) -> object:
        configurations.append(config)
        return object()

    monkeypatch.setattr(
        slack_provider,
        "_build_slack_stream_sdk_client",
        build_stream_sdk_client,
        raising=False,
    )
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    stop.set()

    result = stream_events.run(_RejectUnexpectedEventSink(), stop)

    assert result is None
    assert configurations == []
    adapter.close()


def test_slack_socket_mode_constructs_sdk_role_from_bound_config_and_types_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configurations: list[SlackAdapterConfig] = []

    def build_stream_sdk_client(config: SlackAdapterConfig) -> object:
        configurations.append(config)
        raise RuntimeError("Socket Mode construction failed")

    monkeypatch.setattr(
        slack_provider,
        "_build_slack_stream_sdk_client",
        build_stream_sdk_client,
        raising=False,
    )
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(_RejectUnexpectedEventSink(), Event())

    assert configurations == [_config()]
    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER
    adapter.close()


def test_slack_close_during_blocked_stream_build_is_retryable_without_deadlock_or_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_started = Event()
    build_release = Event()
    sdk_client = _SocketModeSDKClient()
    build_count = 0

    def build_stream_sdk_client(config: SlackAdapterConfig) -> _SocketModeSDKClient:
        nonlocal build_count
        assert config == _config()
        build_count += 1
        build_started.set()
        assert build_release.wait(timeout=2)
        return sdk_client

    monkeypatch.setattr(slack_provider, "_build_slack_stream_sdk_client", build_stream_sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    run_thread, results = _run_in_thread(lambda: stream_events.run(_RejectUnexpectedEventSink(), Event()))
    assert build_started.wait(timeout=2)
    close_thread, close_finished, close_errors, close_returns = _close_in_thread(adapter)

    try:
        close_finished_before_release = close_finished.wait(timeout=2)
    finally:
        build_release.set()
    close_thread.join(timeout=2)
    run_thread.join(timeout=2)

    assert close_finished_before_release
    assert not close_thread.is_alive()
    assert not run_thread.is_alive()
    assert len(close_errors) == 1
    assert close_errors[0].provider is IMProvider.SLACK
    assert close_returns == []
    assert results == [OperationFailure(IMProvider.SLACK, OperationFailureCode.CLOSED, "Slack STREAM client is closed")]
    assert build_count == 1
    assert sdk_client.close_calls == 1

    rerun = stream_events.run(_RejectUnexpectedEventSink(), Event())
    assert isinstance(rerun, OperationFailure)
    assert rerun.code is OperationFailureCode.CLOSED
    assert build_count == 1
    adapter.close()


def test_slack_close_during_blocked_listener_registration_is_retryable_without_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener_registry = _BlockingListenerRegistry()
    sdk_client = _SocketModeSDKClient()
    sdk_client.socket_mode_request_listeners = listener_registry  # type: ignore[assignment]
    configurations = _install_sdk_client(monkeypatch, sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    run_thread, results = _run_in_thread(lambda: stream_events.run(_RejectUnexpectedEventSink(), Event()))
    assert listener_registry.registration_started.wait(timeout=2)
    close_thread, close_finished, close_errors, close_returns = _close_in_thread(adapter)

    try:
        close_finished_before_release = close_finished.wait(timeout=2)
    finally:
        listener_registry.registration_release.set()
    close_thread.join(timeout=2)
    run_thread.join(timeout=2)

    assert close_finished_before_release
    assert not close_thread.is_alive()
    assert not run_thread.is_alive()
    assert len(close_errors) == 1
    assert close_errors[0].provider is IMProvider.SLACK
    assert close_returns == []
    assert len(results) == 1
    assert configurations == [_config()]
    assert sdk_client.close_calls >= 1
    adapter.close()


def test_slack_listener_registration_failure_retains_exact_client_until_cleanup_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _SocketModeSDKClient(close_failures_remaining=1)
    sdk_client.socket_mode_request_listeners = _FailingListenerRegistry()  # type: ignore[assignment]
    configurations = _install_sdk_client(monkeypatch, sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    first_result = stream_events.run(_RejectUnexpectedEventSink(), Event())
    second_result = stream_events.run(_RejectUnexpectedEventSink(), Event())

    assert isinstance(first_result, OperationFailure)
    assert first_result.code is OperationFailureCode.PROVIDER
    assert isinstance(second_result, OperationFailure)
    assert second_result.code is OperationFailureCode.PROVIDER
    assert configurations == [_config()]
    assert sdk_client.connect_calls == 0
    assert sdk_client.close_calls == 1

    adapter.close()
    assert sdk_client.close_calls == 2


def test_slack_socket_mode_post_close_is_closed_without_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configurations: list[SlackAdapterConfig] = []
    monkeypatch.setattr(
        slack_provider,
        "_build_slack_stream_sdk_client",
        lambda config: configurations.append(config),
        raising=False,
    )
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    adapter.close()

    result = stream_events.run(_RejectUnexpectedEventSink(), Event())

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.CLOSED
    assert configurations == []


def test_slack_socket_mode_keeps_out_of_scope_events_api_frames_out_of_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = Event()
    sdk_client = _SocketModeSDKClient(
        (
            _events_api_request(1, event_id="Ev-accepted"),
            _events_api_request(2, event_id=None),
        ),
        stop=stop,
    )
    configurations = _install_sdk_client(monkeypatch, sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(_RejectUnexpectedEventSink(), stop)

    assert result is None
    assert configurations == [_config()]
    assert sdk_client.connect_calls == 1
    assert sdk_client.close_calls == 1
    assert len(sdk_client.socket_mode_request_listeners) == 1
    assert sdk_client.responses == []
    adapter.close()


def test_slack_socket_mode_routes_only_interactive_block_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = Event()
    sdk_client = _SocketModeSDKClient(
        (
            _slash_commands_request("slash-envelope"),
            _interactive_request("interactive-envelope"),
        ),
        stop=stop,
    )
    _install_sdk_client(monkeypatch, sdk_client)
    sink = _SequencedSink([EventAcceptance.ACCEPTED])
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(sink, stop)

    assert result is None
    assert len(sink.events) == 1
    assert [response.envelope_id for response in sdk_client.responses] == ["interactive-envelope"]
    assert all(response.payload is None for response in sdk_client.responses)
    interactive_event = sink.events[0]
    assert interactive_event.provider is IMProvider.SLACK
    assert interactive_event.provider_tenant_id == "T-interactive"
    assert interactive_event.provider_event_id is None
    assert interactive_event.provider_event_time is None
    assert interactive_event.received_at.tzinfo is UTC
    assert interactive_event.provider_event_type == "block_actions"
    assert thaw_json_value(interactive_event.provider_payload) == {
        "type": "block_actions",
        "team": {"id": "T-interactive", "domain": "test-workspace"},
        "user": {"id": "U-test"},
        "actions": [{"type": "button", "action_id": "approve", "value": _submit_action_value()}],
    }
    adapter.close()


def test_slack_socket_mode_withholds_business_ack_for_retry_and_sink_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = Event()
    sdk_client = _SocketModeSDKClient(
        (
            _interactive_request("interactive-retry-envelope"),
            _interactive_request("interactive-exception-envelope"),
        ),
        stop=stop,
    )
    _install_sdk_client(monkeypatch, sdk_client)
    sink = _SequencedSink([EventAcceptance.RETRY, RuntimeError("sink failed")])
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(sink, stop)

    assert result is None
    assert len(sink.events) == 2
    assert sdk_client.responses == []
    adapter.close()


def test_slack_socket_mode_rejects_business_deliveries_without_nonblank_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = Event()
    sdk_client = _SocketModeSDKClient(
        (
            _slash_commands_request("slash-missing-tenant", team_id=None),
            _slash_commands_request("slash-blank-tenant", team_id=" "),
            _interactive_request("interactive-missing-tenant", team_id=None),
            _interactive_request("interactive-blank-tenant", team_id=" "),
        ),
        stop=stop,
    )
    _install_sdk_client(monkeypatch, sdk_client)
    sink = _SequencedSink(
        [
            EventAcceptance.ACCEPTED,
            EventAcceptance.ACCEPTED,
            EventAcceptance.ACCEPTED,
            EventAcceptance.ACCEPTED,
        ]
    )
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(sink, stop)

    assert result is None
    assert sink.events == []
    assert sdk_client.responses == []
    adapter.close()


def test_slack_socket_mode_keeps_hello_and_disconnect_control_frames_out_of_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = Event()
    sdk_client = _SocketModeSDKClient(
        (
            SocketModeRequest("hello", "hello-envelope", {}),
            SocketModeRequest("disconnect", "disconnect-envelope", {"reason": "warning"}),
        ),
        stop=stop,
    )
    _install_sdk_client(monkeypatch, sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(_RejectUnexpectedEventSink(), stop)

    assert result is None
    assert sdk_client.responses == []
    adapter.close()


def test_slack_socket_mode_connect_failure_is_typed_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _SocketModeSDKClient(connect_error=RuntimeError("connect failed"))
    _install_sdk_client(monkeypatch, sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(_RejectUnexpectedEventSink(), Event())

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER
    assert sdk_client.connect_calls == 1
    assert sdk_client.close_calls == 1
    adapter.close()


def test_slack_socket_mode_close_failure_returns_typed_provider_failure_without_raw_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = Event()
    sdk_client = _SocketModeSDKClient(stop=stop, close_failures_remaining=1)
    _install_sdk_client(monkeypatch, sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(_RejectUnexpectedEventSink(), stop)

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER
    assert "raw SDK close failure" not in repr(result)
    assert sdk_client.close_calls == 1

    adapter.close()
    assert sdk_client.close_calls == 2


def test_slack_socket_mode_cleanup_incomplete_blocks_second_run_without_rebuilding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_stop = Event()
    sdk_client = _SocketModeSDKClient(stop=first_stop, close_failures_remaining=1)
    configurations = _install_sdk_client(monkeypatch, sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    first_result = stream_events.run(_RejectUnexpectedEventSink(), first_stop)
    second_result = stream_events.run(_RejectUnexpectedEventSink(), Event())

    assert isinstance(first_result, OperationFailure)
    assert first_result.code is OperationFailureCode.PROVIDER
    assert isinstance(second_result, OperationFailure)
    assert second_result.code is OperationFailureCode.PROVIDER
    assert len(configurations) == 1
    assert sdk_client.connect_calls == 1
    assert sdk_client.close_calls == 1

    adapter.close()
    assert sdk_client.close_calls == 2


def test_slack_socket_mode_close_failure_preserves_primary_run_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _SocketModeSDKClient(
        connect_error=RuntimeError("raw SDK connect failure"),
        close_failures_remaining=1,
    )
    _install_sdk_client(monkeypatch, sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(_RejectUnexpectedEventSink(), Event())

    assert result == OperationFailure(
        IMProvider.SLACK,
        OperationFailureCode.PROVIDER,
        "Slack STREAM client failed",
    )
    assert "raw SDK connect failure" not in repr(result)
    assert "raw SDK close failure" not in repr(result)
    assert sdk_client.close_calls == 1

    adapter.close()
    assert sdk_client.close_calls == 2


def test_slack_official_socket_mode_client_enables_sdk_reconnect_with_bound_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_client = object()
    sdk_client = _SocketModeSDKClient()
    web_tokens: list[str] = []
    socket_options: list[dict[str, object]] = []

    def build_web_client(*, token: str) -> object:
        web_tokens.append(token)
        return web_client

    def build_socket_mode_client(**kwargs: object) -> _SocketModeSDKClient:
        socket_options.append(kwargs)
        return sdk_client

    monkeypatch.setattr(slack_provider, "WebClient", build_web_client)
    monkeypatch.setattr(slack_provider, "SocketModeClient", build_socket_mode_client)

    result = slack_provider._build_slack_stream_sdk_client(_config())

    assert result is sdk_client
    assert web_tokens == ["xoxb-test"]
    assert socket_options == [
        {
            "app_token": "xapp-test",
            "web_client": web_client,
            "auto_reconnect_enabled": True,
            "concurrency": 1,
        }
    ]


def test_slack_pinned_sdk_endpoint_discovery_sends_raw_apps_connections_open_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_requests: list[Request] = []

    def perform_request(web_client: WebClient, url: str, request: Request) -> dict[str, object]:
        del web_client
        raw_requests.append(request)
        assert url == request.full_url
        return {
            "status": 200,
            "headers": {},
            "body": '{"ok":true,"url":"wss://stream.slack.test/socket"}',
        }

    monkeypatch.setattr(WebClient, "_perform_urllib_http_request_internal", perform_request)
    web_client = WebClient(token="xoxb-test")
    sdk_client = SocketModeClient(
        app_token="xapp-test",
        web_client=web_client,
        auto_reconnect_enabled=False,
        concurrency=1,
    )
    try:
        endpoint = sdk_client.issue_new_wss_url()
    finally:
        sdk_client.close()

    assert endpoint == "wss://stream.slack.test/socket"
    assert len(raw_requests) == 1
    raw_request = raw_requests[0]
    parsed_url = urlsplit(raw_request.full_url)
    assert raw_request.get_method() == "POST"
    assert parsed_url.scheme == "https"
    assert parsed_url.netloc == "slack.com"
    assert parsed_url.path == "/api/apps.connections.open"
    assert parsed_url.query == ""
    assert raw_request.get_header("Authorization") == "Bearer xapp-test"
    assert raw_request.data is None


def test_slack_pinned_client_lifecycle_forwards_public_operations_and_stops_absent_runner_thread() -> None:
    sdk_client = _SocketModeSDKClient()
    client = slack_provider._SlackPinnedSocketModeClientLifecycle(
        cast(slack_provider._PinnedSocketModeClient, sdk_client),
    )
    client.socket_mode_request_listeners.append(lambda sdk, request: None)
    response = SocketModeResponse(envelope_id="envelope-1")

    client.connect()
    client.send_socket_mode_response(response)
    client.close()

    assert client.socket_mode_request_listeners is sdk_client.socket_mode_request_listeners
    assert sdk_client.connect_calls == 1
    assert sdk_client.responses == [response]
    assert sdk_client.close_calls == 1
    assert sdk_client.current_session_runner.event.is_set()


def test_slack_socket_mode_close_stops_running_role_and_concurrent_run_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _SocketModeSDKClient()
    _install_sdk_client(monkeypatch, sdk_client)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(
        lambda: stream_events.run(_RejectUnexpectedEventSink(), stop),
    )
    assert sdk_client.connected.wait(timeout=2)

    concurrent_result = stream_events.run(_RejectUnexpectedEventSink(), Event())
    adapter.close()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert results == [None]
    assert isinstance(concurrent_result, OperationFailure)
    assert concurrent_result.code is OperationFailureCode.PROVIDER
    assert sdk_client.close_calls == 1
