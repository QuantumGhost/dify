"""Slack STREAM integration through the pinned SDK and controlled transport."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC
from threading import Event, Thread
from typing import cast, override

import pytest
import slack_sdk.socket_mode.builtin.client as slack_builtin_client
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.builtin.connection import ConnectionState
from slack_sdk.web import WebClient

import core.human_input_v2.im_provider.providers.slack as slack_provider
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AdapterCloseError,
    AuthenticatedIMEvent,
    EventAcceptance,
    IMEventSink,
    OperationFailure,
    OperationFailureCode,
    SlackAdapter,
    SlackAdapterConfig,
    thaw_json_value,
)


def _config() -> SlackAdapterConfig:
    return SlackAdapterConfig(
        bot_token="xoxb-integration-token",
        signing_secret="integration-signing-secret",
        app_token="xapp-integration-token",
    )


def _socket_mode_frame(request_type: str, envelope_id: str, payload: dict[str, object]) -> str:
    return json.dumps(
        {
            "type": request_type,
            "envelope_id": envelope_id,
            "payload": payload,
        },
        separators=(",", ":"),
    )


@dataclass(slots=True)
class _RecordingSink(IMEventSink):
    decision: EventAcceptance | RuntimeError
    events: list[AuthenticatedIMEvent] = field(default_factory=list)
    processed: Event = field(default_factory=Event)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        if isinstance(self.decision, RuntimeError):
            self.processed.set()
            raise self.decision
        self.processed.set()
        return self.decision


@dataclass(frozen=True, slots=True)
class _ConnectionScript:
    messages: tuple[str, ...] = ()
    disconnect_after_messages: bool = False
    live_receive: _LiveReceiveGate | None = None


@dataclass(slots=True)
class _LiveReceiveGate:
    """Holds the pinned SDK session runner inside a controlled live receive."""

    ignore_termination: bool = False
    entered: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)

    def receive(self, state: ConnectionState) -> None:
        self.entered.set()
        while not self.release.is_set():
            if state.terminated and not self.ignore_termination:
                return
            self.release.wait(0.005)
        state.terminated = True


class _ControlledConnection:
    """Socket transport double behind the real SDK queue and lifecycle threads."""

    session_id: str
    connected: Event
    messages_forwarded: Event
    ack_sent: Event
    sent_messages: list[dict[str, object]]
    close_calls: int
    _script: _ConnectionScript
    _on_message: Callable[[str], None]
    _on_close: Callable[[int, str | None], None]
    _active: bool
    _closed: Event

    def __init__(
        self,
        session_number: int,
        script: _ConnectionScript,
        on_message: Callable[[str], None],
        on_close: Callable[[int, str | None], None],
    ) -> None:
        self.session_id = f"session-{session_number}"
        self.connected = Event()
        self.messages_forwarded = Event()
        self.ack_sent = Event()
        self.sent_messages = []
        self.close_calls = 0
        self._script = script
        self._on_message = on_message
        self._on_close = on_close
        self._active = False
        self._closed = Event()

    def connect(self) -> None:
        self._active = True
        self.connected.set()

    def is_active(self) -> bool:
        return self._active

    def run_until_completion(self, state: ConnectionState) -> None:
        for message in self._script.messages:
            if not self._active or state.terminated:
                break
            self._on_message(message)
        self.messages_forwarded.set()
        if self._script.live_receive is not None:
            self._script.live_receive.receive(state)
            return
        if self._script.disconnect_after_messages and self._active:
            self._active = False
            self._on_close(1000, "integration disconnect")
            state.terminated = True
            return
        while self._active and not state.terminated:
            self._closed.wait(0.01)
        state.terminated = True

    def send(self, payload: str) -> None:
        decoded = json.loads(payload)
        assert isinstance(decoded, dict)
        self.sent_messages.append(cast(dict[str, object], decoded))
        self.ack_sent.set()

    def close(self) -> None:
        self.close_calls += 1
        self._active = False
        self._closed.set()

    def check_state(self) -> None:
        return None


class _PinnedSDKTransport:
    """Controls Slack endpoint discovery and built-in Connection construction."""

    connections: list[_ControlledConnection]
    sdk_clients: list[SocketModeClient]
    endpoint_tokens: list[str]
    _scripts: tuple[_ConnectionScript, ...]

    def __init__(self, scripts: tuple[_ConnectionScript, ...]) -> None:
        self.connections = []
        self.sdk_clients = []
        self.endpoint_tokens = []
        self._scripts = scripts

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def issue_endpoint(web_client: WebClient, *, app_token: str) -> dict[str, str | bool]:
            del web_client
            self.endpoint_tokens.append(app_token)
            return {
                "ok": True,
                "url": f"wss://loopback.slack.test/socket/{len(self.endpoint_tokens)}",
            }

        monkeypatch.setattr(WebClient, "apps_connections_open", issue_endpoint)
        monkeypatch.setattr(slack_builtin_client, "Connection", self.create_connection)

    def create_connection(self, **options: object) -> _ControlledConnection:
        connection_number = len(self.connections)
        if connection_number >= len(self._scripts):
            raise AssertionError("unexpected Slack Socket Mode connection")
        on_message = options.get("on_message_listener")
        on_close = options.get("on_close_listener")
        assert callable(on_message)
        assert callable(on_close)
        sdk_client = getattr(on_message, "__self__", None)
        assert isinstance(sdk_client, SocketModeClient)
        connection = _ControlledConnection(
            connection_number + 1,
            self._scripts[connection_number],
            cast(Callable[[str], None], on_message),
            cast(Callable[[int, str | None], None], on_close),
        )
        self.connections.append(connection)
        self.sdk_clients.append(sdk_client)
        return connection


def _run_in_thread(
    operation: Callable[[], OperationFailure | None],
) -> tuple[Thread, list[OperationFailure | None]]:
    results: list[OperationFailure | None] = []
    thread = Thread(target=lambda: results.append(operation()), daemon=True)
    thread.start()
    return thread, results


def _assert_public_sdk_closed(client: SocketModeClient) -> None:
    assert client.closed is True
    assert client.auto_reconnect_enabled is False
    assert not client.current_app_monitor.is_alive()
    assert not client.message_processor.is_alive()
    assert client.message_workers._shutdown is True


def _shutdown_orphaned_sdk_runner(client: SocketModeClient) -> None:
    if client.current_session_runner.is_alive():
        client.current_session_runner.shutdown()


def test_slack_stream_preexisting_stop_skips_pinned_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport(())
    transport.install(monkeypatch)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    stop.set()

    result = stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop)

    assert result is None
    assert transport.endpoint_tokens == []
    assert transport.connections == []
    assert transport.sdk_clients == []
    adapter.close()


@pytest.mark.parametrize(
    ("decision", "expects_ack"),
    [
        pytest.param(EventAcceptance.ACCEPTED, True, id="accepted"),
        pytest.param(EventAcceptance.RETRY, False, id="retry"),
        pytest.param(RuntimeError("sink failed"), False, id="sink-exception"),
    ],
)
def test_slack_stream_pinned_sdk_routes_wire_event_and_owns_ack(
    monkeypatch: pytest.MonkeyPatch,
    decision: EventAcceptance | RuntimeError,
    expects_ack: bool,
) -> None:
    transport = _PinnedSDKTransport(
        (
            _ConnectionScript(
                (
                    _socket_mode_frame(
                        "interactive",
                        "interactive-envelope",
                        {
                            "type": "block_actions",
                            "team": {"id": "T-integration", "domain": "test-workspace"},
                            "user": {"id": "U-test"},
                            "actions": [{"action_id": "approve", "value": "approved"}],
                        },
                    ),
                )
            ),
        )
    )
    transport.install(monkeypatch)
    sink = _RecordingSink(decision)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(sink, stop))
    try:
        for _ in range(200):
            if transport.connections:
                break
            time.sleep(0.005)
        assert len(transport.connections) == 1
        connection = transport.connections[0]
        assert connection.connected.wait(timeout=2)
        assert connection.messages_forwarded.wait(timeout=2)
        assert sink.processed.wait(timeout=2)
        if expects_ack:
            assert connection.ack_sent.wait(timeout=2)
        stop.set()
        thread.join(timeout=5)
    finally:
        stop.set()
        adapter.close()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert results == [None]
    assert slack_provider.SocketModeClient is SocketModeClient
    assert transport.endpoint_tokens == ["xapp-integration-token"]
    assert len(transport.sdk_clients) == 1
    client = transport.sdk_clients[0]
    assert client.app_token == "xapp-integration-token"
    assert client.web_client.token == "xoxb-integration-token"
    assert len(client.socket_mode_request_listeners) == 1
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.provider is IMProvider.SLACK
    assert event.provider_tenant_id == "T-integration"
    assert event.provider_event_id is None
    assert event.provider_event_time is None
    assert event.received_at.tzinfo is UTC
    assert event.provider_event_type == "block_actions"
    assert thaw_json_value(event.provider_payload) == {
        "type": "block_actions",
        "team": {"id": "T-integration", "domain": "test-workspace"},
        "user": {"id": "U-test"},
        "actions": [{"action_id": "approve", "value": "approved"}],
    }
    assert transport.connections[0].sent_messages == ([{"envelope_id": "interactive-envelope"}] if expects_ack else [])
    assert transport.connections[0].close_calls >= 1
    try:
        _assert_public_sdk_closed(client)
    finally:
        _shutdown_orphaned_sdk_runner(client)


def test_slack_stream_pinned_sdk_keeps_out_of_scope_slash_command_out_of_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _socket_mode_frame(
        "slash_commands",
        "slash-envelope",
        {
            "team_id": "T-slash",
            "team_domain": "test-workspace",
            "channel_id": "C-test",
            "user_id": "U-test",
            "command": "/approve",
            "text": "request-1",
        },
    )
    transport = _PinnedSDKTransport((_ConnectionScript((frame,)),))
    transport.install(monkeypatch)
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(sink, stop))
    try:
        for _ in range(200):
            if transport.connections:
                break
            time.sleep(0.005)
        assert len(transport.connections) == 1
        connection = transport.connections[0]
        assert connection.messages_forwarded.wait(timeout=2)
        client = transport.sdk_clients[0]
        for _ in range(200):
            if client.message_queue.empty():
                break
            time.sleep(0.005)
        assert client.message_queue.empty()
        stop.set()
        thread.join(timeout=5)
    finally:
        stop.set()
        adapter.close()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert results == [None]
    assert sink.events == []
    assert transport.connections[0].sent_messages == []
    client = transport.sdk_clients[0]
    try:
        _assert_public_sdk_closed(client)
    finally:
        _shutdown_orphaned_sdk_runner(client)


def test_slack_stream_pinned_sdk_keeps_control_and_invalid_frames_out_of_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport(
        (
            _ConnectionScript(
                (
                    _socket_mode_frame("hello", "hello-envelope", {}),
                    _socket_mode_frame("events_api", "invalid-envelope", {}),
                    _socket_mode_frame(
                        "events_api",
                        "challenge-envelope",
                        {"type": "url_verification", "team_id": "T-integration"},
                    ),
                    _socket_mode_frame("slash_commands", "slash-missing-tenant", {}),
                    _socket_mode_frame("slash_commands", "slash-blank-tenant", {"team_id": " "}),
                    _socket_mode_frame(
                        "interactive",
                        "interactive-missing-tenant",
                        {"type": "block_actions"},
                    ),
                    _socket_mode_frame(
                        "interactive",
                        "interactive-blank-tenant",
                        {"type": "block_actions", "team": {"id": " "}},
                    ),
                )
            ),
        )
    )
    transport.install(monkeypatch)
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(sink, stop))
    try:
        for _ in range(200):
            if transport.connections:
                break
            time.sleep(0.005)
        assert len(transport.connections) == 1
        connection = transport.connections[0]
        assert connection.messages_forwarded.wait(timeout=2)
        client = transport.sdk_clients[0]
        for _ in range(200):
            if client.message_queue.empty():
                break
            time.sleep(0.005)
        assert client.message_queue.empty()
        stop.set()
        thread.join(timeout=5)
    finally:
        stop.set()
        adapter.close()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert results == [None]
    assert sink.events == []
    assert transport.connections[0].sent_messages == []
    client = transport.sdk_clients[0]
    try:
        _assert_public_sdk_closed(client)
    finally:
        _shutdown_orphaned_sdk_runner(client)


def test_slack_stream_pinned_sdk_reconnects_after_transport_disconnect_and_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport(
        (
            _ConnectionScript(disconnect_after_messages=True),
            _ConnectionScript(),
        )
    )
    transport.install(monkeypatch)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop))
    try:
        for _ in range(400):
            if len(transport.connections) == 2:
                break
            time.sleep(0.005)
        assert len(transport.connections) == 2
        assert transport.connections[1].connected.wait(timeout=2)
        stop.set()
        thread.join(timeout=5)
    finally:
        stop.set()
        adapter.close()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert results == [None]
    assert transport.endpoint_tokens == ["xapp-integration-token", "xapp-integration-token"]
    assert len(transport.sdk_clients) == 2
    client = transport.sdk_clients[0]
    assert all(candidate is client for candidate in transport.sdk_clients)
    assert all(connection.close_calls >= 1 for connection in transport.connections)
    endpoint_count_after_stop = len(transport.endpoint_tokens)
    time.sleep(0.05)
    assert len(transport.endpoint_tokens) == endpoint_count_after_stop
    try:
        _assert_public_sdk_closed(client)
    finally:
        _shutdown_orphaned_sdk_runner(client)


def test_slack_stream_public_close_stops_all_sdk_runner_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_threads = tuple((thread.ident, thread.name) for thread in threading.enumerate())
    baseline_thread_ids = {thread_id for thread_id, _ in baseline_threads}
    transport = _PinnedSDKTransport((_ConnectionScript(),))
    transport.install(monkeypatch)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop))
    try:
        for _ in range(200):
            if transport.connections:
                break
            time.sleep(0.005)
        assert len(transport.connections) == 1
        assert transport.connections[0].connected.wait(timeout=2)
        stop.set()
        thread.join(timeout=5)
    finally:
        stop.set()
        adapter.close()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert results == [None]
    assert len(transport.sdk_clients) == 1
    client = transport.sdk_clients[0]
    _assert_public_sdk_closed(client)
    runner_thread = client.current_session_runner.thread
    new_alive_threads = tuple(
        current_thread.name
        for current_thread in threading.enumerate()
        if current_thread.ident not in baseline_thread_ids and current_thread.is_alive()
    )
    try:
        assert runner_thread is None or not runner_thread.is_alive(), (
            f"Slack SDK runner thread remained alive after public close: "
            f"runner={runner_thread.name if runner_thread is not None else None}, "
            f"baseline={baseline_threads}, new_alive={new_alive_threads}"
        )
    finally:
        _shutdown_orphaned_sdk_runner(client)


def test_slack_stream_public_close_stops_sdk_runner_blocked_in_live_receive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_threads = tuple((thread.ident, thread.name) for thread in threading.enumerate())
    baseline_thread_ids = {thread_id for thread_id, _ in baseline_threads}
    close_timeout_seconds = 0.05
    monkeypatch.setattr(slack_provider, "_STREAM_RUNNER_CLOSE_TIMEOUT_SECONDS", close_timeout_seconds)
    live_receive = _LiveReceiveGate()
    transport = _PinnedSDKTransport((_ConnectionScript(live_receive=live_receive),))
    transport.install(monkeypatch)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop))
    close_error: AdapterCloseError | None = None
    elapsed_seconds = 0.0
    runner_stopped_before_release = False
    try:
        assert live_receive.entered.wait(timeout=2)
        assert len(transport.connections) == 1
        assert len(transport.sdk_clients) == 1
        client = transport.sdk_clients[0]
        runner_thread = client.current_session_runner.thread
        assert runner_thread is not None
        assert runner_thread.is_alive()

        close_started_at = time.monotonic()
        try:
            adapter.close()
        except AdapterCloseError as error:
            close_error = error
        elapsed_seconds = time.monotonic() - close_started_at
        runner_stopped_before_release = not runner_thread.is_alive()

        assert elapsed_seconds < 2.0
        assert transport.connections[0].close_calls >= 1
        _assert_public_sdk_closed(client)

        if close_error is not None:
            live_receive.release.set()
            adapter.close()
        thread.join(timeout=2)
    finally:
        live_receive.release.set()
        stop.set()
        try:
            adapter.close()
        except AdapterCloseError:
            pass
        thread.join(timeout=2)
        if transport.sdk_clients:
            _shutdown_orphaned_sdk_runner(transport.sdk_clients[0])

    assert close_error is None, "Slack adapter close failed while the SDK runner was in a live receive"
    assert runner_stopped_before_release
    assert not thread.is_alive()
    assert results == [None]
    assert len(transport.connections) == 1
    assert len(transport.sdk_clients) == 1
    new_alive_threads = tuple(
        current_thread.name
        for current_thread in threading.enumerate()
        if current_thread.ident not in baseline_thread_ids and current_thread.is_alive()
    )
    assert new_alive_threads == (), (
        f"Slack close leaked threads: baseline={baseline_threads}, new_alive={new_alive_threads}"
    )


def test_slack_stream_close_failure_retains_sdk_client_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_thread_ids = {thread.ident for thread in threading.enumerate()}
    monkeypatch.setattr(slack_provider, "_STREAM_RUNNER_CLOSE_TIMEOUT_SECONDS", 0.05)
    live_receive = _LiveReceiveGate(ignore_termination=True)
    transport = _PinnedSDKTransport((_ConnectionScript(live_receive=live_receive),))
    transport.install(monkeypatch)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop))
    try:
        assert live_receive.entered.wait(timeout=2)
        assert len(transport.sdk_clients) == 1
        client = transport.sdk_clients[0]

        with pytest.raises(AdapterCloseError, match="Slack"):
            adapter.close()

        assert client.current_session_runner.is_alive()
        assert transport.connections[0].close_calls >= 1
        assert transport.sdk_clients == [client]

        live_receive.release.set()
        adapter.close()
        thread.join(timeout=2)
    finally:
        live_receive.release.set()
        stop.set()
        try:
            adapter.close()
        except AdapterCloseError:
            pass
        thread.join(timeout=2)
        if transport.sdk_clients:
            _shutdown_orphaned_sdk_runner(transport.sdk_clients[0])

    assert not thread.is_alive()
    assert results == [None]
    assert transport.sdk_clients == [client]
    assert not client.current_session_runner.is_alive()
    new_alive_threads = tuple(
        current_thread.name
        for current_thread in threading.enumerate()
        if current_thread.ident not in baseline_thread_ids and current_thread.is_alive()
    )
    assert new_alive_threads == ()


def test_slack_stream_run_returns_typed_failure_when_sdk_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_thread_ids = {thread.ident for thread in threading.enumerate()}
    monkeypatch.setattr(slack_provider, "_STREAM_RUNNER_CLOSE_TIMEOUT_SECONDS", 0.05)
    live_receive = _LiveReceiveGate(ignore_termination=True)
    transport = _PinnedSDKTransport((_ConnectionScript(live_receive=live_receive),))
    transport.install(monkeypatch)
    adapter = SlackAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop))
    try:
        assert live_receive.entered.wait(timeout=2)
        assert len(transport.sdk_clients) == 1
        client = transport.sdk_clients[0]

        stop.set()
        thread.join(timeout=2)

        assert not thread.is_alive()
        assert results == [
            OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.PROVIDER,
                "Slack STREAM client cleanup failed",
            )
        ]
        assert client.current_session_runner.is_alive()
        assert transport.sdk_clients == [client]

        live_receive.release.set()
        adapter.close()
    finally:
        live_receive.release.set()
        stop.set()
        try:
            adapter.close()
        except AdapterCloseError:
            pass
        thread.join(timeout=2)
        if transport.sdk_clients:
            _shutdown_orphaned_sdk_runner(transport.sdk_clients[0])

    assert not client.current_session_runner.is_alive()
    new_alive_threads = tuple(
        current_thread.name
        for current_thread in threading.enumerate()
        if current_thread.ident not in baseline_thread_ids and current_thread.is_alive()
    )
    assert new_alive_threads == ()
