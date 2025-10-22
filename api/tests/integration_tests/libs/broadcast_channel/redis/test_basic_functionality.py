"""
Basic functionality tests for Redis broadcast channel implementation.

This module tests the core publish/subscribe functionality, including
simple operations, multiple subscribers, topic isolation, and interface
compliance.
"""

import threading
import time
from typing import Any

import pytest

from libs.broadcast_channel.exc import InvalidOperationError
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_helpers import (
    assert_message_order,
    wait_for_condition,
)


class TestBasicPublishSubscribe:
    """Test basic publish and subscribe operations."""

    def test_simple_publish_subscribe(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        test_messages: list[bytes],
    ) -> None:
        """Test simple publish and subscribe functionality."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=5) as subscription:
            # Start message collection in a separate thread
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= len(test_messages):
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            # Give subscription time to start
            time.sleep(0.1)

            # Publish test messages
            for message in test_messages[:3]:  # Use first 3 messages
                producer.publish(message)

            # Wait for collection to complete
            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 3
        assert received_messages == test_messages[:3]

    def test_multiple_subscribers_same_topic(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        test_messages: list[bytes],
    ) -> None:
        """Test multiple subscribers to the same topic receive all messages."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        subscriber_count = 3
        messages_to_send = test_messages[:3]

        # Act
        all_received_messages = []
        subscription_threads = []

        def create_subscriber(subscriber_id: int):
            received = []
            with topic.subscribe(buffer=10) as subscription:
                for message in subscription:
                    received.append(message)
                    if len(received) >= len(messages_to_send):
                        break
            all_received_messages.append((subscriber_id, received))

        # Start multiple subscribers
        for i in range(subscriber_count):
            thread = threading.Thread(
                target=create_subscriber,
                args=(i,),
                daemon=True,
            )
            thread.start()
            subscription_threads.append(thread)

        # Give subscribers time to start
        time.sleep(0.2)

        # Publish messages
        for message in messages_to_send:
            producer.publish(message)

        # Wait for all subscribers to complete
        for thread in subscription_threads:
            thread.join(timeout=5.0)

        # Assert
        assert len(all_received_messages) == subscriber_count

        for subscriber_id, received in all_received_messages:
            assert len(received) == len(messages_to_send)
            assert received == messages_to_send

    def test_different_topics_independent_streams(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        test_messages: list[bytes],
    ) -> None:
        """Test that different topics have independent message streams."""
        # Arrange
        topic1 = broadcast_channel.topic(f"{unique_topic}_1")
        topic2 = broadcast_channel.topic(f"{unique_topic}_2")

        producer1 = topic1.as_producer()
        producer2 = topic2.as_producer()

        messages_topic1 = test_messages[:2]
        messages_topic2 = test_messages[2:4]

        # Act
        received_topic1 = []
        received_topic2 = []

        def subscriber1():
            with topic1.subscribe(buffer=5) as subscription:
                for message in subscription:
                    received_topic1.append(message)
                    if len(received_topic1) >= len(messages_topic1):
                        break

        def subscriber2():
            with topic2.subscribe(buffer=5) as subscription:
                for message in subscription:
                    received_topic2.append(message)
                    if len(received_topic2) >= len(messages_topic2):
                        break

        thread1 = threading.Thread(target=subscriber1, daemon=True)
        thread2 = threading.Thread(target=subscriber2, daemon=True)

        thread1.start()
        thread2.start()

        # Give subscribers time to start
        time.sleep(0.1)

        # Publish to different topics
        for message in messages_topic1:
            producer1.publish(message)
        for message in messages_topic2:
            producer2.publish(message)

        thread1.join(timeout=5.0)
        thread2.join(timeout=5.0)

        # Assert
        assert received_topic1 == messages_topic1
        assert received_topic2 == messages_topic2
        assert received_topic1 != received_topic2  # Ensure independence

    def test_message_ordering(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that messages are received in the same order they are published."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Create ordered messages with sequence numbers
        ordered_messages = [f"message_{i:03d}".encode() for i in range(10)]

        # Act
        with topic.subscribe(buffer=20) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= len(ordered_messages):
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            # Give subscription time to start
            time.sleep(0.1)

            # Publish messages in order
            for message in ordered_messages:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == len(ordered_messages)
        assert assert_message_order(received_messages, ordered_messages)

    def test_subscription_lifecycle(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test subscription lifecycle management."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act & Assert - Test subscription creation and destruction
        subscription = topic.subscribe(buffer=5)
        assert subscription is not None
        # Check interface compliance through duck typing instead of isinstance
        assert hasattr(subscription, "__iter__")
        assert hasattr(subscription, "close")
        assert hasattr(subscription, "__enter__")
        assert hasattr(subscription, "__exit__")

        # Test that subscription is not closed initially
        subscription.close()

        # Test that operations on closed subscription fail
        with pytest.raises(InvalidOperationError):
            for _ in subscription:  # type: ignore
                pass

    def test_context_manager_behavior(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        test_messages: list[bytes],
    ) -> None:
        """Test that subscription works correctly as a context manager."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        received_messages = []

        with topic.subscribe(buffer=10) as subscription:
            # Collection thread
            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 3:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            # Give subscription time to start
            time.sleep(0.1)

            # Publish messages
            for message in test_messages[:3]:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert - Subscription should be automatically closed
        assert len(received_messages) == 3
        assert received_messages == test_messages[:3]

        # Verify subscription is closed after context manager exits
        with pytest.raises(InvalidOperationError):
            for _ in subscription:  # type: ignore
                pass


class TestMessageTypes:
    """Test handling of different message types."""

    def test_empty_message_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of empty messages."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=5) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 2:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish empty messages
            producer.publish(b"")
            producer.publish(b"")  # Another empty message

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 2
        assert all(msg == b"" for msg in received_messages)

    def test_unicode_message_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of Unicode messages."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        unicode_messages = [
            "Hello, 世界!".encode("utf-8"),
            "Café résumé naïve".encode("utf-8"),
            "🚀 Rocket ship 🌟".encode("utf-8"),
        ]

        # Act
        with topic.subscribe(buffer=10) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= len(unicode_messages):
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            for message in unicode_messages:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == len(unicode_messages)
        assert received_messages == unicode_messages

    def test_large_message_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of large messages."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Create a large message (100KB)
        large_message = b"x" * 100000

        # Act
        with topic.subscribe(buffer=5) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    break  # Only expect one message

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            producer.publish(large_message)

            collector_thread.join(timeout=10.0)  # Longer timeout for large message

        # Assert
        assert len(received_messages) == 1
        assert received_messages[0] == large_message


class TestProducerInterface:
    """Test producer interface compliance."""

    def test_producer_interface_compliance(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that producer implements the correct interface."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Assert
        assert hasattr(producer, "publish")
        assert callable(getattr(producer, "publish"))

        # Test that it's the same object (as_producer returns self)
        assert producer is topic

    def test_publish_method_accepts_bytes(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that publish method accepts bytes."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act & Assert - Should not raise an exception
        producer.publish(b"test_message")


class TestSubscriberInterface:
    """Test subscriber interface compliance."""

    def test_subscriber_interface_compliance(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that subscriber implements the correct interface."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        subscriber = topic.as_subscriber()

        # Assert
        assert hasattr(subscriber, "subscribe")
        assert callable(getattr(subscriber, "subscribe"))

        # Test that it's the same object (as_subscriber returns self)
        assert subscriber is topic

    def test_subscribe_method_returns_subscription(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that subscribe method returns a Subscription object."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        subscriber = topic.as_subscriber()

        # Act
        subscription = subscriber.subscribe(buffer=5)

        # Assert
        # Check interface compliance through duck typing instead of isinstance
        assert hasattr(subscription, "__iter__")
        assert hasattr(subscription, "close")
        assert hasattr(subscription, "__enter__")
        assert hasattr(subscription, "__exit__")

        # Clean up
        subscription.close()

    def test_subscription_iterator_protocol(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that subscription implements iterator protocol correctly."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=5) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 2:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish messages
            producer.publish(b"iterator_test_1")
            producer.publish(b"iterator_test_2")

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 2
        assert received_messages[0] == b"iterator_test_1"
        assert received_messages[1] == b"iterator_test_2"

        # Test that subscription is iterable
        with topic.subscribe(buffer=5) as subscription:
            # Should be able to call iter() on subscription
            iterator = iter(subscription)
            assert iterator is not None
            assert hasattr(iterator, "__next__")

            # Test iterator protocol with context manager
            messages = []
            collector_thread = threading.Thread(
                target=lambda: [messages.append(msg) for msg in subscription if len(messages) < 1], daemon=True
            )
            collector_thread.start()

            time.sleep(0.1)
            producer.publish(b"iterator_protocol_test")
            collector_thread.join(timeout=2.0)

            assert len(messages) == 1
            assert messages[0] == b"iterator_protocol_test"
