"""
Buffer management tests for Redis broadcast channel implementation.

This module tests buffer overflow behaviors including DROP_OLDEST,
DROP_NEWEST, and BLOCK strategies, as well as buffer validation
and performance under high message rates.
"""

import threading
import time
from typing import Any

import pytest

from libs.broadcast_channel.channel import Overflow
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_data import (
    BUFFER_TEST_CONFIGS,
)
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_helpers import (
    ConcurrentPublisher,
    wait_for_condition,
)


class TestDropOldestOverflow:
    """Test DROP_OLDEST overflow behavior."""

    def test_drop_oldest_basic_behavior(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        small_buffer_size: int,
    ) -> None:
        """Test basic DROP_OLDEST behavior when buffer is full."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Create more messages than buffer can hold
        messages_to_send = [f"msg_{i}".encode() for i in range(small_buffer_size + 2)]

        # Act
        with topic.subscribe(buffer=small_buffer_size, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    # Continue collecting to see what's in buffer after overflow
                    time.sleep(0.1)  # Small delay to ensure all messages are processed
                    if len(received_messages) >= small_buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            # Give subscription time to start
            time.sleep(0.1)

            # Publish more messages than buffer can hold
            for message in messages_to_send:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        # Should have exactly buffer_size messages (oldest dropped)
        assert len(received_messages) == small_buffer_size

        # Should contain the last 'small_buffer_size' messages (oldest dropped)
        expected_messages = messages_to_send[-small_buffer_size:]
        assert received_messages == expected_messages

    def test_drop_oldest_continuous_overflow(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test DROP_OLDEST behavior with continuous overflow."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        buffer_size = 3

        # Act
        with topic.subscribe(buffer=buffer_size, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 10:  # Collect more than buffer size
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish many messages to trigger continuous overflow
            for i in range(15):
                producer.publish(f"msg_{i}".encode())
                time.sleep(0.01)  # Small delay between messages

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) >= buffer_size
        # Should contain the most recent messages
        assert received_messages[-buffer_size:] == [f"msg_{i}".encode() for i in range(12, 15)]

    def test_drop_oldest_with_rapid_publishing(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test DROP_OLDEST behavior with very rapid message publishing."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        buffer_size = 5

        # Act
        with topic.subscribe(buffer=buffer_size, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    time.sleep(0.2)  # Slow consumption to cause overflow
                    if len(received_messages) >= buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Rapidly publish many messages
            for i in range(20):
                producer.publish(f"rapid_msg_{i}".encode())

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == buffer_size
        # Should contain the last buffer_size messages
        expected = [f"rapid_msg_{i}".encode() for i in range(15, 20)]
        assert received_messages == expected


class TestDropNewestOverflow:
    """Test DROP_NEWEST overflow behavior."""

    def test_drop_newest_basic_behavior(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        small_buffer_size: int,
    ) -> None:
        """Test basic DROP_NEWEST behavior when buffer is full."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Create more messages than buffer can hold
        messages_to_send = [f"msg_{i}".encode() for i in range(small_buffer_size + 2)]

        # Act
        with topic.subscribe(buffer=small_buffer_size, overflow=Overflow.DROP_NEWEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    time.sleep(0.1)  # Small delay to ensure all messages are processed
                    if len(received_messages) >= small_buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish more messages than buffer can hold
            for message in messages_to_send:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        # Should have exactly buffer_size messages (newest dropped)
        assert len(received_messages) == small_buffer_size

        # Should contain the first 'small_buffer_size' messages (newest dropped)
        expected_messages = messages_to_send[:small_buffer_size]
        assert received_messages == expected_messages

    def test_drop_newest_with_burst_publishing(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test DROP_NEWEST behavior with burst publishing."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        buffer_size = 3

        # Act
        with topic.subscribe(buffer=buffer_size, overflow=Overflow.DROP_NEWEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish a burst of messages
            burst_messages = [f"burst_{i}".encode() for i in range(10)]
            for message in burst_messages:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == buffer_size
        # Should contain the first buffer_size messages from the burst
        expected = burst_messages[:buffer_size]
        assert received_messages == expected

    def test_drop_newest_preserves_existing_messages(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that DROP_NEWEST preserves existing messages in buffer."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        buffer_size = 4

        # Act
        with topic.subscribe(buffer=buffer_size, overflow=Overflow.DROP_NEWEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish initial messages to fill buffer
            for i in range(buffer_size):
                producer.publish(f"initial_{i}".encode())
                time.sleep(0.05)

            # Wait for initial messages to be received
            time.sleep(0.2)

            # Publish additional messages (should be dropped)
            for i in range(5):
                producer.publish(f"extra_{i}".encode())

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == buffer_size
        # Should contain only the initial messages
        expected = [f"initial_{i}".encode() for i in range(buffer_size)]
        assert received_messages == expected


class TestBlockOverflow:
    """Test BLOCK overflow behavior."""

    def test_block_basic_behavior(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        small_buffer_size: int,
    ) -> None:
        """Test basic BLOCK behavior when buffer is full."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=small_buffer_size, overflow=Overflow.BLOCK) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= small_buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish exactly buffer_size messages (should not block)
            initial_messages = [f"initial_{i}".encode() for i in range(small_buffer_size)]
            for message in initial_messages:
                producer.publish(message)

            # Wait for messages to be consumed
            wait_for_condition(lambda: len(received_messages) >= small_buffer_size, timeout=2.0)

            # Publish additional messages (should block until buffer has space)
            additional_messages = [f"additional_{i}".encode() for i in range(2)]
            for message in additional_messages:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        # Should receive all messages (no dropping)
        expected_total = small_buffer_size + len(additional_messages)
        assert len(received_messages) == expected_total
        assert received_messages[:small_buffer_size] == initial_messages
        assert received_messages[small_buffer_size:] == additional_messages

    def test_block_with_slow_consumer(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test BLOCK behavior with slow consumer."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        buffer_size = 3

        # Act
        with topic.subscribe(buffer=buffer_size, overflow=Overflow.BLOCK) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    time.sleep(0.2)  # Slow consumption
                    if len(received_messages) >= 6:  # Collect more than buffer size
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish messages - should block when buffer is full
            messages_to_publish = [f"slow_{i}".encode() for i in range(6)]
            start_time = time.time()

            for message in messages_to_publish:
                producer.publish(message)

            end_time = time.time()
            publishing_time = end_time - start_time

            collector_thread.join(timeout=10.0)

        # Assert
        assert len(received_messages) == 6
        assert received_messages == messages_to_publish
        # Publishing should take longer due to blocking
        assert publishing_time > 0.5  # Should take at least some time due to blocking

    def test_block_timeout_behavior(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test BLOCK behavior with potential timeout scenarios."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        buffer_size = 2

        # Act
        with topic.subscribe(buffer=buffer_size, overflow=Overflow.BLOCK) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    # Don't consume all messages to test blocking
                    if len(received_messages) >= buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Fill the buffer
            for i in range(buffer_size):
                producer.publish(f"fill_{i}".encode())

            # Wait for buffer to be filled
            wait_for_condition(lambda: len(received_messages) >= buffer_size, timeout=2.0)

            # Try to publish more - should block but eventually succeed
            # when the subscription is closed
            start_time = time.time()

            def publish_extra():
                time.sleep(0.1)  # Small delay
                producer.publish(b"extra_message")

            publisher_thread = threading.Thread(target=publish_extra, daemon=True)
            publisher_thread.start()

            # Close subscription to unblock publisher
            time.sleep(0.2)
            subscription.close()

            publisher_thread.join(timeout=2.0)
            collector_thread.join(timeout=2.0)

            end_time = time.time()

        # Assert
        # The extra message should not be received since subscription was closed
        assert len(received_messages) == buffer_size


class TestBufferValidation:
    """Test buffer size validation and edge cases."""

    @pytest.mark.parametrize("invalid_size", [0, -1, -10])
    def test_invalid_buffer_sizes(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        invalid_size: int,
    ) -> None:
        """Test that invalid buffer sizes raise appropriate errors."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Act & Assert
        with pytest.raises(ValueError, match="buffer must be a positive integer"):
            topic.subscribe(buffer=invalid_size)

    @pytest.mark.parametrize("invalid_type", ["invalid", None, [], {}])
    def test_invalid_buffer_types(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        invalid_type: Any,
    ) -> None:
        """Test that invalid buffer types raise appropriate errors."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Act & Assert
        with pytest.raises((TypeError, ValueError)):
            topic.subscribe(buffer=invalid_type)

    def test_minimum_buffer_size(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test behavior with minimum buffer size (1)."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=1, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    time.sleep(0.1)
                    if len(received_messages) >= 3:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish multiple messages
            for i in range(5):
                producer.publish(f"min_buffer_{i}".encode())

            collector_thread.join(timeout=5.0)

        # Assert
        # Should only have the most recent message
        assert len(received_messages) >= 1
        assert received_messages[-1] == b"min_buffer_4"

    def test_large_buffer_size(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        large_buffer_size: int,
    ) -> None:
        """Test behavior with large buffer sizes."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=large_buffer_size, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 100:  # Collect subset
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish messages (less than buffer size)
            for i in range(100):
                producer.publish(f"large_buffer_{i}".encode())

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 100
        expected = [f"large_buffer_{i}".encode() for i in range(100)]
        assert received_messages == expected


class TestBufferPerformance:
    """Test buffer performance under high message rates."""

    def test_high_frequency_publishing_drop_oldest(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test performance with high frequency publishing using DROP_OLDEST."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        buffer_size = 10

        # Act
        with topic.subscribe(buffer=buffer_size, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    time.sleep(0.001)  # Very fast consumption
                    if len(received_messages) >= buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish many messages rapidly
            message_count = 1000
            for i in range(message_count):
                producer.publish(f"high_freq_{i}".encode())

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == buffer_size
        # Should contain the most recent messages
        expected = [f"high_freq_{i}".encode() for i in range(message_count - buffer_size, message_count)]
        assert received_messages == expected

    def test_high_frequency_publishing_drop_newest(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test performance with high frequency publishing using DROP_NEWEST."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        buffer_size = 10

        # Act
        with topic.subscribe(buffer=buffer_size, overflow=Overflow.DROP_NEWEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    time.sleep(0.001)  # Very fast consumption
                    if len(received_messages) >= buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish many messages rapidly
            message_count = 1000
            for i in range(message_count):
                producer.publish(f"high_freq_{i}".encode())

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == buffer_size
        # Should contain the first buffer_size messages
        expected = [f"high_freq_{i}".encode() for i in range(buffer_size)]
        assert received_messages == expected


class TestParametrizedBufferConfigs:
    """Test with parametrized buffer configurations."""

    @pytest.mark.parametrize("config", BUFFER_TEST_CONFIGS)
    def test_buffer_configurations(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        config: Any,
    ) -> None:
        """Test different buffer configurations."""
        # Arrange
        topic = broadcast_channel.topic(f"{unique_topic}_{config.description}")
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=config.buffer_size, overflow=config.overflow_strategy) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    time.sleep(0.01)
                    if len(received_messages) >= config.buffer_size:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish messages
            messages_to_send = [f"config_{i}".encode() for i in range(config.message_count)]
            for message in messages_to_send:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        if config.expected_behavior == "drop_oldest":
            # Should have buffer_size messages (oldest dropped)
            assert len(received_messages) == config.buffer_size
            expected = messages_to_send[-config.buffer_size :]
            assert received_messages == expected
        elif config.expected_behavior == "drop_newest":
            # Should have buffer_size messages (newest dropped)
            assert len(received_messages) == config.buffer_size
            expected = messages_to_send[: config.buffer_size]
            assert received_messages == expected
        elif config.expected_behavior == "block":
            # Should have all messages (no dropping)
            assert len(received_messages) == config.message_count
            assert received_messages == messages_to_send
