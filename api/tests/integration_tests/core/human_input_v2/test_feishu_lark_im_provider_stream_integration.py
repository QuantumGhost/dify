"""Feishu/Lark STREAM integration through the controlled pinned SDK client."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event, Thread
from typing import cast, override

import pytest
from lark_oapi.ws.const import HEADER_MESSAGE_ID, HEADER_SEQ, HEADER_SUM, HEADER_TRACE_ID, HEADER_TYPE
from lark_oapi.ws.enum import FrameType, MessageType
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

import core.human_input_v2.im_provider.providers.feishu_lark_stream as feishu_lark_stream_provider
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AuthenticatedIMEvent,
    EventAcceptance,
    FeishuLarkAdapter,
    FeishuLarkAdapterConfig,
    IMEventSink,
    OperationFailure,
    OperationFailureCode,
    thaw_json_value,
)
from core.human_input_v2.im_provider.providers.feishu_lark_stream import ControlledLarkWebSocketClient

_EVENT_TIME_MILLISECONDS = 1_787_000_000_000


def _config() -> FeishuLarkAdapterConfig:
    return FeishuLarkAdapterConfig(
        provider=IMProvider.FEISHU,
        app_id="cli-integration",
        app_secret="secret-integration",
        verification_token="verification-integration",
        encrypt_key="encrypt-integration",
    )


def _event_payload(
    *,
    event_id: str | None = "evt-integration",
    token: str = "verification-integration",
    app_id: str = "cli-integration",
    tenant_key: str = "tenant-integration",
    create_time: str | None = str(_EVENT_TIME_MILLISECONDS),
) -> bytes:
    header: dict[str, object] = {
        "token": token,
        "event_type": "card.action.trigger",
        "tenant_key": tenant_key,
        "app_id": app_id,
    }
    if event_id is not None:
        header["event_id"] = event_id
    if create_time is not None:
        header["create_time"] = create_time
    return json.dumps(
        {
            "schema": "2.0",
            "header": header,
            "event": {
                "operator": {"tenant_key": tenant_key, "open_id": "ou-integration"},
                "token": "action-token",
                "action": {"tag": "button", "value": {"decision": "approve"}},
                "context": {"open_message_id": "om-integration", "open_chat_id": "oc-integration"},
            },
        },
        separators=(",", ":"),
    ).encode()


def _data_frame(
    payload: bytes,
    *,
    message_id: str = "message-integration",
    fragment_count: int = 1,
    fragment_index: int = 0,
) -> bytes:
    frame = Frame()
    frame.service = 100
    frame.method = FrameType.DATA.value
    frame.SeqID = 1
    frame.LogID = 2
    for key, value in (
        (HEADER_MESSAGE_ID, message_id),
        (HEADER_TRACE_ID, "trace-integration"),
        (HEADER_SUM, str(fragment_count)),
        (HEADER_SEQ, str(fragment_index)),
        (HEADER_TYPE, MessageType.EVENT.value),
    ):
        header = frame.headers.add()
        header.key = key
        header.value = value
    frame.payload = payload
    return frame.SerializeToString()


def _control_frame() -> bytes:
    frame = Frame()
    frame.service = 100
    frame.method = FrameType.CONTROL.value
    frame.SeqID = 1
    frame.LogID = 2
    header = frame.headers.add()
    header.key = HEADER_TYPE
    header.value = MessageType.PING.value
    return frame.SerializeToString()


def _data_ack_statuses(messages: list[bytes]) -> list[int]:
    statuses: list[int] = []
    for message in messages:
        frame = Frame()
        frame.ParseFromString(message)
        if frame.method != FrameType.DATA.value:
            continue
        payload = cast(dict[str, int], json.loads(frame.payload))
        statuses.append(payload["code"])
    return statuses


@dataclass(slots=True)
class _RecordingSink(IMEventSink):
    decision: EventAcceptance | RuntimeError
    events: list[AuthenticatedIMEvent] = field(default_factory=list)
    processed: Event = field(default_factory=Event)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        self.processed.set()
        if isinstance(self.decision, RuntimeError):
            raise self.decision
        return self.decision


@dataclass(slots=True)
class _BlockingSink(IMEventSink):
    started: Event
    release: Event
    completed: Event
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        self.started.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("callback release was not signaled")
        self.completed.set()
        return EventAcceptance.ACCEPTED


@dataclass(frozen=True, slots=True)
class _ConnectionScript:
    frames: tuple[bytes, ...] = ()
    disconnect_after_frames: bool = False
    fail_first_send: bool = False


class _ControlledConnection:
    """WebSocket transport double behind the real controlled SDK lifecycle."""

    sent_messages: list[bytes]
    connected: Event
    frames_forwarded: Event
    close_calls: int
    _frames: list[bytes]
    _disconnect_after_frames: bool
    _fail_first_send: bool
    _send_attempts: int
    _closed: asyncio.Event

    def __init__(self, script: _ConnectionScript) -> None:
        self.sent_messages = []
        self.connected = Event()
        self.frames_forwarded = Event()
        self.close_calls = 0
        self._frames = list(script.frames)
        self._disconnect_after_frames = script.disconnect_after_frames
        self._fail_first_send = script.fail_first_send
        self._send_attempts = 0
        self._closed = asyncio.Event()

    async def recv(self) -> bytes:
        self.connected.set()
        if self._frames:
            message = self._frames.pop(0)
            if not self._frames:
                self.frames_forwarded.set()
            return message
        self.frames_forwarded.set()
        if self._disconnect_after_frames:
            self._disconnect_after_frames = False
            raise ConnectionError("integration transport disconnected")
        await self._closed.wait()
        raise ConnectionError("integration transport closed")

    async def send(self, data: bytes) -> None:
        self._send_attempts += 1
        if self._fail_first_send and self._send_attempts == 1:
            raise ConnectionError("integration transport write failed")
        self.sent_messages.append(data)

    async def close(self) -> None:
        self.close_calls += 1
        self._closed.set()


class _PinnedSDKTransport:
    """Replace only endpoint discovery and WebSocket I/O for the pinned client."""

    clients: list[ControlledLarkWebSocketClient]
    connections: list[_ControlledConnection]
    endpoint_calls: int
    connection_urls: list[str]
    _scripts: tuple[_ConnectionScript, ...]
    _endpoint_failures: int
    _reconnect_count: int

    def __init__(
        self,
        scripts: tuple[_ConnectionScript, ...],
        *,
        endpoint_failures: int = 0,
        reconnect_count: int = 3,
    ) -> None:
        self.clients = []
        self.connections = []
        self.endpoint_calls = 0
        self.connection_urls = []
        self._scripts = scripts
        self._endpoint_failures = endpoint_failures
        self._reconnect_count = reconnect_count

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def get_connection_url(client: ControlledLarkWebSocketClient) -> str:
            if client not in self.clients:
                self.clients.append(client)
            client._ping_interval = 30
            client._reconnect_nonce = 0
            client._reconnect_interval = 0
            client._reconnect_count = self._reconnect_count
            self.endpoint_calls += 1
            if self.endpoint_calls <= self._endpoint_failures:
                raise ConnectionError("integration endpoint unavailable")
            return (
                f"wss://loopback.feishu.test/stream/{self.endpoint_calls}"
                f"?device_id=device-{self.endpoint_calls}&service_id=100"
            )

        monkeypatch.setattr(ControlledLarkWebSocketClient, "_get_conn_url", get_connection_url)
        monkeypatch.setattr(feishu_lark_stream_provider.websockets, "connect", self.connect)

    async def connect(self, url: str, *, proxy: None) -> _ControlledConnection:
        assert proxy is None
        connection_number = len(self.connections)
        if connection_number >= len(self._scripts):
            raise ConnectionError("integration WebSocket unavailable")
        connection = _ControlledConnection(self._scripts[connection_number])
        self.connection_urls.append(url)
        self.connections.append(connection)
        return connection


def _run_in_thread(
    operation: Callable[[], OperationFailure | None],
) -> tuple[Thread, list[OperationFailure | None]]:
    results: list[OperationFailure | None] = []
    thread = Thread(target=lambda: results.append(operation()), daemon=True)
    thread.start()
    return thread, results


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 3) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not satisfied before the deadline")


def _stop_stream(
    adapter: FeishuLarkAdapter,
    stop: Event,
    thread: Thread,
) -> None:
    stop.set()
    thread.join(timeout=5)
    adapter.close()
    thread.join(timeout=5)


def _assert_client_cleanup(client: ControlledLarkWebSocketClient) -> None:
    assert client._lifecycle_loop is None
    assert client._reconnect_lock is None
    assert client._ping_task is None
    assert client._receive_task is None
    assert client._dispatch_tasks == set()
    assert client._conn is None


def test_feishu_stream_preexisting_stop_skips_pinned_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport(())
    transport.install(monkeypatch)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    stop.set()

    result = stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop)

    assert result is None
    assert transport.endpoint_calls == 0
    assert transport.clients == []
    assert transport.connections == []
    adapter.close()


@pytest.mark.parametrize(
    ("decision", "expected_ack"),
    [
        pytest.param(EventAcceptance.ACCEPTED, 200, id="accepted"),
        pytest.param(EventAcceptance.RETRY, 500, id="retry"),
        pytest.param(RuntimeError("sink failed"), 500, id="sink-exception"),
    ],
)
def test_feishu_stream_pinned_sdk_routes_protobuf_event_and_owns_ack(
    monkeypatch: pytest.MonkeyPatch,
    decision: EventAcceptance | RuntimeError,
    expected_ack: int,
) -> None:
    transport = _PinnedSDKTransport((_ConnectionScript((_data_frame(_event_payload()),)),))
    transport.install(monkeypatch)
    sink = _RecordingSink(decision)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(sink, stop))
    try:
        assert sink.processed.wait(timeout=3)
        _wait_until(lambda: bool(transport.connections) and _data_ack_statuses(transport.connections[0].sent_messages))
    finally:
        _stop_stream(adapter, stop, thread)

    assert not thread.is_alive()
    assert results == [None]
    assert len(transport.clients) == 1
    assert len(transport.connections) == 1
    assert _data_ack_statuses(transport.connections[0].sent_messages) == [expected_ack]
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.provider is IMProvider.FEISHU
    assert event.provider_tenant_id == "tenant-integration"
    assert event.provider_event_id == "evt-integration"
    assert event.provider_event_time == datetime.fromtimestamp(_EVENT_TIME_MILLISECONDS / 1000, tz=UTC)
    assert event.received_at.tzinfo is UTC
    assert event.provider_event_type == "card.action.trigger"
    assert thaw_json_value(event.provider_payload) == {
        "operator": {"tenant_key": "tenant-integration", "open_id": "ou-integration"},
        "token": "action-token",
        "action": {"value": {"decision": "approve"}, "tag": "button"},
        "context": {"open_message_id": "om-integration", "open_chat_id": "oc-integration"},
    }
    assert transport.connections[0].close_calls == 1
    _assert_client_cleanup(transport.clients[0])


def test_feishu_stream_pinned_sdk_combines_fragmented_protobuf_data_before_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _event_payload(event_id=None, create_time=None)
    split_at = len(payload) // 2
    transport = _PinnedSDKTransport(
        (
            _ConnectionScript(
                (
                    _data_frame(payload[:split_at], fragment_count=2, fragment_index=0),
                    _data_frame(payload[split_at:], fragment_count=2, fragment_index=1),
                )
            ),
        )
    )
    transport.install(monkeypatch)
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(sink, stop))
    try:
        assert sink.processed.wait(timeout=3)
        _wait_until(lambda: _data_ack_statuses(transport.connections[0].sent_messages) == [200])
    finally:
        _stop_stream(adapter, stop, thread)

    assert results == [None]
    assert len(sink.events) == 1
    assert sink.events[0].provider_event_id is None
    assert sink.events[0].provider_event_time is None
    assert _data_ack_statuses(transport.connections[0].sent_messages) == [200]
    _assert_client_cleanup(transport.clients[0])


def test_feishu_stream_pinned_sdk_rejects_invalid_envelopes_and_control_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_payloads = (
        b"not-json",
        b'{"schema":"2.0","event":{}}',
        _event_payload(token="wrong-token"),
        _event_payload(app_id="wrong-app"),
        _event_payload(tenant_key=" "),
        _event_payload(create_time="invalid"),
    )
    invalid_frames = tuple(
        _data_frame(payload, message_id=f"invalid-{index}") for index, payload in enumerate(invalid_payloads)
    )
    frames = (_control_frame(), *invalid_frames)
    transport = _PinnedSDKTransport((_ConnectionScript(frames),))
    transport.install(monkeypatch)
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(sink, stop))
    try:
        _wait_until(
            lambda: (
                bool(transport.connections)
                and len(_data_ack_statuses(transport.connections[0].sent_messages)) == len(invalid_payloads)
            )
        )
    finally:
        _stop_stream(adapter, stop, thread)

    assert results == [None]
    assert sink.events == []
    assert _data_ack_statuses(transport.connections[0].sent_messages) == [500] * len(invalid_payloads)
    _assert_client_cleanup(transport.clients[0])


def test_feishu_stream_pinned_sdk_retries_initial_endpoint_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport((_ConnectionScript(),), endpoint_failures=1)
    transport.install(monkeypatch)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop))
    try:
        _wait_until(lambda: len(transport.connections) == 1)
        assert transport.connections[0].connected.wait(timeout=3)
    finally:
        _stop_stream(adapter, stop, thread)

    assert results == [None]
    assert transport.endpoint_calls == 2
    assert len(transport.clients) == 1
    _assert_client_cleanup(transport.clients[0])


def test_feishu_stream_pinned_sdk_reconnects_after_transport_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport(
        (
            _ConnectionScript(disconnect_after_frames=True),
            _ConnectionScript(),
        )
    )
    transport.install(monkeypatch)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop))
    try:
        _wait_until(lambda: len(transport.connections) == 2)
        assert transport.connections[1].connected.wait(timeout=3)
    finally:
        _stop_stream(adapter, stop, thread)

    assert results == [None]
    assert transport.endpoint_calls == 2
    assert all(connection.close_calls == 1 for connection in transport.connections)
    endpoint_calls_after_stop = transport.endpoint_calls
    time.sleep(0.05)
    assert transport.endpoint_calls == endpoint_calls_after_stop
    _assert_client_cleanup(transport.clients[0])


def test_feishu_stream_pinned_sdk_reconnects_after_ping_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport(
        (
            _ConnectionScript(fail_first_send=True),
            _ConnectionScript(),
        )
    )
    transport.install(monkeypatch)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop))
    try:
        _wait_until(lambda: len(transport.connections) == 2)
        assert transport.connections[1].connected.wait(timeout=3)
    finally:
        _stop_stream(adapter, stop, thread)

    assert results == [None]
    assert transport.endpoint_calls == 2
    assert all(connection.close_calls == 1 for connection in transport.connections)
    _assert_client_cleanup(transport.clients[0])


def test_feishu_stream_pinned_sdk_exhausted_reconnect_is_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport((), endpoint_failures=3, reconnect_count=2)
    transport.install(monkeypatch)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), Event())

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER
    assert transport.endpoint_calls == 3
    assert len(transport.clients) == 1
    _assert_client_cleanup(transport.clients[0])
    adapter.close()


def test_feishu_stream_stop_waits_for_active_callback_and_wire_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport((_ConnectionScript((_data_frame(_event_payload()),)),))
    transport.install(monkeypatch)
    callback_started = Event()
    callback_release = Event()
    callback_completed = Event()
    sink = _BlockingSink(callback_started, callback_release, callback_completed)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(sink, stop))
    try:
        assert callback_started.wait(timeout=3)
        stop.set()
        thread.join(timeout=0.05)

        assert thread.is_alive()
        assert not callback_completed.is_set()
        assert _data_ack_statuses(transport.connections[0].sent_messages) == []
    finally:
        callback_release.set()
        thread.join(timeout=5)
        adapter.close()

    assert not thread.is_alive()
    assert callback_completed.is_set()
    assert results == [None]
    assert _data_ack_statuses(transport.connections[0].sent_messages) == [200]
    _assert_client_cleanup(transport.clients[0])


def test_feishu_stream_public_close_stops_active_pinned_client_and_rejects_later_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _PinnedSDKTransport((_ConnectionScript(),))
    transport.install(monkeypatch)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    thread, results = _run_in_thread(lambda: stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), stop))
    _wait_until(lambda: len(transport.connections) == 1)
    assert transport.connections[0].connected.wait(timeout=3)

    concurrent_result = stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), Event())
    adapter.close()
    thread.join(timeout=5)
    closed_result = stream_events.run(_RecordingSink(EventAcceptance.ACCEPTED), Event())

    assert not thread.is_alive()
    assert results == [None]
    assert isinstance(concurrent_result, OperationFailure)
    assert concurrent_result.code is OperationFailureCode.PROVIDER
    assert isinstance(closed_result, OperationFailure)
    assert closed_result.code is OperationFailureCode.CLOSED
    _assert_client_cleanup(transport.clients[0])


def test_feishu_controlled_client_stop_before_start_is_terminal_and_restart_is_rejected() -> None:
    async def run() -> None:
        client = feishu_lark_stream_provider.create_controlled_lark_websocket_client(
            app_id="cli-integration",
            app_secret="secret-integration",
            callback=lambda event: None,
            domain="https://open.feishu.cn",
        )
        await client.stop()
        await client.start()

        with pytest.raises(RuntimeError, match="cannot be restarted"):
            await client.start()

        client._cache._cron.cancel()
        await asyncio.gather(client._cache._cron, return_exceptions=True)

    asyncio.run(run())
