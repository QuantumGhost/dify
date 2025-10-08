"""
Integration tests for Redis broadcast channel.

These tests require a running Redis instance and test the actual Redis Pub/Sub operations.
"""

import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Thread

import pytest
import redis

from configs.app_config import DifyConfig
from libs.redis_channels.broadcast_channel import InvalidOperationError, RedisBroadcastChannel


@dataclass
class PubSubTestCase:
    name: str
    channel_key: str
    messages: list[bytes]
    expected_subscriber_count: int


@pytest.fixture(scope="class")
def redis_client(dify_config: DifyConfig):
    """Create Redis client for integration tests."""
    # Use database 15 for tests to avoid conflicts
    client = redis.Redis(
        host=dify_config.REDIS_HOST,
        port=dify_config.REDIS_PORT,
        db=dify_config.REDIS_DB,
        username=dify_config.REDIS_USERNAME,
        password=dify_config.REDIS_PASSWORD,
        decode_responses=False,
    )

    client.ping()

    yield client

    client.close()


def get_pubsub_test_cases() -> list[PubSubTestCase]:
    """Get test cases for pub/sub integration."""
    return [
        PubSubTestCase(
            name="single_message",
            channel_key="test_channel_1",
            messages=[b"user_login_event_data"],
            expected_subscriber_count=1,
        ),
        PubSubTestCase(
            name="multiple_messages",
            channel_key="test_channel_2",
            messages=[
                b"workflow_started",
                b"node_completed",
                b"workflow_completed",
            ],
            expected_subscriber_count=2,
        ),
        PubSubTestCase(
            name="binary_data",
            channel_key="test_channel_3",
            messages=[
                b"\x01\x02\x03\x04binary_data",
            ],
            expected_subscriber_count=1,
        ),
    ]


def _run_generator(message_iterator: Iterator[bytes]):
    try:
        next(message_iterator)
    except StopIteration:
        pass


class TestRedisBroadcastChannelIntegration:
    """Integration tests for Redis broadcast channel with real Redis instance."""

    @pytest.fixture
    def unique_key_prefix(self):
        """Generate unique key prefix for each test."""
        return f"broadcast_test_{uuid.uuid4().hex[:8]}_"

    def test_broadcast_channel_creation(self, redis_client):
        """Test creating broadcast channel."""
        key = "test_channel"
        channel = RedisBroadcastChannel(redis_client, key)

        assert channel._redis_client is redis_client
        assert channel._key == key
        assert channel._pubsub is None
        assert channel._closed is False

    @pytest.mark.parametrize("test_case", get_pubsub_test_cases(), ids=lambda tc: tc.name)
    def test_broadcast_channel_pubsub(self, redis_client, unique_key_prefix, test_case):
        """Test broadcast channel pub/sub functionality."""
        channel_key = unique_key_prefix + test_case.channel_key
        received_messages = []
        subscriber_ready = Event()

        def subscriber_thread():
            """Subscriber thread function."""
            subscriber_channel = RedisBroadcastChannel(redis_client, channel_key)
            with subscriber_channel as message_iter:
                subscriber_ready.set()
                message_count = 0
                for message in message_iter:
                    received_messages.append(message)
                    message_count += 1
                    if message_count >= len(test_case.messages):
                        break

        # Start subscriber in background thread
        subscriber = Thread(target=subscriber_thread)
        subscriber.start()

        # Wait for subscriber to be ready
        subscriber_ready.wait(timeout=2)
        time.sleep(0.1)  # Small delay to ensure subscription is active

        # Publish messages
        publisher_channel = RedisBroadcastChannel(redis_client, channel_key)
        for message in test_case.messages:
            publisher_channel.publish(message)
            time.sleep(0.01)  # Small delay between messages

        # Wait for subscriber to finish
        subscriber.join(timeout=2)

        # Verify all messages were received
        assert len(received_messages) == len(test_case.messages)
        assert received_messages == test_case.messages

    def test_broadcast_channel_multiple_subscribers(self, redis_client, unique_key_prefix):
        """Test broadcast channel with multiple subscribers."""
        channel_key = unique_key_prefix + "multi_sub"
        message = b"broadcast_test_multi_subscriber"

        received_messages_1 = []
        received_messages_2 = []
        subscribers_ready = Event()

        def subscriber_1():
            """First subscriber thread."""
            channel = RedisBroadcastChannel(redis_client, channel_key)
            with channel as message_iter:
                subscribers_ready.wait()
                for msg in message_iter:
                    received_messages_1.append(msg)
                    break

        def subscriber_2():
            """Second subscriber thread."""
            channel = RedisBroadcastChannel(redis_client, channel_key)
            with channel as message_iter:
                subscribers_ready.wait()
                for msg in message_iter:
                    received_messages_2.append(msg)
                    break

        # Start both subscribers
        thread1 = Thread(target=subscriber_1)
        thread2 = Thread(target=subscriber_2)
        thread1.start()
        thread2.start()

        time.sleep(0.1)  # Allow subscribers to set up
        subscribers_ready.set()
        time.sleep(0.1)  # Allow subscribers to subscribe

        # Publish message
        publisher = RedisBroadcastChannel(redis_client, channel_key)
        publisher.publish(message)

        # Wait for both subscribers
        thread1.join(timeout=2)
        thread2.join(timeout=2)

        # Both subscribers should have received the message
        assert len(received_messages_1) == 1
        assert len(received_messages_2) == 1
        assert received_messages_1[0] == message
        assert received_messages_2[0] == message

    def test_broadcast_channel_single_subscription(self, redis_client, unique_key_prefix):
        """Test single channel subscription management."""
        channel_key = unique_key_prefix + "sub_mgmt"

        channel = RedisBroadcastChannel(redis_client, channel_key)

        # Initially no subscriptions
        assert channel._pubsub is None
        assert channel._closed is False

        # Start subscription
        message_iterator = channel.subscribe()

        thread = Thread(target=_run_generator, args=(message_iterator,), daemon=True)
        # This will trigger subscription setup
        thread.start()
        assert channel._pubsub is not None

        # Close the subscription
        channel.close()
        assert channel._pubsub is None
        assert channel._closed is True

    def test_broadcast_channel_bytes_handling(self, redis_client, unique_key_prefix):
        """Test bytes message handling edge cases."""
        channel_key = unique_key_prefix + "bytes_test"

        test_messages = [
            "unicode_测试".encode(),  # UTF-8 encoded Chinese
            b"\x00\x01\x02\x03binary_data",  # Binary data with null bytes
            b"",  # Empty bytes
            b"special_chars!@#$%^&*()",  # Special characters
            b"long_message_" + b"x" * 1000,  # Long message
        ]

        received_messages = []

        def subscriber():
            sub_channel = RedisBroadcastChannel(redis_client, channel_key)
            with sub_channel as message_iter:
                for msg in message_iter:
                    received_messages.append(msg)
                    if len(received_messages) >= len(test_messages):
                        break

        # Start subscriber
        subscriber_thread = Thread(target=subscriber)
        subscriber_thread.start()
        time.sleep(0.1)  # Allow subscriber to set up

        # Publish test messages
        pub_channel = RedisBroadcastChannel(redis_client, channel_key)
        for message in test_messages:
            pub_channel.publish(message)
            time.sleep(0.01)

        subscriber_thread.join(timeout=2)

        # Verify all messages were handled correctly
        assert len(received_messages) == len(test_messages)
        assert received_messages == test_messages

    def test_broadcast_channel_error_handling(self, redis_client, unique_key_prefix):
        """Test error handling scenarios."""
        channel_key = unique_key_prefix + "error_test"

        channel = RedisBroadcastChannel(redis_client, channel_key)

        # Test publishing bytes works fine
        channel.publish(b"test bytes")

        # Test that we can close multiple times safely
        # First we need to set up a subscription to test closing
        message_iterator = channel.subscribe()

        thread = Thread(target=_run_generator, args=(message_iterator,), daemon=True)
        # This will trigger subscription setup
        thread.start()

        channel.close()

        # Now close multiple times
        with pytest.raises(InvalidOperationError):
            channel.close()

    def test_broadcast_channel_concurrent_operations(self, redis_client, unique_key_prefix):
        """Test concurrent publish/subscribe operations."""
        channel_key = unique_key_prefix + "concurrent_test"
        num_publishers = 3
        num_subscribers = 2
        messages_per_publisher = 10

        all_published_messages = []
        cancel_event = Event()

        def publisher(publisher_id):
            """Publisher thread."""
            pub_channel = RedisBroadcastChannel(redis_client, channel_key)
            for i in range(messages_per_publisher):
                message = f"pub_{publisher_id}_seq_{i}_data".encode()
                pub_channel.publish(message)
                all_published_messages.append(message)
                time.sleep(0.001)  # Small delay

        def subscriber(_) -> list[bytes]:
            """Subscriber thread."""

            sub_channel = RedisBroadcastChannel(redis_client, channel_key, cancel_event)

            # Subscribe and collect messages
            with sub_channel as message_iterator:
                messages = list(message_iterator)
                return messages

        # Start publishers and subscribers concurrently
        with ThreadPoolExecutor(max_workers=num_publishers + num_subscribers) as executor:
            # Start subscribers first
            subscriber_futures = [executor.submit(subscriber, i) for i in range(num_subscribers)]

            time.sleep(0.1)  # Allow subscribers to set up

            # Start publishers
            publisher_futures = [executor.submit(publisher, i) for i in range(num_publishers)]

            # Wait for publishers to finish
            for future in publisher_futures:
                future.result()
            time.sleep(1)
            cancel_event.set()

            # Wait for subscribers to finish
            for future in subscriber_futures:
                message_received = future.result(timeout=5)
                assert set(message_received) == set(all_published_messages)

    def test_broadcast_channel_context_manager_cleanup(self, redis_client, unique_key_prefix):
        """Test that context managers properly clean up resources."""
        channel_key = unique_key_prefix + "cleanup_test"

        # Test broadcast channel cleanup
        channel = RedisBroadcastChannel(redis_client, channel_key)
        with channel:
            # The context manager automatically starts subscription
            pass  # Context manager handles setup and cleanup

        # After context exit, should be cleaned up
        assert channel._closed is True
        assert channel._pubsub is None
