"""Controlled Feishu/Lark WebSocket lifecycle fork.

This narrow fork derives from ``lark-oapi==1.7.1`` ``lark_oapi/ws/client.py``
at upstream tag commit ``2cecb91d7cacd074667c8ddbf15488a0a70bd110``:
https://github.com/larksuite/oapi-sdk-python/blob/v1.7.1/lark_oapi/ws/client.py

Connection lifecycle is replaced while event registration uses the SDK's exact
``register_p2_card_action_trigger`` callback. Endpoint discovery,
protobuf frames, control/data decoding, and DATA ACK encoding remain supplied
by the exact pinned SDK. The upstream synchronous ``start()`` owns a
module-global event loop and has no public stop operation; this fork instead
owns per-instance tasks and a bounded public ``stop()`` that suppresses
reconnect before disconnecting. The callback exception contract is retained
because the pinned DATA handler maps normal return to 200 and exceptions to 500.

This fork intentionally depends on pinned private SDK fields and methods,
including connection/configuration state plus ``_get_conn_url()``,
``_handle_message()`` and ``_write_message()``. Upgrading ``lark-oapi`` requires
diffing those boundaries against the pinned source before changing the version.
The synchronous endpoint request inside ``_get_conn_url()`` runs through
``asyncio.to_thread()`` so it cannot block the lifecycle loop; Python cannot
cancel the worker thread itself, so stop suppresses publication and reconnect
from a late result while its bounded deadline remains the caller-visible limit.

MIT License

Copyright (c) 2023 Lark Technologies Pte. Ltd.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol, cast
from urllib.parse import parse_qs, urlparse

import websockets
from lark_oapi.core.const import FEISHU_DOMAIN  # type: ignore[import-untyped]
from lark_oapi.core.enum import LogLevel  # type: ignore[import-untyped]
from lark_oapi.event.callback.model.p2_card_action_trigger import (  # type: ignore[import-untyped]
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler  # type: ignore[import-untyped]
from lark_oapi.ws.client import Client as UpstreamWebSocketClient  # type: ignore[import-untyped]
from lark_oapi.ws.const import DEVICE_ID, HEADER_TYPE, SERVICE_ID  # type: ignore[import-untyped]
from lark_oapi.ws.enum import FrameType, MessageType  # type: ignore[import-untyped]
from lark_oapi.ws.exception import (  # type: ignore[import-untyped]
    ConnectionClosedException,
    ServerUnreachableException,
)
from lark_oapi.ws.pb.pbbp2_pb2 import Frame  # type: ignore[import-untyped]

_STOP_TIMEOUT_SECONDS = 10.0


class _WebSocketConnection(Protocol):
    async def recv(self) -> bytes: ...

    async def send(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class _SerializableFrame(Protocol):
    def SerializeToString(self) -> bytes: ...  # noqa: N802 - third-party protobuf API


def _ping_frame(service_id: int) -> _SerializableFrame:
    frame = Frame()
    header = frame.headers.add()
    header.key = HEADER_TYPE
    header.value = MessageType.PING.value
    frame.service = service_id
    frame.method = FrameType.CONTROL.value
    frame.SeqID = 0
    frame.LogID = 0
    return cast(_SerializableFrame, frame)


class ControlledLarkWebSocketClient(UpstreamWebSocketClient):
    """Pinned SDK protocol implementation with an owned, stoppable lifecycle."""

    _lifecycle_loop: asyncio.AbstractEventLoop | None
    _stop_requested: asyncio.Event | None
    _stopped: asyncio.Event | None
    _reconnect_lock: asyncio.Lock | None
    _ping_task: asyncio.Task[None] | None
    _receive_task: asyncio.Task[None] | None
    _dispatch_tasks: set[asyncio.Task[None]]
    _started: bool
    _stopping: bool
    _stop_before_start: bool

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        event_handler: EventDispatcherHandler,
        domain: str = FEISHU_DOMAIN,
        log_level: LogLevel = LogLevel.INFO,
    ) -> None:
        super().__init__(
            app_id=app_id,
            app_secret=app_secret,
            log_level=log_level,
            event_handler=event_handler,
            domain=domain,
            auto_reconnect=False,
        )
        self._lifecycle_loop = None
        self._stop_requested = None
        self._stopped = None
        self._reconnect_lock = None
        self._ping_task = None
        self._receive_task = None
        self._dispatch_tasks = set()
        self._started = False
        self._stopping = False
        self._stop_before_start = False

    async def start(self) -> None:  # type: ignore[override]
        """Connect and run until ``stop`` completes this client's lifecycle."""
        if self._started:
            raise RuntimeError("Feishu/Lark STREAM client cannot be restarted")
        self._started = True
        if self._stop_before_start:
            return

        self._lifecycle_loop = asyncio.get_running_loop()
        self._lock = asyncio.Lock()
        self._reconnect_lock = asyncio.Lock()
        self._stop_requested = asyncio.Event()
        self._stopped = asyncio.Event()
        stop_wait_task: asyncio.Task[bool] | None = None
        try:
            try:
                await self._connect_owned()
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._reconnect_owned(wait_before_first_attempt=True)
            if self._stopping or self._conn is None:
                return
            self._ping_task = asyncio.create_task(self._ping_loop_owned())
            self._receive_task = asyncio.create_task(self._receive_loop_owned())
            stop_wait_task = asyncio.create_task(self._stop_requested.wait())
            done, _ = await asyncio.wait(
                (stop_wait_task, self._ping_task, self._receive_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_wait_task in done:
                return
            if self._ping_task in done:
                await self._ping_task
            if self._receive_task in done:
                await self._receive_task
        finally:
            self._stopping = True
            if self._stop_requested is not None:
                self._stop_requested.set()
            if stop_wait_task is not None:
                stop_wait_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stop_wait_task
            await self._shutdown_owned()
            if self._stopped is not None:
                self._stopped.set()
            self._lifecycle_loop = None
            self._reconnect_lock = None

    async def stop(self) -> None:
        """Suppress reconnect, disconnect, and await all owned tasks boundedly."""
        self._stopping = True
        if self._stop_requested is None or self._stopped is None:
            self._stop_before_start = True
            return
        self._stop_requested.set()
        await self._disconnect_owned()
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=_STOP_TIMEOUT_SECONDS)
        except TimeoutError as error:
            raise RuntimeError("Feishu/Lark STREAM client did not stop before the deadline") from error

    async def _connect_owned(self) -> None:
        if self._stopping:
            return
        connection_url = await asyncio.to_thread(self._get_conn_url)
        parsed_url = urlparse(connection_url)
        query = parse_qs(parsed_url.query)
        connection_id = query[DEVICE_ID][0]
        service_id = query[SERVICE_ID][0]
        connection = cast(
            _WebSocketConnection,
            await websockets.connect(connection_url, proxy=None),
        )
        async with self._lock:
            if self._stopping:
                await connection.close()
                return
            self._conn = connection  # type: ignore[assignment]
            self._conn_url = connection_url
            self._conn_id = connection_id
            self._service_id = service_id

    async def _receive_loop_owned(self) -> None:
        while not self._stopping:
            connection = cast(_WebSocketConnection | None, self._conn)
            if connection is None:
                await self._reconnect_owned()
                continue
            try:
                message = await connection.recv()
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._disconnect_owned(connection)
                if not self._stopping:
                    await self._reconnect_owned()
                continue
            dispatch_task = asyncio.create_task(self._handle_message(message))
            self._dispatch_tasks.add(dispatch_task)
            dispatch_task.add_done_callback(self._dispatch_tasks.discard)

    async def _ping_loop_owned(self) -> None:
        while not self._stopping:
            connection = cast(_WebSocketConnection | None, self._conn)
            if connection is not None:
                try:
                    frame = _ping_frame(int(self._service_id))
                    await self._write_message(frame.SerializeToString())
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await self._disconnect_owned(connection)
                    if not self._stopping:
                        await self._reconnect_owned()
                    continue
            if await self._wait_for_stop(self._ping_interval):
                return

    async def _reconnect_owned(self, *, wait_before_first_attempt: bool = False) -> None:
        reconnect_lock = self._reconnect_lock
        if reconnect_lock is None:
            raise ConnectionClosedException("Feishu/Lark STREAM reconnect lifecycle was not started")
        async with reconnect_lock:
            if self._stopping or self._conn is not None:
                return
            reconnect_jitter = secrets.randbelow(1_000_000) / 1_000_000 * self._reconnect_nonce
            if self._reconnect_nonce > 0 and await self._wait_for_stop(reconnect_jitter):
                return
            if wait_before_first_attempt and await self._wait_for_stop(self._reconnect_interval):
                return
            attempt = 0
            while not self._stopping:
                if self._reconnect_count >= 0 and attempt >= self._reconnect_count:
                    raise ServerUnreachableException(
                        f"unable to connect to the server after trying {self._reconnect_count} times"
                    )
                try:
                    await self._connect_owned()
                    if self._conn is not None:
                        return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    attempt += 1
                    if await self._wait_for_stop(self._reconnect_interval):
                        return

    async def _disconnect_owned(self, expected_connection: _WebSocketConnection | None = None) -> None:
        async with self._lock:
            connection = cast(_WebSocketConnection | None, self._conn)
            if expected_connection is not None and connection is not expected_connection:
                return
            self._conn = None  # type: ignore[assignment]
            self._conn_url = ""
            self._conn_id = ""
            self._service_id = ""
        if connection is not None:
            await connection.close()

    async def _shutdown_owned(self) -> None:
        current_task = asyncio.current_task()
        tasks = [self._ping_task, self._receive_task, *self._dispatch_tasks]
        pending_tasks = [task for task in tasks if task is not None and task is not current_task and not task.done()]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        await self._disconnect_owned()
        self._ping_task = None
        self._receive_task = None
        self._dispatch_tasks.clear()

    async def _wait_for_stop(self, delay_seconds: float) -> bool:
        stop_requested = self._stop_requested
        if stop_requested is None:
            raise ConnectionClosedException("Feishu/Lark STREAM lifecycle was not started")
        try:
            await asyncio.wait_for(stop_requested.wait(), timeout=delay_seconds)
        except TimeoutError:
            return False
        return True


def create_controlled_lark_websocket_client(
    app_id: str,
    app_secret: str,
    callback: Callable[[P2CardActionTrigger], P2CardActionTriggerResponse],
    *,
    domain: str,
) -> ControlledLarkWebSocketClient:
    """Construct the pinned client with the exact official card-action callback."""
    event_handler = (
        EventDispatcherHandler.builder(encrypt_key="", verification_token="")
        .register_p2_card_action_trigger(callback)
        .build()
    )
    return ControlledLarkWebSocketClient(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=event_handler,
        domain=domain,
    )
