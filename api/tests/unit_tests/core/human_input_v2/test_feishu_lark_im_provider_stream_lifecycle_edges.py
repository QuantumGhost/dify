"""Focused edge contracts for the controlled Feishu/Lark STREAM lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Thread
from typing import cast, override

import pytest
from lark_oapi.core.const import FEISHU_DOMAIN, LARK_DOMAIN
from lark_oapi.event.custom import CustomizedEvent
from lark_oapi.ws.exception import ConnectionClosedException

import core.human_input_v2.im_provider.providers.feishu_lark as feishu_lark_provider
import core.human_input_v2.im_provider.providers.feishu_lark_stream as feishu_lark_stream_provider
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AdapterCloseError,
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


def _config(provider: IMProvider = IMProvider.FEISHU) -> FeishuLarkAdapterConfig:
    return FeishuLarkAdapterConfig(
        provider=provider,
        app_id="cli-test",
        app_secret="secret-test",
        verification_token="verification-test",
        encrypt_key="encrypt-test",
    )


def _client() -> ControlledLarkWebSocketClient:
    return feishu_lark_stream_provider.create_controlled_lark_websocket_client(
        app_id="cli-test",
        app_secret="secret-test",
        callback=lambda event: None,
        domain=FEISHU_DOMAIN,
    )


async def _cancel_cache_tasks(*clients: ControlledLarkWebSocketClient) -> None:
    for client in clients:
        client._cache._cron.cancel()
    await asyncio.gather(*(client._cache._cron for client in clients), return_exceptions=True)


@dataclass(slots=True)
class _Connection:
    close_calls: int = 0
    closed: asyncio.Event | None = None

    async def recv(self) -> bytes:
        if self.closed is None:
            self.closed = asyncio.Event()
        await self.closed.wait()
        raise ConnectionError("connection closed")

    async def send(self, data: bytes) -> None:
        return None

    async def close(self) -> None:
        self.close_calls += 1
        if self.closed is not None:
            self.closed.set()


@dataclass(slots=True)
class _BlockingClient:
    started: Event
    stopped: Event
    stop_calls: int = 0

    async def start(self) -> None:
        self.started.set()
        await asyncio.to_thread(self.stopped.wait)

    async def stop(self) -> None:
        self.stop_calls += 1
        self.stopped.set()


@dataclass(slots=True)
class _BlockingStartClient:
    start_entered: Event
    start_release: Event
    stopped: Event
    stop_calls: int = 0
    loop_errors: list[dict[str, object]] | None = None

    async def start(self) -> None:
        self.loop_errors = []
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: self.loop_errors.append(context) if self.loop_errors is not None else None
        )
        self.start_entered.set()
        await asyncio.to_thread(self.start_release.wait)
        await asyncio.to_thread(self.stopped.wait)

    async def stop(self) -> None:
        self.stop_calls += 1
        self.stopped.set()


@dataclass(slots=True)
class _FailingStartClient:
    adapter: FeishuLarkAdapter | None = None
    start_calls: int = 0
    stop_calls: int = 0
    stop_failures_remaining: int = 1
    close_errors: list[AdapterCloseError] | None = None
    loop_errors: list[dict[str, object]] | None = None

    async def start(self) -> None:
        self.start_calls += 1
        self.loop_errors = []
        self.close_errors = []
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: self.loop_errors.append(context) if self.loop_errors is not None else None
        )
        assert self.adapter is not None
        try:
            self.adapter.close()
        except AdapterCloseError as error:
            self.close_errors.append(error)
        else:
            raise AssertionError("adapter close returned before the starting client was published")
        raise RuntimeError("stream start failed")

    async def stop(self) -> None:
        self.stop_calls += 1
        if self.stop_failures_remaining > 0:
            self.stop_failures_remaining -= 1
            raise RuntimeError("raw SDK stop failure")


@dataclass(slots=True)
class _SameLoopCloseClient:
    started: Event
    stopped: asyncio.Event | None = None
    callback: Callable[[CustomizedEvent], None] | None = None
    stop_calls: int = 0
    stop_failures_remaining: int = 0
    callback_retries: int = 0
    loop_errors: list[dict[str, object]] | None = None

    async def start(self) -> None:
        self.stopped = asyncio.Event()
        self.loop_errors = []
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: self.loop_errors.append(context) if self.loop_errors is not None else None
        )
        self.started.set()
        assert self.callback is not None
        try:
            self.callback(
                CustomizedEvent(
                    {
                        "schema": "2.0",
                        "header": {
                            "event_id": "evt-close",
                            "token": "verification-test",
                            "event_type": "card.action.trigger",
                            "tenant_key": "tenant-close",
                            "app_id": "cli-test",
                        },
                        "event": {"message_id": "message-close"},
                    }
                )
            )
        except feishu_lark_provider._FeishuLarkStreamRetryRequestedError:
            self.callback_retries += 1
        await self.stopped.wait()
        await asyncio.sleep(0)

    async def stop(self) -> None:
        self.stop_calls += 1
        assert self.stopped is not None
        self.stopped.set()
        if self.stop_failures_remaining > 0:
            self.stop_failures_remaining -= 1
            raise RuntimeError("raw SDK stop failure")


@dataclass(slots=True)
class _AcceptingSink(IMEventSink):
    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        return EventAcceptance.ACCEPTED


@dataclass(slots=True)
class _CloseFromFeishuSink(IMEventSink):
    adapter: FeishuLarkAdapter
    close_errors: list[AdapterCloseError]

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        try:
            self.adapter.close()
        except AdapterCloseError as error:
            self.close_errors.append(error)
            raise
        raise AssertionError("same-loop adapter.close() returned before cleanup completed")


def _close_in_thread(adapter: FeishuLarkAdapter) -> tuple[Thread, Event, list[AdapterCloseError], list[None]]:
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


def test_controlled_client_prestart_stop_is_terminal_and_unstarted_guards_are_typed() -> None:
    async def run() -> None:
        terminal_client = _client()
        guarded_client = _client()
        await terminal_client.stop()
        await terminal_client.start()

        with pytest.raises(RuntimeError, match="cannot be restarted"):
            await terminal_client.start()
        with pytest.raises(ConnectionClosedException, match="reconnect lifecycle was not started"):
            await guarded_client._reconnect_owned()
        with pytest.raises(ConnectionClosedException, match="lifecycle was not started"):
            await guarded_client._wait_for_stop(0)

        guarded_client._stopping = True
        guarded_client._lock = asyncio.Lock()
        await guarded_client._connect_owned()
        await _cancel_cache_tasks(terminal_client, guarded_client)

    asyncio.run(run())


def test_controlled_client_stop_timeout_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        client = _client()
        client._lock = asyncio.Lock()
        client._stop_requested = asyncio.Event()
        client._stopped = asyncio.Event()
        monkeypatch.setattr(feishu_lark_stream_provider, "_STOP_TIMEOUT_SECONDS", 0)

        with pytest.raises(RuntimeError, match="did not stop before the deadline"):
            await client.stop()

        await _cancel_cache_tasks(client)

    asyncio.run(run())


def test_controlled_client_late_connection_is_closed_without_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        client = _client()
        connection = _Connection()
        client._lock = asyncio.Lock()
        client._get_conn_url = lambda: "wss://stream.example/ws?device_id=device-1&service_id=100"

        async def connect(url: str, *, proxy: None) -> _Connection:
            client._stopping = True
            return connection

        monkeypatch.setattr(feishu_lark_stream_provider.websockets, "connect", connect)

        await client._connect_owned()

        assert connection.close_calls == 1
        assert client._conn is None
        await _cancel_cache_tasks(client)

    asyncio.run(run())


@pytest.mark.parametrize("terminal_loop", ["ping", "receive"])
def test_controlled_client_propagates_owned_terminal_loop_and_cancels_peer(
    monkeypatch: pytest.MonkeyPatch,
    terminal_loop: str,
) -> None:
    async def run() -> None:
        client = _client()
        connection = _Connection()
        peer_cancelled = asyncio.Event()

        async def connect_owned(instance: ControlledLarkWebSocketClient) -> None:
            instance._conn = cast(object, connection)  # type: ignore[assignment]
            instance._service_id = "100"

        async def terminal(instance: ControlledLarkWebSocketClient) -> None:
            return None

        async def peer(instance: ControlledLarkWebSocketClient) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                peer_cancelled.set()
                raise

        monkeypatch.setattr(ControlledLarkWebSocketClient, "_connect_owned", connect_owned)
        if terminal_loop == "ping":
            monkeypatch.setattr(ControlledLarkWebSocketClient, "_ping_loop_owned", terminal)
            monkeypatch.setattr(ControlledLarkWebSocketClient, "_receive_loop_owned", peer)
        else:
            monkeypatch.setattr(ControlledLarkWebSocketClient, "_ping_loop_owned", peer)
            monkeypatch.setattr(ControlledLarkWebSocketClient, "_receive_loop_owned", terminal)

        await client.start()

        assert peer_cancelled.is_set()
        assert connection.close_calls == 1
        assert client._dispatch_tasks == set()
        await _cancel_cache_tasks(client)

    asyncio.run(run())


@pytest.mark.parametrize("connect_outcome", ["no_connection", "cancelled"])
def test_controlled_client_handles_initial_connect_terminal_outcome(
    monkeypatch: pytest.MonkeyPatch,
    connect_outcome: str,
) -> None:
    async def run() -> None:
        client = _client()

        async def connect_owned(instance: ControlledLarkWebSocketClient) -> None:
            if connect_outcome == "cancelled":
                raise asyncio.CancelledError

        monkeypatch.setattr(ControlledLarkWebSocketClient, "_connect_owned", connect_owned)

        if connect_outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await client.start()
        else:
            await client.start()

        await _cancel_cache_tasks(client)

    asyncio.run(run())


def test_controlled_client_reconnect_stop_and_cancellation_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        jitter_client = _client()
        backoff_client = _client()
        retry_stop_client = _client()
        cancelled_client = _client()
        for client in (jitter_client, backoff_client, retry_stop_client, cancelled_client):
            client._reconnect_lock = asyncio.Lock()
            client._stop_requested = asyncio.Event()
            client._reconnect_count = -1
            client._conn = None

        jitter_client._reconnect_nonce = 1
        jitter_client._stop_requested.set()
        await jitter_client._reconnect_owned()

        backoff_client._reconnect_nonce = 0
        backoff_client._stop_requested.set()
        await backoff_client._reconnect_owned(wait_before_first_attempt=True)

        async def fail_connect() -> None:
            raise ConnectionError("connection failed")

        retry_stop_client._reconnect_nonce = 0
        retry_stop_client._stop_requested.set()
        monkeypatch.setattr(retry_stop_client, "_connect_owned", fail_connect)
        await retry_stop_client._reconnect_owned()

        async def cancel_connect() -> None:
            raise asyncio.CancelledError

        cancelled_client._reconnect_nonce = 0
        monkeypatch.setattr(cancelled_client, "_connect_owned", cancel_connect)
        with pytest.raises(asyncio.CancelledError):
            await cancelled_client._reconnect_owned()

        await _cancel_cache_tasks(jitter_client, backoff_client, retry_stop_client, cancelled_client)

    asyncio.run(run())


def test_feishu_stream_listener_covers_missing_header_optional_time_and_nested_list() -> None:
    events: list[AuthenticatedIMEvent] = []
    listener = feishu_lark_provider._FeishuLarkStreamEventListener(
        _config(),
        lambda event: events.append(event) or EventAcceptance.ACCEPTED,
    )

    listener(
        CustomizedEvent(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-1",
                    "token": "verification-test",
                    "event_type": "card.action.trigger",
                    "tenant_key": "tenant-1",
                    "app_id": "cli-test",
                },
                "event": {"roles": ["admin", "reviewer"]},
            }
        )
    )

    with pytest.raises(ValueError, match="header"):
        listener(CustomizedEvent({"schema": "2.0", "event": {}}))

    assert len(events) == 1
    assert events[0].provider_event_time is None
    assert thaw_json_value(events[0].provider_payload) == {"roles": ["admin", "reviewer"]}


def test_feishu_stream_builder_selects_provider_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = cast(feishu_lark_provider._FeishuLarkStreamSDKClient, object())
    construction_options: list[tuple[str, str, str]] = []

    def create_client(
        app_id: str,
        app_secret: str,
        callback: object,
        *,
        domain: str,
    ) -> feishu_lark_provider._FeishuLarkStreamSDKClient:
        construction_options.append((app_id, app_secret, domain))
        return sentinel

    monkeypatch.setattr(feishu_lark_stream_provider, "create_controlled_lark_websocket_client", create_client)

    feishu_client = feishu_lark_provider._build_feishu_lark_stream_sdk_client(_config(), lambda event: None)
    lark_client = feishu_lark_provider._build_feishu_lark_stream_sdk_client(
        _config(IMProvider.LARK),
        lambda event: None,
    )

    assert feishu_client is sentinel
    assert lark_client is sentinel
    assert construction_options == [
        ("cli-test", "secret-test", FEISHU_DOMAIN),
        ("cli-test", "secret-test", LARK_DOMAIN),
    ]


def test_feishu_stream_external_close_waits_for_active_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _BlockingClient(Event(), Event())
    monkeypatch.setattr(
        feishu_lark_provider,
        "_build_feishu_lark_stream_sdk_client",
        lambda config, callback: sdk_client,
    )
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    results: list[OperationFailure | None] = []
    thread = Thread(target=lambda: results.append(stream_events.run(_AcceptingSink(), Event())))
    thread.start()
    assert sdk_client.started.wait(timeout=2)

    adapter.close()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert results == [None]
    assert sdk_client.stop_calls >= 1


def test_feishu_close_during_blocked_stream_build_is_retryable_without_deadlock_or_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_started = Event()
    build_release = Event()
    sdk_client = _BlockingClient(Event(), Event())
    build_count = 0

    def build_client(
        config: FeishuLarkAdapterConfig,
        callback: Callable[[CustomizedEvent], None],
    ) -> _BlockingClient:
        nonlocal build_count
        del callback
        assert config == _config()
        build_count += 1
        build_started.set()
        assert build_release.wait(timeout=2)
        return sdk_client

    monkeypatch.setattr(feishu_lark_provider, "_build_feishu_lark_stream_sdk_client", build_client)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    results: list[OperationFailure | None] = []
    run_thread = Thread(
        target=lambda: results.append(stream_events.run(_AcceptingSink(), Event())),
        daemon=True,
    )
    run_thread.start()
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
    assert close_errors[0].provider is IMProvider.FEISHU
    assert close_returns == []
    assert results == [None]
    assert build_count == 1
    assert sdk_client.stop_calls >= 1

    rerun = stream_events.run(_AcceptingSink(), Event())
    assert isinstance(rerun, OperationFailure)
    assert rerun.code is OperationFailureCode.CLOSED
    assert build_count == 1
    adapter.close()


def test_feishu_close_during_blocked_start_is_retryable_without_deadlock_or_unobserved_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _BlockingStartClient(Event(), Event(), Event())
    build_count = 0

    def build_client(
        config: FeishuLarkAdapterConfig,
        callback: Callable[[CustomizedEvent], None],
    ) -> _BlockingStartClient:
        nonlocal build_count
        del callback
        assert config == _config()
        build_count += 1
        return sdk_client

    monkeypatch.setattr(feishu_lark_provider, "_build_feishu_lark_stream_sdk_client", build_client)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    results: list[OperationFailure | None] = []
    run_thread = Thread(
        target=lambda: results.append(stream_events.run(_AcceptingSink(), Event())),
        daemon=True,
    )
    run_thread.start()
    assert sdk_client.start_entered.wait(timeout=2)
    close_thread, close_finished, close_errors, close_returns = _close_in_thread(adapter)

    try:
        close_finished_before_release = close_finished.wait(timeout=2)
    finally:
        sdk_client.start_release.set()
    close_thread.join(timeout=2)
    run_thread.join(timeout=2)

    assert close_finished_before_release
    assert not close_thread.is_alive()
    assert not run_thread.is_alive()
    assert len(close_errors) == 1
    assert close_errors[0].provider is IMProvider.FEISHU
    assert close_returns == []
    assert results == [None]
    assert build_count == 1
    assert sdk_client.stop_calls >= 1
    assert sdk_client.loop_errors == []
    adapter.close()


def test_feishu_start_failure_retains_published_client_until_cleanup_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _FailingStartClient()
    build_count = 0

    def build_client(
        config: FeishuLarkAdapterConfig,
        callback: Callable[[CustomizedEvent], None],
    ) -> _FailingStartClient:
        nonlocal build_count
        del callback
        assert config == _config()
        build_count += 1
        return sdk_client

    monkeypatch.setattr(feishu_lark_provider, "_build_feishu_lark_stream_sdk_client", build_client)
    adapter = FeishuLarkAdapter(_config())
    sdk_client.adapter = adapter
    stream_events = adapter.stream_events
    assert stream_events is not None

    first_result = stream_events.run(_AcceptingSink(), Event())
    rerun = stream_events.run(_AcceptingSink(), Event())

    assert isinstance(first_result, OperationFailure)
    assert first_result.code is OperationFailureCode.PROVIDER
    assert isinstance(rerun, OperationFailure)
    assert rerun.code is OperationFailureCode.CLOSED
    assert build_count == 1
    assert sdk_client.start_calls == 1
    assert sdk_client.stop_calls == 1
    assert sdk_client.close_errors is not None
    assert len(sdk_client.close_errors) == 1
    assert sdk_client.close_errors[0].provider is IMProvider.FEISHU
    assert sdk_client.loop_errors == []

    adapter.close()
    assert sdk_client.stop_calls == 2


def test_feishu_same_loop_close_is_retryable_without_deadlock_or_unobserved_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _SameLoopCloseClient(Event())
    built_configs: list[FeishuLarkAdapterConfig] = []

    def build_client(
        config: FeishuLarkAdapterConfig,
        callback: Callable[[CustomizedEvent], None],
    ) -> _SameLoopCloseClient:
        built_configs.append(config)
        sdk_client.callback = callback
        return sdk_client

    monkeypatch.setattr(feishu_lark_provider, "_build_feishu_lark_stream_sdk_client", build_client)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    close_errors: list[AdapterCloseError] = []
    results: list[OperationFailure | None] = []
    thread = Thread(
        target=lambda: results.append(stream_events.run(_CloseFromFeishuSink(adapter, close_errors), Event())),
        daemon=True,
    )

    thread.start()
    assert sdk_client.started.wait(timeout=2)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert len(close_errors) == 1
    assert close_errors[0].provider is IMProvider.FEISHU
    assert sdk_client.callback_retries == 1
    assert results == [None]
    assert sdk_client.loop_errors == []

    adapter.close()
    adapter.close()
    adapter.close()

    assert built_configs == [_config()]
    assert sdk_client.stop_calls >= 1


def test_feishu_same_loop_stop_failure_remains_available_for_external_close_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_client = _SameLoopCloseClient(Event(), stop_failures_remaining=2)
    build_count = 0

    def build_client(
        config: FeishuLarkAdapterConfig,
        callback: Callable[[CustomizedEvent], None],
    ) -> _SameLoopCloseClient:
        nonlocal build_count
        build_count += 1
        sdk_client.callback = callback
        return sdk_client

    monkeypatch.setattr(feishu_lark_provider, "_build_feishu_lark_stream_sdk_client", build_client)
    adapter = FeishuLarkAdapter(_config())
    stream_events = adapter.stream_events
    assert stream_events is not None
    close_errors: list[AdapterCloseError] = []
    results: list[OperationFailure | None] = []
    thread = Thread(
        target=lambda: results.append(stream_events.run(_CloseFromFeishuSink(adapter, close_errors), Event())),
        daemon=True,
    )

    thread.start()
    assert sdk_client.started.wait(timeout=2)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert len(close_errors) == 1
    assert len(results) == 1
    assert isinstance(results[0], OperationFailure)
    assert results[0].code is OperationFailureCode.PROVIDER
    assert sdk_client.loop_errors == []

    with pytest.raises(AdapterCloseError):
        adapter.close()
    adapter.close()
    adapter.close()

    assert build_count == 1
    assert sdk_client.stop_failures_remaining == 0
