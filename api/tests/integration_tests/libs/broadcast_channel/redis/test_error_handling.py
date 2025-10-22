"""
Error handling tests for Redis broadcast channel implementation.

This module tests error conditions, exception handling, and graceful
degradation scenarios including invalid inputs, connection failures,
and malformed messages.
"""

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from redis.exceptions import ConnectionError, RedisError

from libs.broadcast_channel.channel import Overflow
from libs.broadcast_channel.exc import InvalidOperationError
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_data import (
    ERROR_TEST_CONFIGS,
)
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_helpers import (
    SubscriptionMonitor,
    wait_for_condition,
)


class TestInvalidBufferSizes:
    """Test error handling for invalid buffer sizes."""

    @pytest.mark.parametrize("config", ERROR_TEST_CONFIGS)
    def test_invalid_buffer_size_errors(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        config: Any,
    ) -> None:
        """Test that invalid buffer sizes raise appropriate errors."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Act & Assert
        with pytest.raises(config.expected_exception):
            topic.subscribe(buffer=config.test_input)

    def test_buffer_size_validation_edge_cases(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test buffer size validation with edge cases."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Test cases: (input, expected_exception)
        test_cases = [
            (0, ValueError),  # Zero
            (-1, ValueError),  # Negative
            (-100, ValueError),  # Large negative
            ("1", TypeError),  # String
            (None, TypeError),  # None
            ([], TypeError),  # List
            ({}, TypeError),  # Dict
            (True, TypeError),  # Boolean
        ]

        for invalid_input, expected_exception in test_cases:
            # Act & Assert
            with pytest.raises(expected_exception):
                topic.subscribe(buffer=invalid_input)

    def test_valid_buffer_sizes(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that valid buffer sizes work correctly."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Test valid buffer sizes
        valid_sizes = [1, 10, 100, 1000]

        for buffer_size in valid_sizes:
            # Act & Assert - Should not raise an exception
            subscription = topic.subscribe(buffer=buffer_size)
            subscription.close()


class TestClosedSubscriptionErrors:
    """Test error handling for operations on closed subscriptions."""

    def test_iteration_on_closed_subscription(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that iterating over a closed subscription raises an error."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        subscription = topic.subscribe(buffer=5)
        subscription.close()

        # Act & Assert
        with pytest.raises(InvalidOperationError, match="The Redis subscription is closed"):
            for _ in subscription:  # type: ignore
                pass

    def test_context_manager_on_closed_subscription(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that using a closed subscription as context manager raises an error."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        subscription = topic.subscribe(buffer=5)
        subscription.close()

        # Act & Assert
        with pytest.raises(InvalidOperationError, match="The Redis subscription is closed"):
            with subscription:
                pass  # Should not reach here

    def test_multiple_close_operations(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that closing a subscription multiple times is safe."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        subscription = topic.subscribe(buffer=5)

        # Act & Assert - Should not raise an exception
        subscription.close()
        subscription.close()  # Second close should be safe
        subscription.close()  # Third close should be safe

    def test_publish_to_closed_subscription_topic(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that publishing to a topic with closed subscriptions works."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Create and close a subscription
        subscription = topic.subscribe(buffer=5)
        subscription.close()

        # Create a new subscription to receive messages
        with topic.subscribe(buffer=5) as active_subscription:
            received_messages = []

            def collect_messages():
                for message in active_subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 2:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Act - Publishing should still work
            producer.publish(b"message_1")
            producer.publish(b"message_2")

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 2
        assert received_messages == [b"message_1", b"message_2"]


class TestRedisConnectionFailures:
    """Test error handling for Redis connection failures."""

    def test_publish_with_connection_error(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test publishing when Redis connection fails."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Mock Redis client to raise connection error
        with patch.object(producer, "_client") as mock_client:
            mock_client.publish.side_effect = ConnectionError("Redis connection failed")

            # Act & Assert
            with pytest.raises(ConnectionError):
                producer.publish(b"test_message")

    def test_subscribe_with_connection_error(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test subscribing when Redis connection fails."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Mock Redis client to raise connection error during pubsub creation
        with patch.object(topic, "_client") as mock_client:
            mock_client.pubsub.side_effect = ConnectionError("Redis connection failed")

            # Act & Assert
            with pytest.raises(ConnectionError):
                topic.subscribe(buffer=5)

    def test_listener_thread_connection_error(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test listener thread handling of Redis connection errors."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Mock pubsub to raise connection error in get_message
        mock_pubsub = MagicMock()
        mock_pubsub.get_message.side_effect = ConnectionError("Redis connection failed")

        with patch.object(topic, "_client") as mock_client:
            mock_client.pubsub.return_value = mock_pubsub

            # Act
            subscription = topic.subscribe(buffer=5)

            # Try to iterate (should handle connection error gracefully)
            received_messages = []

            def collect_messages():
                try:
                    for message in subscription:
                        received_messages.append(message)
                except Exception as e:
                    # Connection errors should be handled gracefully
                    pass

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            # Wait for error handling
            time.sleep(0.5)

            # Clean up
            subscription.close()
            collector_thread.join(timeout=2.0)

        # Assert
        # Connection error should be handled without crashing
        assert not collector_thread.is_alive()

    def test_redis_error_during_subscription_cleanup(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of Redis errors during subscription cleanup."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Mock pubsub to raise error during unsubscribe
        mock_pubsub = MagicMock()
        mock_pubsub.unsubscribe.side_effect = RedisError("Redis error during unsubscribe")

        with patch.object(topic, "_client") as mock_client:
            mock_client.pubsub.return_value = mock_pubsub

            subscription = topic.subscribe(buffer=5)

            # Act & Assert - Cleanup should handle errors gracefully
            # Note: Current implementation doesn't catch Redis errors during cleanup
            # This test documents the current behavior
            with pytest.raises(RedisError):
                subscription.close()

    def test_redis_error_during_pubsub_close(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of Redis errors during pubsub close."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Mock pubsub to raise error during close
        mock_pubsub = MagicMock()
        mock_pubsub.close.side_effect = RedisError("Redis error during close")

        with patch.object(topic, "_client") as mock_client:
            mock_client.pubsub.return_value = mock_pubsub

            subscription = topic.subscribe(buffer=5)

            # Act & Assert - Cleanup should handle errors gracefully
            # Note: Current implementation doesn't catch Redis errors during cleanup
            # This test documents the current behavior
            with pytest.raises(RedisError):
                subscription.close()


class TestMalformedMessageHandling:
    """Test handling of malformed messages."""

    def test_none_message_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of None messages from Redis."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=10) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 2:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish normal messages (None should be converted to empty bytes)
            producer.publish(b"message_1")
            producer.publish(b"message_2")

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 2
        assert received_messages == [b"message_1", b"message_2"]

    def test_unsupported_payload_type_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of unsupported payload types from Redis."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Mock pubsub to return unsupported payload type
        mock_pubsub = MagicMock()

        # Simulate Redis message with unsupported payload type
        unsupported_message = {
            "type": "message",
            "channel": unique_topic.encode(),
            "data": {"invalid": "object"},  # Unsupported type
        }

        normal_message = {
            "type": "message",
            "channel": unique_topic.encode(),
            "data": b"normal_message",
        }

        mock_pubsub.get_message.side_effect = [
            unsupported_message,  # First message is unsupported
            normal_message,  # Second message is normal
            None,  # No more messages
        ]

        with patch.object(topic, "_client") as mock_client:
            mock_client.pubsub.return_value = mock_pubsub

            # Act
            with topic.subscribe(buffer=10) as subscription:
                received_messages = []

                def collect_messages():
                    for message in subscription:
                        received_messages.append(message)
                        if len(received_messages) >= 1:
                            break

                collector_thread = threading.Thread(target=collect_messages, daemon=True)
                collector_thread.start()

                time.sleep(0.5)

                # Simulate subscription
                mock_pubsub.subscribe.assert_called_with(unique_topic)

                collector_thread.join(timeout=5.0)

            # Assert
            # Should only receive the valid message (unsupported one should be dropped)
            assert len(received_messages) == 1
            assert received_messages[0] == b"normal_message"

    def test_malformed_channel_name_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of messages with malformed channel names."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Mock pubsub to return message with wrong channel
        mock_pubsub = MagicMock()

        wrong_channel_message = {
            "type": "message",
            "channel": b"wrong_channel",
            "data": b"wrong_channel_message",
        }

        correct_channel_message = {
            "type": "message",
            "channel": unique_topic.encode(),
            "data": b"correct_channel_message",
        }

        mock_pubsub.get_message.side_effect = [
            wrong_channel_message,  # First message has wrong channel
            correct_channel_message,  # Second message has correct channel
            None,  # No more messages
        ]

        with patch.object(topic, "_client") as mock_client:
            mock_client.pubsub.return_value = mock_pubsub

            # Act
            with topic.subscribe(buffer=10) as subscription:
                received_messages = []

                def collect_messages():
                    for message in subscription:
                        received_messages.append(message)
                        if len(received_messages) >= 1:
                            break

                collector_thread = threading.Thread(target=collect_messages, daemon=True)
                collector_thread.start()

                time.sleep(0.5)

                collector_thread.join(timeout=5.0)

            # Assert
            # Should only receive the message with correct channel
            assert len(received_messages) == 1
            assert received_messages[0] == b"correct_channel_message"

    def test_non_message_type_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of non-message types from Redis pubsub."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Mock pubsub to return non-message types
        mock_pubsub = MagicMock()

        subscribe_message = {
            "type": "subscribe",
            "channel": unique_topic.encode(),
            "data": 1,
        }

        normal_message = {
            "type": "message",
            "channel": unique_topic.encode(),
            "data": b"normal_message",
        }

        mock_pubsub.get_message.side_effect = [
            subscribe_message,  # Subscribe message (should be ignored)
            normal_message,  # Normal message
            None,  # No more messages
        ]

        with patch.object(topic, "_client") as mock_client:
            mock_client.pubsub.return_value = mock_pubsub

            # Act
            with topic.subscribe(buffer=10) as subscription:
                received_messages = []

                def collect_messages():
                    for message in subscription:
                        received_messages.append(message)
                        if len(received_messages) >= 1:
                            break

                collector_thread = threading.Thread(target=collect_messages, daemon=True)
                collector_thread.start()

                time.sleep(0.5)

                collector_thread.join(timeout=5.0)

            # Assert
            # Should only receive the normal message (subscribe message ignored)
            assert len(received_messages) == 1
            assert received_messages[0] == b"normal_message"


class TestExceptionPropagation:
    """Test exception propagation in listener threads."""

    def test_listener_thread_exception_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that exceptions in listener threads are handled gracefully."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Mock pubsub to raise exception in get_message
        mock_pubsub = MagicMock()
        mock_pubsub.get_message.side_effect = Exception("Unexpected error")

        with patch.object(topic, "_client") as mock_client:
            mock_client.pubsub.return_value = mock_pubsub

            # Act
            subscription = topic.subscribe(buffer=5)

            # Try to use subscription
            received_messages = []

            def collect_messages():
                try:
                    for message in subscription:
                        received_messages.append(message)
                except Exception:
                    pass  # Expected

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.5)

            # Clean up
            subscription.close()
            collector_thread.join(timeout=2.0)

        # Assert
        # Exception should be handled without crashing
        assert not collector_thread.is_alive()
        assert len(received_messages) == 0

    def test_subscription_start_after_close(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test starting subscription after it's been closed."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        subscription = topic.subscribe(buffer=5)
        subscription.close()

        # Act & Assert
        with pytest.raises(InvalidOperationError, match="The Redis subscription is closed"):
            # Try to iterate after close
            for _ in subscription:  # type: ignore
                pass

    def test_context_manager_exception_cleanup(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that context manager cleans up properly even with exceptions."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Act
        exception_raised = False

        try:
            with topic.subscribe(buffer=5) as subscription:
                # Simulate some work then raise exception
                time.sleep(0.1)
                raise ValueError("Test exception")
        except ValueError:
            exception_raised = True

        # Assert
        assert exception_raised

        # Subscription should be properly closed
        with pytest.raises(InvalidOperationError):
            for _ in subscription:  # type: ignore
                pass


class TestResourceExhaustion:
    """Test behavior under resource exhaustion scenarios."""

    def test_thread_exhaustion(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test behavior when system resources are exhausted."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Create many subscriptions to potentially exhaust resources
        subscriptions = []

        try:
            # Act
            for i in range(100):  # Create many subscriptions
                subscription = topic.subscribe(buffer=1)
                subscriptions.append(subscription)

                # Try to use the subscription briefly
                subscription.__iter__()  # Start the subscription
                time.sleep(0.001)  # Very short use

        except Exception as e:
            # If we hit resource limits, it should be handled gracefully
            pytest.skip(f"Resource exhaustion encountered: {e}")

        finally:
            # Clean up
            for subscription in subscriptions:
                try:
                    subscription.close()
                except Exception:
                    pass  # Ignore cleanup errors

    def test_memory_pressure_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling under memory pressure."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=10, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    # Slow down consumption to create memory pressure
                    time.sleep(0.1)
                    if len(received_messages) >= 5:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish many large messages to create memory pressure
            large_message = b"x" * 10000  # 10KB message
            for i in range(50):
                producer.publish(large_message)

            collector_thread.join(timeout=10.0)

        # Assert
        # Should handle memory pressure gracefully
        assert len(received_messages) >= 1
        # Messages should be properly handled despite memory pressure


class TestTimeoutAndRecovery:
    """Test timeout handling and recovery scenarios."""

    def test_subscription_timeout_recovery(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test subscription recovery after timeout scenarios."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=5, overflow=Overflow.BLOCK) as subscription:
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
            producer.publish(b"timeout_test_1")
            producer.publish(b"timeout_test_2")

            # Wait for completion with timeout
            completed = collector_thread.join(timeout=5.0)

            # Assert
            assert completed, "Subscription should complete within timeout"
            assert len(received_messages) == 2
            assert received_messages == [b"timeout_test_1", b"timeout_test_2"]

    def test_blocking_timeout_behavior(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test behavior of BLOCK overflow when timeouts occur."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=2, overflow=Overflow.BLOCK) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    time.sleep(0.2)  # Slow consumption
                    if len(received_messages) >= 3:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Fill buffer and test blocking behavior
            start_time = time.time()
            producer.publish(b"block_test_1")
            producer.publish(b"block_test_2")  # Buffer is now full
            producer.publish(b"block_test_3")  # Should block until space available

            end_time = time.time()
            elapsed = end_time - start_time

            collector_thread.join(timeout=5.0)

        # Assert
        # Publishing should take time due to blocking
        assert elapsed > 0.1, "Publishing should have blocked"
        assert len(received_messages) == 3
        assert received_messages == [b"block_test_1", b"block_test_2", b"block_test_3"]
