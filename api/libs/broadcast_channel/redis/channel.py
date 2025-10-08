from collections.abc import Generator
import dataclasses
import logging
import threading
from typing import Iterator
from redis import Redis
from redis.client import PubSub

from libs.broadcast_channel.channel import Producer, Subscriber, Subscription
from libs.broadcast_channel.exc import InvalidOperationError


_logger= logging.getLogger(__name__)


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
        return _RedisSubscription(
            self._client.pubsub(),
            self._topic,

        )


@dataclasses.dataclass(frozen=True)
class _Stop:
    pass


_STOP = _Stop()


class _RedisSubscription:
    def __init__(self, pubsub: PubSub, topic: str):
        self._pubsub = pubsub
        self._topic = topic
        self._closed = False
        self._iter_gen: Generator[bytes, _Stop, None] =

    @staticmethod
    def _yield_from_pubsub(pubsub: PubSub) -> Generator[bytes, _Stop, None]:

        # Listen for messages using get_message with timeout
        while True:
                    if self._cancel.is_set():
                return

            pubsub = self._pubsub
            if pubsub is None:
                # Closed by other threads.
                return
            raw_message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if raw_message is None:
                continue

            if raw_message["type"] != "message":
                continue

            channel_name = raw_message["channel"].decode("utf-8")
            if channel_name != self._key:
                raise AssertionError(f"expected message from {self._key}, got {channel_name}")

            # Return the raw bytes payload
            payload = raw_message["data"]
            logger.debug("Received message from channel %s", self._key)
            yield payload

    def __iter__(self) -> Iterator[bytes]:
        if self._closed:
            raise InvalidOperationError("The RedisBroadcastChannel instance is closed")

        self._iter_gen = _RedisSubscription._yield_from_pubsub(self._pubsub)
        return iter(self._iter_gen)

    def __enter__(self) -> "Subscription":
        self._pubsub.subscribe(self._topic)
        _logger.debug("Subscribed to channel %s", self._topic)
        self._iter_gen =
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> bool | None:
        self._pubsub.close()
        return None

    def close(self):
        self._cancel.set()
