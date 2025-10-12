"""
Integration tests for the Redis BroadcastChannel implementation.

These tests exercise the real Redis pub/sub behaviour to ensure the channel
abstraction honours the documented semantics: topic isolation, broadcast fan-out,
and at-most-once delivery with configurable overflow strategies.
"""

import time
import uuid
from collections.abc import Iterator
from threading import Event, Thread

import pytest
import redis

from configs.app_config import DifyConfig
from libs.broadcast_channel.channel import Overflow
from libs.broadcast_channel.redis.channel import BroadcastChannel, Topic


@pytest.fixture(scope="module")
def redis_client(dify_config: DifyConfig) -> Iterator[redis.Redis]:
    """Provide a Redis client connected to the integration test instance."""
    client = redis.Redis(
        host=dify_config.REDIS_HOST,
        port=dify_config.REDIS_PORT,
        db=dify_config.REDIS_DB,
        username=dify_config.REDIS_USERNAME,
        password=dify_config.REDIS_PASSWORD,
        decode_responses=False,
    )
    client.ping()
    try:
        yield client
    finally:
        client.close()


def _unique_channel_key() -> str:
    return f"broadcast:test:{uuid.uuid4().hex}"


def _spawn_subscription_thread(
    topic: Topic,
    *,
    buffer: int = 1024,
    overflow: Overflow = Overflow.DROP_OLDEST,
    collected: list[bytes],
    ready_event: Event,
    start_read_event: Event | None = None,
    limit: int = 1,
) -> Thread:
    subscription = topic.as_subscriber().subscribe(buffer=buffer, overflow=overflow)

    def _worker() -> None:
        with subscription as iterator:
            ready_event.set()
            if start_read_event is not None:
                start_read_event.wait(timeout=2)
            for message in iterator:
                collected.append(message)
                if len(collected) >= limit:
                    break

    thread = Thread(target=_worker, daemon=True)
    thread.start()
    return thread


def test_topic_isolation(redis_client: redis.Redis) -> None:
    broadcast_channel = BroadcastChannel(redis_client)
    topic_a = broadcast_channel.topic(_unique_channel_key())
    topic_b = broadcast_channel.topic(_unique_channel_key())

    messages_a: list[bytes] = []
    messages_b: list[bytes] = []
    ready_a = Event()
    ready_b = Event()

    thread_a = _spawn_subscription_thread(topic_a, collected=messages_a, ready_event=ready_a, limit=1)
    thread_b = _spawn_subscription_thread(topic_b, collected=messages_b, ready_event=ready_b, limit=1)

    assert ready_a.wait(timeout=2)
    assert ready_b.wait(timeout=2)

    topic_a.as_producer().publish(b"message-for-a")
    topic_b.as_producer().publish(b"message-for-b")

    thread_a.join(timeout=2)
    thread_b.join(timeout=2)

    assert messages_a == [b"message-for-a"]
    assert messages_b == [b"message-for-b"]
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()


def test_broadcast_reaches_all_subscribers(redis_client: redis.Redis) -> None:
    broadcast_channel = BroadcastChannel(redis_client)
    topic = broadcast_channel.topic(_unique_channel_key())
    payload = b"fan-out-payload"

    messages_first: list[bytes] = []
    messages_second: list[bytes] = []
    ready_first = Event()
    ready_second = Event()

    first_thread = _spawn_subscription_thread(topic, collected=messages_first, ready_event=ready_first, limit=1)
    second_thread = _spawn_subscription_thread(topic, collected=messages_second, ready_event=ready_second, limit=1)

    assert ready_first.wait(timeout=2)
    assert ready_second.wait(timeout=2)

    topic.as_producer().publish(payload)

    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert messages_first == [payload]
    assert messages_second == [payload]
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()


def test_publish_before_subscription_is_dropped(redis_client: redis.Redis) -> None:
    broadcast_channel = BroadcastChannel(redis_client)
    topic = broadcast_channel.topic(_unique_channel_key())
    producer = topic.as_producer()

    producer.publish(b"message-before-subscribe")

    messages: list[bytes] = []
    ready = Event()
    thread = _spawn_subscription_thread(topic, collected=messages, ready_event=ready, limit=1)

    assert ready.wait(timeout=2)

    producer.publish(b"message-after-subscribe")

    thread.join(timeout=2)

    assert messages == [b"message-after-subscribe"]
    assert not thread.is_alive()


def test_drop_oldest_overflow_behavior(redis_client: redis.Redis) -> None:
    broadcast_channel = BroadcastChannel(redis_client)
    topic = broadcast_channel.topic(_unique_channel_key())

    messages: list[bytes] = []
    ready = Event()
    allow_read = Event()

    thread = _spawn_subscription_thread(
        topic,
        buffer=1,
        overflow=Overflow.DROP_OLDEST,
        collected=messages,
        ready_event=ready,
        start_read_event=allow_read,
        limit=1,
    )

    assert ready.wait(timeout=2)

    producer = topic.as_producer()
    producer.publish(b"first-message")
    producer.publish(b"second-message")

    time.sleep(0.05)
    allow_read.set()

    thread.join(timeout=2)

    assert messages == [b"second-message"]
    assert not thread.is_alive()


def test_drop_newest_overflow_behavior(redis_client: redis.Redis) -> None:
    broadcast_channel = BroadcastChannel(redis_client)
    topic = broadcast_channel.topic(_unique_channel_key())

    messages: list[bytes] = []
    ready = Event()
    allow_read = Event()

    thread = _spawn_subscription_thread(
        topic,
        buffer=1,
        overflow=Overflow.DROP_NEWEST,
        collected=messages,
        ready_event=ready,
        start_read_event=allow_read,
        limit=1,
    )

    assert ready.wait(timeout=2)

    producer = topic.as_producer()
    producer.publish(b"first-message")
    producer.publish(b"second-message")

    time.sleep(0.05)
    allow_read.set()

    thread.join(timeout=2)

    assert messages == [b"first-message"]
    assert not thread.is_alive()


def test_multiple_publishers_no_additional_messages_after_completion(redis_client: redis.Redis) -> None:
    broadcast_channel = BroadcastChannel(redis_client)
    topic = broadcast_channel.topic(_unique_channel_key())

    collected: list[bytes] = []
    ready = Event()
    allow_read = Event()
    expected_messages = [
        b"publisher-0-message-0",
        b"publisher-1-message-0",
        b"publisher-0-message-1",
        b"publisher-1-message-1",
    ]

    thread = _spawn_subscription_thread(
        topic,
        buffer=len(expected_messages),
        overflow=Overflow.DROP_OLDEST,
        collected=collected,
        ready_event=ready,
        start_read_event=allow_read,
        limit=len(expected_messages),
    )

    assert ready.wait(timeout=2)

    producer = topic.as_producer()
    for message in expected_messages:
        producer.publish(message)
        time.sleep(0.005)

    allow_read.set()

    thread.join(timeout=2)
    assert not thread.is_alive()
    assert collected == expected_messages

    snapshot = list(collected)
    time.sleep(0.1)
    assert collected == snapshot
