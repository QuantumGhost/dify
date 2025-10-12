import dataclasses
import logging
import queue
import threading
import types
from collections.abc import Generator, Iterator

from redis import Redis
from redis.client import PubSub

from libs.broadcast_channel.channel import Overflow, Producer, Subscriber, Subscription
from libs.broadcast_channel.exc import InvalidOperationError

_logger = logging.getLogger(__name__)


class BroadcastChannel:
    """
    Redis Pub/Sub based broadcast channel implementation.

    Provides "at most once" delivery semantics for messages published to channels.
    Uses Redis PUBLISH/SUBSCRIBE commands for real-time message delivery.
    """

    def __init__(
        self,
        redis_client: Redis,
    ):
        self._client = redis_client

    def topic(self, topic: str) -> "Topic":
        return Topic(self._client, topic)


class Topic:
    def __init__(self, redis_client: Redis, topic: str):
        self._client = redis_client
        self._topic = topic

    def as_producer(self) -> Producer:
        return self

    def publish(self, payload: bytes) -> None:
        self._client.publish(self._topic, payload)

    def as_subscriber(self) -> Subscriber:
        return self

    def subscribe(
        self,
        *,
        buffer: int = 1024,
        overflow: Overflow = Overflow.DROP_OLDEST,
    ) -> Subscription:
        if buffer <= 0:
            raise ValueError("buffer must be a positive integer")
        return _RedisSubscription(
            pubsub=self._client.pubsub(),
            topic=self._topic,
            buffer_size=buffer,
            overflow=overflow,
        )


@dataclasses.dataclass(frozen=True)
class _Stop:
    pass


_STOP = _Stop()


class _RedisSubscription(Subscription):
    def __init__(
        self,
        pubsub: PubSub,
        topic: str,
        *,
        buffer_size: int,
        overflow: Overflow,
    ):
        # The _pubsub is Noen only if the subscription is closed.
        self._pubsub: PubSub | None = pubsub
        self._topic = topic
        self._buffer_size = buffer_size
        self._overflow = overflow
        self._closed = threading.Event()
        self._queue: queue.Queue[bytes | _Stop] = queue.Queue(maxsize=buffer_size)
        self._iter_gen: Generator[bytes, None, None] | None = None
        self._listener_thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._started = False

    def _start_if_needed(self) -> None:
        with self._start_lock:
            if self._started:
                return
            if self._closed.is_set():
                raise InvalidOperationError("The Redis subscription is closed")
            if self._pubsub is None:
                raise InvalidOperationError("The Redis subscription has been cleaned up")

            self._pubsub.subscribe(self._topic)
            _logger.debug("Subscribed to channel %s", self._topic)

            self._iter_gen = self._message_iterator()
            self._listener_thread = threading.Thread(
                target=self._listen,
                name=f"redis-broadcast-{self._topic}",
                daemon=True,
            )
            self._listener_thread.start()
            self._started = True

    def _listen(self) -> None:
        while not self._closed.is_set():
            pubsub = self._pubsub
            if pubsub is None:
                break

            try:
                raw_message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            except Exception as exc:  # pragma: no cover - defensive guard
                if not self._closed.is_set():
                    _logger.exception(
                        "Failed to fetch message from channel %s",
                        self._topic,
                        exc_info=exc,
                    )
                break

            if raw_message is None:
                continue

            if raw_message.get("type") != "message":
                continue

            channel_field = raw_message.get("channel")
            if isinstance(channel_field, bytes):
                channel_name = channel_field.decode("utf-8")
            elif isinstance(channel_field, str):
                channel_name = channel_field
            else:
                channel_name = str(channel_field)

            if channel_name != self._topic:
                _logger.debug("Ignoring message from unexpected channel %s", channel_name)
                continue

            payload_field = raw_message.get("data")
            payload_bytes: bytes
            if isinstance(payload_field, bytes):
                payload_bytes = payload_field
            elif isinstance(payload_field, memoryview):
                payload_bytes = payload_field.tobytes()
            elif isinstance(payload_field, bytearray):
                payload_bytes = bytes(payload_field)
            elif isinstance(payload_field, str):
                payload_bytes = payload_field.encode("utf-8")
            elif payload_field is None:
                payload_bytes = b""
            else:
                try:
                    payload_bytes = bytes(payload_field)
                except Exception:
                    _logger.warning(
                        "Dropping message with unsupported payload type %s on channel %s",
                        type(payload_field),
                        self._topic,
                    )
                    continue

            _logger.debug("Received message from channel %s", self._topic)
            self._enqueue_message(payload_bytes)

        self._signal_stop()
        _logger.debug("Listener thread stopped for channel %s", self._topic)

    def _enqueue_message(self, payload: bytes) -> None:
        if self._overflow is Overflow.DROP_NEWEST:
            if self._queue.full():
                _logger.debug(
                    "Dropping newest message for channel %s due to full buffer (size=%s)",
                    self._topic,
                    self._buffer_size,
                )
                return
            try:
                self._queue.put_nowait(payload)
            except queue.Full:  # pragma: no cover - race condition guard
                return
            return

        if self._overflow is Overflow.DROP_OLDEST:
            while not self._closed.is_set():
                try:
                    self._queue.put_nowait(payload)
                    return
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:  # pragma: no cover - defensive guard
                        return
            return

        while not self._closed.is_set():
            try:
                self._queue.put(payload, timeout=0.1)
                return
            except queue.Full:
                continue

    def _message_iterator(self) -> Generator[bytes, None, None]:
        while True:
            if self._closed.is_set() and self._queue.empty():
                return
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if isinstance(item, _Stop):
                return
            yield item

    def __iter__(self) -> Iterator[bytes]:
        if self._closed.is_set():
            raise InvalidOperationError("The Redis subscription is closed")
        self._start_if_needed()
        assert self._iter_gen is not None, "Subscription is not properly setup."
        return iter(self._iter_gen)

    def __enter__(self) -> "Subscription":
        self._start_if_needed()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> bool | None:
        self.close()
        return None

    def close(self) -> None:
        if self._closed.is_set():
            return

        self._closed.set()
        pubsub = self._pubsub
        if pubsub is not None:
            pubsub.unsubscribe(self._topic)
            pubsub.close()
        self._pubsub = None

        self._signal_stop()

        listener = self._listener_thread
        if listener is not None:
            listener.join(timeout=1.0)
            self._listener_thread = None

        self._iter_gen = None

    def _signal_stop(self) -> None:
        try:
            self._queue.put_nowait(_STOP)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(_STOP)
            except queue.Full:  # pragma: no cover - final fallback
                while True:
                    try:
                        self._queue.put(_STOP, timeout=0.1)
                        break
                    except queue.Full:
                        if self._closed.is_set():
                            continue
