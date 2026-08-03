"""Feishu/Lark long-connection public capability and construction contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event, Thread
from typing import cast, override

import lark_oapi.ws.client as lark_ws_client  # type: ignore[import-untyped]
import pytest
from lark_oapi.event.custom import CustomizedEvent
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.ws.const import HEADER_MESSAGE_ID, HEADER_SEQ, HEADER_SUM, HEADER_TRACE_ID, HEADER_TYPE
from lark_oapi.ws.enum import FrameType, MessageType
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

import core.human_input_v2.im_provider.providers.feishu_lark as feishu_lark_provider
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
from core.human_input_v2.im_provider.providers.feishu_lark_stream import (
    ControlledLarkWebSocketClient,
    create_controlled_lark_websocket_client,
)


def _config() -> FeishuLarkAdapterConfig:
    return FeishuLarkAdapterConfig(
        provider=IMProvider.FEISHU,
        app_id="cli-test",
        app_secret="secret-test",
        verification_token="verification-test",
        encrypt_key="encrypt-test",
    )


@dataclass(slots=True)
class _RejectUnexpectedEventSink(IMEventSink):
    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        raise AssertionError("pre-lifecycle STREAM test must not deliver an event")


@dataclass(slots=True)
class _RecordingSink(IMEventSink):
    acceptance: EventAcceptance
    error: Exception | None = None
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return self.acceptance


type _SDKEventCallback = Callable[[CustomizedEvent], None]


@dataclass(frozen=True, slots=True)
class _RawEndpointResponse:
    status_code: int
    content: bytes


@dataclass(slots=True)
class _CallbackSDKClient:
    callback: _SDKEventCallback | None
    events: tuple[CustomizedEvent, ...]
    ack_statuses: list[int]
    stop_calls: int = 0

    async def start(self) -> None:
        if self.callback is None:
            return
        for event in self.events:
            try:
                self.callback(event)
            except Exception:
                self.ack_statuses.append(500)
            else:
                self.ack_statuses.append(200)

    async def stop(self) -> None:
        self.stop_calls += 1


@dataclass(slots=True)
class _ConcurrentCallbackSDKClient:
    callback: _SDKEventCallback | None
    events: tuple[CustomizedEvent, ...]
    ack_statuses: list[int]

    async def start(self) -> None:
        if self.callback is None:
            return

        async def deliver(event: CustomizedEvent) -> None:
            try:
                await asyncio.to_thread(self.callback, event)
            except Exception:
                self.ack_statuses.append(500)
            else:
                self.ack_statuses.append(200)

        await asyncio.gather(*(deliver(event) for event in self.events))

    async def stop(self) -> None:
        return None


@dataclass(slots=True)
class _BlockingSDKClient:
    started: Event
    stopped: Event
    stop_calls: int = 0

    async def start(self) -> None:
        self.started.set()
        await asyncio.to_thread(self.stopped.wait)

    async def stop(self) -> None:
        self.stop_calls += 1
        self.stopped.set()


def _sdk_event(
    *,
    event_id: str = "evt-1",
    app_id: str = "cli-test",
    token: str = "verification-test",
    tenant_key: str = "tenant-1",
) -> CustomizedEvent:
    return CustomizedEvent(
        {
            "schema": "2.0",
            "header": {
                "event_id": event_id,
                "token": token,
                "create_time": "1787000000000",
                "event_type": "card.action.trigger",
                "tenant_key": tenant_key,
                "app_id": app_id,
            },
            "event": {
                "operator": {"tenant_key": tenant_key, "open_id": "ou-1"},
                "token": "action-token",
                "action": {"tag": "button", "value": {"decision": "approve"}},
                "context": {"open_message_id": "om-1", "open_chat_id": "oc-1"},
            },
        }
    )


def _sdk_data_frame(
    payload: bytes,
    *,
    message_id: str = "message-1",
    fragment_count: int = 1,
    fragment_index: int = 0,
) -> Frame:
    frame = Frame()
    frame.service = 100
    frame.method = FrameType.DATA.value
    frame.SeqID = 1
    frame.LogID = 2
    for key, value in (
        (HEADER_MESSAGE_ID, message_id),
        (HEADER_TRACE_ID, "trace-1"),
        (HEADER_SUM, str(fragment_count)),
        (HEADER_SEQ, str(fragment_index)),
        (HEADER_TYPE, MessageType.EVENT.value),
    ):
        header = frame.headers.add()
        header.key = key
        header.value = value
    frame.payload = payload
    return frame


def test_feishu_pinned_sdk_endpoint_discovery_sends_raw_callback_ws_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_requests: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, str],
    ) -> _RawEndpointResponse:
        raw_requests.append((url, dict(headers), dict(json)))
        return _RawEndpointResponse(
            200,
            b'{"code":0,"msg":"success","data":{'
            b'"URL":"wss://stream.feishu.test/ws?device_id=device-1&service_id=100",'
            b'"ClientConfig":{"ReconnectCount":2,"ReconnectInterval":3,'
            b'"ReconnectNonce":4,"PingInterval":5}}}',
        )

    monkeypatch.setattr(lark_ws_client.requests, "post", post)

    async def run() -> tuple[str, ControlledLarkWebSocketClient]:
        client = create_controlled_lark_websocket_client(
            app_id="cli-test",
            app_secret="secret-test",
            callback=lambda event: None,
            domain="https://open.feishu.cn",
        )
        try:
            endpoint = await asyncio.to_thread(client._get_conn_url)
            return endpoint, client
        finally:
            client._cache._cron.cancel()
            await asyncio.gather(client._cache._cron, return_exceptions=True)

    endpoint, client = asyncio.run(run())

    assert endpoint == "wss://stream.feishu.test/ws?device_id=device-1&service_id=100"
    assert len(raw_requests) == 1
    url, headers, request_body = raw_requests[0]
    assert url == "https://open.feishu.cn/callback/ws/endpoint"
    assert headers["locale"] == "zh"
    assert headers["User-Agent"]
    assert request_body == {"AppID": "cli-test", "AppSecret": "secret-test"}
    assert client._reconnect_count == 2
    assert client._reconnect_interval == 3
    assert client._reconnect_nonce == 4
    assert client._ping_interval == 5


@dataclass(slots=True)
class _RecordingConnection:
    sent: list[bytes]

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        return None


@dataclass(slots=True)
class _LifecycleConnection:
    fail_receive: bool
    fail_send: bool = False
    close_calls: int = 0
    send_calls: int = 0
    send_attempted: Event = field(default_factory=Event)
    closed: asyncio.Event = field(default_factory=asyncio.Event)

    async def recv(self) -> bytes:
        if self.fail_receive:
            raise ConnectionError("connection lost")
        await self.closed.wait()
        raise ConnectionError("connection closed")

    async def send(self, data: bytes) -> None:
        self.send_calls += 1
        self.send_attempted.set()
        if self.fail_send:
            raise ConnectionError("connection write failed")

    async def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


@dataclass(slots=True)
class _OneFrameLifecycleConnection:
    message: bytes
    sent: list[bytes] = field(default_factory=list)
    close_calls: int = 0
    delivered: bool = False
    closed: asyncio.Event = field(default_factory=asyncio.Event)

    async def recv(self) -> bytes:
        if not self.delivered:
            self.delivered = True
            return self.message
        await self.closed.wait()
        raise ConnectionError("connection closed")

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


@dataclass(slots=True)
class _BlockingRecordingSink(IMEventSink):
    callback_started: Event
    callback_release: Event
    callback_completed: Event
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        self.callback_started.set()
        if not self.callback_release.wait(timeout=5):
            raise AssertionError("callback release was not signaled")
        self.callback_completed.set()
        return EventAcceptance.ACCEPTED


async def _cleanup_controlled_client(
    client: ControlledLarkWebSocketClient,
    start_task: asyncio.Task[None],
) -> None:
    if not start_task.done():
        await client.stop()
    await asyncio.gather(start_task, return_exceptions=True)
    client._cache._cron.cancel()
    await asyncio.gather(client._cache._cron, return_exceptions=True)


def _ack_status(serialized_frame: bytes) -> int:
    frame = Frame()
    frame.ParseFromString(serialized_frame)
    payload = cast(dict[str, int], json.loads(frame.payload))
    return payload["code"]


def _sdk_event_payload(
    *,
    event_id: str | None = "evt-wire-1",
    schema: str = "2.0",
    token: str = "verification-test",
    app_id: str = "cli-test",
    tenant_key: str = "tenant-wire-1",
    create_time: str = "1787000000000",
) -> bytes:
    header = {
        "token": token,
        "create_time": create_time,
        "event_type": "card.action.trigger",
        "tenant_key": tenant_key,
        "app_id": app_id,
    }
    if event_id is not None:
        header["event_id"] = event_id
    return json.dumps(
        {
            "schema": schema,
            "header": header,
            "event": {
                "operator": {"tenant_key": tenant_key, "open_id": "ou-wire-1"},
                "token": "action-token",
                "action": {"tag": "button", "value": {"decision": "approve"}},
                "context": {"open_message_id": "om-wire-1", "open_chat_id": "oc-wire-1"},
            },
        },
        separators=(",", ":"),
    ).encode()


def _run_actual_sdk_frames(
    sink: IMEventSink,
    frames: tuple[Frame, ...],
) -> tuple[list[bytes], list[int]]:
    sent: list[bytes] = []
    sent_counts: list[int] = []

    async def run() -> None:
        listener = feishu_lark_provider._FeishuLarkStreamEventListener(_config(), sink.accept)
        client = create_controlled_lark_websocket_client(
            app_id="cli-test",
            app_secret="secret-test",
            callback=listener,
            domain="https://open.feishu.cn",
        )
        connection = _RecordingConnection(sent)
        client._lock = asyncio.Lock()
        client._conn = connection
        for frame in frames:
            await client._handle_message(frame.SerializeToString())
            sent_counts.append(len(sent))
        client._cache._cron.cancel()
        await asyncio.gather(client._cache._cron, return_exceptions=True)

    asyncio.run(run())
    return sent, sent_counts


def test_feishu_public_adapter_exposes_long_connection_and_preexisting_stop_skips_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configurations: list[FeishuLarkAdapterConfig] = []

    def build_stream_sdk_client(config: FeishuLarkAdapterConfig) -> object:
        configurations.append(config)
        return object()

    monkeypatch.setattr(
        feishu_lark_provider,
        "_build_feishu_lark_stream_sdk_client",
        build_stream_sdk_client,
        raising=False,
    )
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    stop.set()

    result = stream_events.run(_RejectUnexpectedEventSink(), stop)

    assert result is None
    assert configurations == []
    adapter.close()


def test_feishu_long_connection_constructs_sdk_role_from_bound_config_and_types_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configurations: list[FeishuLarkAdapterConfig] = []

    def build_stream_sdk_client(
        config: FeishuLarkAdapterConfig,
        callback: _SDKEventCallback | None = None,
    ) -> object:
        del callback
        configurations.append(config)
        raise RuntimeError("long-connection construction failed")

    monkeypatch.setattr(
        feishu_lark_provider,
        "_build_feishu_lark_stream_sdk_client",
        build_stream_sdk_client,
        raising=False,
    )
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(_RejectUnexpectedEventSink(), Event())

    assert configurations == [_config()]
    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER
    adapter.close()


def test_feishu_long_connection_post_close_is_closed_without_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configurations: list[FeishuLarkAdapterConfig] = []
    monkeypatch.setattr(
        feishu_lark_provider,
        "_build_feishu_lark_stream_sdk_client",
        lambda config: configurations.append(config),
        raising=False,
    )
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    adapter.close()

    result = stream_events.run(_RejectUnexpectedEventSink(), Event())

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.CLOSED
    assert configurations == []


def test_feishu_stream_data_callback_normalizes_authenticated_event_and_acks_accepted_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ack_statuses: list[int] = []
    sdk_clients: list[_CallbackSDKClient] = []

    def build_stream_sdk_client(
        config: FeishuLarkAdapterConfig,
        callback: _SDKEventCallback | None = None,
    ) -> _CallbackSDKClient:
        assert config == _config()
        client = _CallbackSDKClient(callback, (_sdk_event(),), ack_statuses)
        sdk_clients.append(client)
        return client

    monkeypatch.setattr(
        feishu_lark_provider,
        "_build_feishu_lark_stream_sdk_client",
        build_stream_sdk_client,
    )
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    before = datetime.now(UTC)

    result = stream_events.run(sink, Event())

    after = datetime.now(UTC)
    assert result is None
    assert ack_statuses == [200]
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.provider is IMProvider.FEISHU
    assert event.provider_tenant_id == "tenant-1"
    assert event.provider_event_id == "evt-1"
    assert event.provider_event_time == datetime.fromtimestamp(1_787_000_000, tz=UTC)
    assert before <= event.received_at <= after
    assert event.provider_event_type == "card.action.trigger"
    assert thaw_json_value(event.provider_payload) == {
        "operator": {"tenant_key": "tenant-1", "open_id": "ou-1"},
        "token": "action-token",
        "action": {"tag": "button", "value": {"decision": "approve"}},
        "context": {"open_message_id": "om-1", "open_chat_id": "oc-1"},
    }
    assert sdk_clients[0].stop_calls == 1
    adapter.close()


def test_feishu_stream_data_callback_maps_retry_sink_to_500_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ack_statuses: list[int] = []

    def build_stream_sdk_client(
        config: FeishuLarkAdapterConfig,
        callback: _SDKEventCallback | None = None,
    ) -> _CallbackSDKClient:
        return _CallbackSDKClient(callback, (_sdk_event(),), ack_statuses)

    monkeypatch.setattr(
        feishu_lark_provider,
        "_build_feishu_lark_stream_sdk_client",
        build_stream_sdk_client,
    )
    sink = _RecordingSink(EventAcceptance.RETRY)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(sink, Event())

    assert result is None
    assert ack_statuses == [500]
    assert len(sink.events) == 1
    adapter.close()


def test_feishu_stream_data_callback_maps_sink_exception_to_500_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ack_statuses: list[int] = []

    def build_stream_sdk_client(
        config: FeishuLarkAdapterConfig,
        callback: _SDKEventCallback | None = None,
    ) -> _CallbackSDKClient:
        return _CallbackSDKClient(callback, (_sdk_event(),), ack_statuses)

    monkeypatch.setattr(
        feishu_lark_provider,
        "_build_feishu_lark_stream_sdk_client",
        build_stream_sdk_client,
    )
    sink = _RecordingSink(EventAcceptance.ACCEPTED, error=RuntimeError("sink failed"))
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None

    result = stream_events.run(sink, Event())

    assert result is None
    assert ack_statuses == [500]
    assert len(sink.events) == 1
    adapter.close()


def test_feishu_control_frame_never_reaches_event_dispatcher_or_emits_data_ack() -> None:
    dispatcher_calls: list[CustomizedEvent] = []
    dispatcher = (
        EventDispatcherHandler.builder("encrypt-test", "verification-test")
        .register_p2_customized_event("card.action.trigger", dispatcher_calls.append)
        .build()
    )
    client = object.__new__(ControlledLarkWebSocketClient)
    client._event_handler = dispatcher
    connection = _RecordingConnection([])
    frame = Frame()
    frame.service = 100
    frame.method = FrameType.CONTROL.value
    frame.SeqID = 1
    frame.LogID = 2
    header = frame.headers.add()
    header.key = HEADER_TYPE
    header.value = MessageType.PING.value

    asyncio.run(client._handle_message(frame.SerializeToString()))

    assert dispatcher_calls == []
    assert connection.sent == []


@pytest.mark.parametrize(
    ("acceptance", "error", "expected_ack"),
    [
        (EventAcceptance.ACCEPTED, None, 200),
        (EventAcceptance.RETRY, None, 500),
        (EventAcceptance.ACCEPTED, RuntimeError("sink failed"), 500),
    ],
    ids=("accepted", "retry", "sink-exception"),
)
def test_feishu_actual_sdk_data_frame_maps_sink_result_to_wire_ack(
    acceptance: EventAcceptance,
    error: Exception | None,
    expected_ack: int,
) -> None:
    sink = _RecordingSink(acceptance, error=error)
    frame = _sdk_data_frame(_sdk_event_payload())

    sent, sent_counts = _run_actual_sdk_frames(sink, (frame,))

    assert sent_counts == [1]
    assert len(sent) == 1
    assert _ack_status(sent[0]) == expected_ack
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.provider is IMProvider.FEISHU
    assert event.provider_tenant_id == "tenant-wire-1"
    assert event.provider_event_id == "evt-wire-1"
    assert event.provider_event_time == datetime.fromtimestamp(1_787_000_000, tz=UTC)
    assert event.provider_event_type == "card.action.trigger"
    assert thaw_json_value(event.provider_payload) == {
        "operator": {"tenant_key": "tenant-wire-1", "open_id": "ou-wire-1"},
        "token": "action-token",
        "action": {"value": {"decision": "approve"}, "tag": "button"},
        "context": {"open_message_id": "om-wire-1", "open_chat_id": "oc-wire-1"},
    }


def test_feishu_actual_sdk_fragmented_data_emits_one_ack_only_after_complete_envelope() -> None:
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    payload = _sdk_event_payload()
    split_at = len(payload) // 2
    frames = (
        _sdk_data_frame(payload[:split_at], fragment_count=2, fragment_index=0),
        _sdk_data_frame(payload[split_at:], fragment_count=2, fragment_index=1),
    )

    sent, sent_counts = _run_actual_sdk_frames(sink, frames)

    assert sent_counts == [0, 1]
    assert len(sent) == 1
    assert _ack_status(sent[0]) == 200
    assert len(sink.events) == 1


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"not-json", id="invalid-json"),
        pytest.param(_sdk_event_payload(schema="1.0"), id="invalid-schema"),
        pytest.param(_sdk_event_payload(token="wrong-token"), id="wrong-token"),
        pytest.param(_sdk_event_payload(app_id="wrong-app"), id="wrong-app"),
        pytest.param(_sdk_event_payload(tenant_key=" "), id="blank-tenant"),
        pytest.param(_sdk_event_payload(event_id=" "), id="blank-event-id"),
        pytest.param(_sdk_event_payload(create_time="invalid"), id="invalid-event-time"),
    ],
)
def test_feishu_actual_sdk_invalid_data_envelope_returns_500_without_sink_delivery(payload: bytes) -> None:
    sink = _RecordingSink(EventAcceptance.ACCEPTED)

    sent, sent_counts = _run_actual_sdk_frames(sink, (_sdk_data_frame(payload),))

    assert sent_counts == [1]
    assert len(sent) == 1
    assert _ack_status(sent[0]) == 500
    assert sink.events == []


def test_feishu_actual_sdk_preserves_absent_provider_event_id_as_none() -> None:
    sink = _RecordingSink(EventAcceptance.ACCEPTED)

    sent, _ = _run_actual_sdk_frames(sink, (_sdk_data_frame(_sdk_event_payload(event_id=None)),))

    assert _ack_status(sent[0]) == 200
    assert len(sink.events) == 1
    assert sink.events[0].provider_event_id is None


def test_feishu_controlled_client_reconnects_after_receive_failure_and_stop_suppresses_further_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections = (_LifecycleConnection(True), _LifecycleConnection(False))
    connect_calls = 0

    async def connect(url: str, *, proxy: None) -> _LifecycleConnection:
        nonlocal connect_calls
        assert proxy is None
        connect_calls += 1
        return connections[connect_calls - 1]

    monkeypatch.setattr(feishu_lark_stream_provider.websockets, "connect", connect)

    async def run() -> None:
        client = create_controlled_lark_websocket_client(
            app_id="cli-test",
            app_secret="secret-test",
            callback=lambda event: None,
            domain="https://open.feishu.cn",
        )
        client._get_conn_url = lambda: "wss://stream.example/ws?device_id=device-1&service_id=100"
        client._reconnect_nonce = 0
        client._reconnect_interval = 0
        client._reconnect_count = 2
        start_task = asyncio.create_task(client.start())
        for _ in range(100):
            if connect_calls == 2:
                break
            await asyncio.sleep(0.001)
        assert connect_calls == 2

        await client.stop()
        await asyncio.wait_for(start_task, timeout=2)
        calls_after_stop = connect_calls
        await asyncio.sleep(0.01)

        assert connect_calls == calls_after_stop
        assert connections[0].close_calls == 1
        assert connections[1].close_calls == 1
        assert client._ping_task is None
        assert client._receive_task is None
        assert client._dispatch_tasks == set()
        client._cache._cron.cancel()
        await asyncio.gather(client._cache._cron, return_exceptions=True)

    asyncio.run(run())


def test_feishu_controlled_client_stop_interrupts_reconnect_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_connection = _LifecycleConnection(True)
    connect_calls = 0

    async def connect(url: str, *, proxy: None) -> _LifecycleConnection:
        nonlocal connect_calls
        assert proxy is None
        connect_calls += 1
        if connect_calls == 1:
            return first_connection
        raise ConnectionError("endpoint unavailable")

    monkeypatch.setattr(feishu_lark_stream_provider.websockets, "connect", connect)

    async def run() -> None:
        client = create_controlled_lark_websocket_client(
            app_id="cli-test",
            app_secret="secret-test",
            callback=lambda event: None,
            domain="https://open.feishu.cn",
        )
        client._get_conn_url = lambda: "wss://stream.example/ws?device_id=device-1&service_id=100"
        client._reconnect_nonce = 0
        client._reconnect_interval = 30
        client._reconnect_count = -1
        start_task = asyncio.create_task(client.start())
        for _ in range(100):
            if connect_calls >= 2:
                break
            await asyncio.sleep(0.001)
        assert connect_calls == 2

        await client.stop()
        await asyncio.wait_for(start_task, timeout=2)
        calls_after_stop = connect_calls
        await asyncio.sleep(0.01)

        assert connect_calls == calls_after_stop
        assert first_connection.close_calls == 1
        client._cache._cron.cancel()
        await asyncio.gather(client._cache._cron, return_exceptions=True)

    asyncio.run(run())


def test_feishu_controlled_client_retries_initial_connect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _LifecycleConnection(False)
    connect_calls = 0

    async def connect(url: str, *, proxy: None) -> _LifecycleConnection:
        nonlocal connect_calls
        assert proxy is None
        connect_calls += 1
        if connect_calls == 1:
            raise ConnectionError("initial connection failed")
        return connection

    monkeypatch.setattr(feishu_lark_stream_provider.websockets, "connect", connect)

    async def run() -> None:
        client = create_controlled_lark_websocket_client(
            app_id="cli-test",
            app_secret="secret-test",
            callback=lambda event: None,
            domain="https://open.feishu.cn",
        )
        client._get_conn_url = lambda: "wss://stream.example/ws?device_id=device-1&service_id=100"
        client._reconnect_nonce = 0
        client._reconnect_interval = 0
        client._reconnect_count = 2
        start_task = asyncio.create_task(client.start())
        try:
            for _ in range(100):
                if connect_calls == 2:
                    break
                await asyncio.sleep(0.001)
            assert connect_calls == 2

            await client.stop()
            await asyncio.wait_for(start_task, timeout=2)

            assert connection.close_calls == 1
            assert client._ping_task is None
            assert client._receive_task is None
            assert client._dispatch_tasks == set()
        finally:
            await _cleanup_controlled_client(client, start_task)

    asyncio.run(run())


def test_feishu_controlled_client_stop_interrupts_initial_connect_retry_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect_calls = 0

    async def connect(url: str, *, proxy: None) -> _LifecycleConnection:
        nonlocal connect_calls
        assert proxy is None
        connect_calls += 1
        raise ConnectionError("endpoint unavailable")

    monkeypatch.setattr(feishu_lark_stream_provider.websockets, "connect", connect)

    async def run() -> None:
        client = create_controlled_lark_websocket_client(
            app_id="cli-test",
            app_secret="secret-test",
            callback=lambda event: None,
            domain="https://open.feishu.cn",
        )
        client._get_conn_url = lambda: "wss://stream.example/ws?device_id=device-1&service_id=100"
        client._reconnect_nonce = 0
        client._reconnect_interval = 30
        client._reconnect_count = -1
        start_task = asyncio.create_task(client.start())
        try:
            for _ in range(100):
                if connect_calls == 1:
                    break
                await asyncio.sleep(0.001)
            assert connect_calls == 1
            assert not start_task.done()

            await client.stop()
            await asyncio.wait_for(start_task, timeout=2)
            calls_after_stop = connect_calls
            await asyncio.sleep(0.01)

            assert connect_calls == calls_after_stop
        finally:
            await _cleanup_controlled_client(client, start_task)

    asyncio.run(run())


def test_feishu_controlled_client_reconnects_after_ping_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections = (_LifecycleConnection(False, fail_send=True), _LifecycleConnection(False))
    connect_calls = 0

    async def connect(url: str, *, proxy: None) -> _LifecycleConnection:
        nonlocal connect_calls
        assert proxy is None
        connect_calls += 1
        return connections[connect_calls - 1]

    monkeypatch.setattr(feishu_lark_stream_provider.websockets, "connect", connect)

    async def run() -> None:
        client = create_controlled_lark_websocket_client(
            app_id="cli-test",
            app_secret="secret-test",
            callback=lambda event: None,
            domain="https://open.feishu.cn",
        )
        client._get_conn_url = lambda: "wss://stream.example/ws?device_id=device-1&service_id=100"
        client._ping_interval = 30
        client._reconnect_nonce = 0
        client._reconnect_interval = 0
        client._reconnect_count = 2
        start_task = asyncio.create_task(client.start())
        try:
            for _ in range(100):
                if connections[0].send_attempted.is_set():
                    break
                await asyncio.sleep(0.001)
            assert connections[0].send_attempted.is_set()
            for _ in range(100):
                if connect_calls == 2:
                    break
                await asyncio.sleep(0.001)
            assert connect_calls == 2

            await client.stop()
            await asyncio.wait_for(start_task, timeout=2)

            assert connections[0].close_calls == 1
            assert connections[1].close_calls == 1
            assert client._ping_task is None
            assert client._receive_task is None
            assert client._dispatch_tasks == set()
        finally:
            await _cleanup_controlled_client(client, start_task)

    asyncio.run(run())


def test_feishu_stream_stop_waits_for_active_callback_before_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _OneFrameLifecycleConnection(
        _sdk_data_frame(_sdk_event_payload()).SerializeToString(),
    )
    clients: list[ControlledLarkWebSocketClient] = []

    async def connect(url: str, *, proxy: None) -> _OneFrameLifecycleConnection:
        assert proxy is None
        return connection

    def build_stream_sdk_client(
        config: FeishuLarkAdapterConfig,
        callback: _SDKEventCallback,
    ) -> ControlledLarkWebSocketClient:
        client = create_controlled_lark_websocket_client(
            app_id=config.app_id,
            app_secret=config.app_secret,
            callback=callback,
            domain="https://open.feishu.cn",
        )
        client._get_conn_url = lambda: "wss://stream.example/ws?device_id=device-1&service_id=100"
        client._ping_interval = 30
        clients.append(client)
        return client

    monkeypatch.setattr(feishu_lark_stream_provider.websockets, "connect", connect)
    monkeypatch.setattr(feishu_lark_provider, "_build_feishu_lark_stream_sdk_client", build_stream_sdk_client)
    callback_started = Event()
    callback_release = Event()
    callback_completed = Event()
    sink = _BlockingRecordingSink(callback_started, callback_release, callback_completed)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    results: list[OperationFailure | None] = []
    thread = Thread(target=lambda: results.append(stream_events.run(sink, stop)), daemon=True)
    thread.start()

    try:
        assert callback_started.wait(timeout=2)
        stop.set()
        thread.join(timeout=0.05)

        assert thread.is_alive()
        assert not callback_completed.is_set()
    finally:
        callback_release.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert callback_completed.is_set()
    assert results == [None]
    assert len(sink.events) == 1
    assert _ack_status(connection.sent[-1]) == 200
    assert connection.close_calls == 1
    assert len(clients) == 1
    assert clients[0]._ping_task is None
    assert clients[0]._receive_task is None
    assert clients[0]._dispatch_tasks == set()
    adapter.close()


def test_feishu_stream_rejects_concurrent_run_and_external_stop_returns_boundedly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _BlockingSDKClient(Event(), Event())
    monkeypatch.setattr(
        feishu_lark_provider,
        "_build_feishu_lark_stream_sdk_client",
        lambda config, callback: sdk_client,
    )
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    stop = Event()
    first_results: list[OperationFailure | None] = []
    thread = Thread(target=lambda: first_results.append(stream_events.run(_RejectUnexpectedEventSink(), stop)))
    thread.start()
    assert sdk_client.started.wait(timeout=2)

    concurrent_result = stream_events.run(_RejectUnexpectedEventSink(), Event())
    stop.set()
    thread.join(timeout=2)

    assert isinstance(concurrent_result, OperationFailure)
    assert concurrent_result.code is OperationFailureCode.PROVIDER
    assert not thread.is_alive()
    assert first_results == [None]
    assert sdk_client.stop_calls == 1
    adapter.close()
