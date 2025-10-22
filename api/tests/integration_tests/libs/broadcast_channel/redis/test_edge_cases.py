"""
Edge cases tests for Redis broadcast channel implementation.

This module tests edge cases, boundary conditions, and unusual scenarios
including empty messages, large messages, rapid operations, and stress
testing scenarios.
"""

import threading
import time
from typing import Any

import pytest

from libs.broadcast_channel.channel import Overflow
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_data import (
    EDGE_CASE_MESSAGES,
    LARGE_MESSAGES,
    PERFORMANCE_TEST_CONFIGS,
    SPECIAL_MESSAGES,
    STRESS_TEST_CONFIGS,
    TOPIC_NAME_TEST_CASES,
    VERY_LARGE_MESSAGES,
)
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_helpers import (
    ConcurrentPublisher,
    SubscriptionMonitor,
    create_stress_test_messages,
    measure_throughput,
    validate_message_integrity,
)


class TestEmptyMessages:
    """Test handling of empty messages."""

    def test_empty_message_publish_subscribe(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test publishing and subscribing empty messages."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=10) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 3:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish empty messages
            producer.publish(b"")
            producer.publish(b"")
            producer.publish(b"")

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 3
        assert all(msg == b"" for msg in received_messages)

    def test_mixed_empty_and_non_empty_messages(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test mixing empty and non-empty messages."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=10) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 6:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish mixed messages
            producer.publish(b"")
            producer.publish(b"message1")
            producer.publish(b"")
            producer.publish(b"message2")
            producer.publish(b"")
            producer.publish(b"message3")

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 6
        expected = [b"", b"message1", b"", b"message2", b"", b"message3"]
        assert received_messages == expected


class TestLargeMessages:
    """Test handling of large messages."""

    def test_large_message_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of large messages."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=5) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= len(LARGE_MESSAGES):
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish large messages
            for message in LARGE_MESSAGES:
                producer.publish(message)

            collector_thread.join(timeout=10.0)  # Longer timeout for large messages

        # Assert
        assert len(received_messages) == len(LARGE_MESSAGES)
        assert received_messages == LARGE_MESSAGES

    def test_very_large_message_handling(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test handling of very large messages (100KB+)."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=3) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= len(VERY_LARGE_MESSAGES):
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.2)  # Longer setup time for very large messages

            # Publish very large messages
            for i, message in enumerate(VERY_LARGE_MESSAGES):
                print(f"Publishing very large message {i + 1} ({len(message)} bytes)")
                producer.publish(message)

            collector_thread.join(timeout=30.0)  # Very long timeout for very large messages

        # Assert
        assert len(received_messages) == len(VERY_LARGE_MESSAGES)
        for i, (received, expected) in enumerate(zip(received_messages, VERY_LARGE_MESSAGES)):
            assert len(received) == len(expected), f"Message {i + 1} length mismatch"
            assert received == expected, f"Message {i + 1} content mismatch"

    def test_multiple_large_messages_rapid_sequence(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test multiple large messages in rapid sequence."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Create multiple large messages
        large_messages = [b"x" * 50000 for _ in range(5)]  # 5 messages of 50KB each

        # Act
        with topic.subscribe(buffer=10, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= len(large_messages):
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.2)

            # Publish large messages rapidly
            for message in large_messages:
                producer.publish(message)

            collector_thread.join(timeout=15.0)

        # Assert
        assert len(received_messages) == len(large_messages)
        assert received_messages == large_messages


class TestSpecialCharacters:
    """Test handling of messages with special characters."""

    def test_unicode_messages(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test Unicode message handling."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        unicode_messages = [
            "Hello, 世界!".encode("utf-8"),
            "Café résumé naïve".encode("utf-8"),
            "🚀 Rocket ship 🌟".encode("utf-8"),
            "Русский текст".encode("utf-8"),
            "العربية النص".encode("utf-8"),
            "עברית טקסט".encode("utf-8"),
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

    def test_binary_data_messages(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test binary data message handling."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        binary_messages = [
            bytes(range(256)),  # All possible byte values
            b"\x00\x01\x02\x03\x04",  # Null bytes and control characters
            b"\xff\xfe\xfd\xfc\xfb",  # High byte values
            b"\x80\x81\x82\x83\x84",  # High ASCII
        ]

        # Act
        with topic.subscribe(buffer=10) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= len(binary_messages):
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            for message in binary_messages:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == len(binary_messages)
        assert received_messages == binary_messages

    def test_special_characters_in_messages(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test messages with special characters."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=10) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= len(SPECIAL_MESSAGES):
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            for message in SPECIAL_MESSAGES:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == len(SPECIAL_MESSAGES)
        assert received_messages == SPECIAL_MESSAGES


class TestRapidOperations:
    """Test rapid publish/subscribe cycles."""

    def test_rapid_subscription_creation_and_destruction(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test rapid creation and destruction of subscriptions."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Act
        subscription_count = 50
        created_subscriptions = []

        for i in range(subscription_count):
            subscription = topic.subscribe(buffer=5)
            created_subscriptions.append(subscription)

            # Immediately close some subscriptions
            if i % 2 == 0:
                subscription.close()

        # Close remaining subscriptions
        for subscription in created_subscriptions:
            try:
                subscription.close()
            except Exception:
                pass  # Ignore errors during cleanup

        # Assert
        # Should complete without errors
        assert len(created_subscriptions) == subscription_count

    def test_rapid_publish_subscribe_cycles(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test rapid publish/subscribe cycles."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        cycle_count = 20
        all_received_messages = []

        for cycle in range(cycle_count):
            with topic.subscribe(buffer=5) as subscription:
                received_messages = []

                def collect_messages():
                    for message in subscription:
                        received_messages.append(message)
                        if len(received_messages) >= 2:
                            break

                collector_thread = threading.Thread(target=collect_messages, daemon=True)
                collector_thread.start()

                time.sleep(0.01)  # Very short setup time

                # Publish messages for this cycle
                cycle_messages = [f"cycle_{cycle}_msg_{i}".encode() for i in range(2)]
                for message in cycle_messages:
                    producer.publish(message)

                collector_thread.join(timeout=1.0)
                all_received_messages.extend(received_messages)

        # Assert
        assert len(all_received_messages) == cycle_count * 2

        # Verify all messages were received in correct order
        expected_messages = []
        for cycle in range(cycle_count):
            expected_messages.extend([f"cycle_{cycle}_msg_{i}".encode() for i in range(2)])

        assert all_received_messages == expected_messages

    def test_burst_publishing(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test burst publishing of many messages."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=100, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    time.sleep(0.001)  # Fast consumption
                    if len(received_messages) >= 50:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Burst publish many messages
            burst_count = 100
            for i in range(burst_count):
                producer.publish(f"burst_msg_{i}".encode())

            collector_thread.join(timeout=5.0)

        # Assert
        # Should receive most messages (some may be dropped due to buffer overflow)
        assert len(received_messages) >= 40  # At least 40% of messages
        assert len(received_messages) <= 100  # But not more than published


class TestTopicNameEdgeCases:
    """Test edge cases for topic names."""

    @pytest.mark.parametrize("topic_name", TOPIC_NAME_TEST_CASES)
    def test_various_topic_names(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        topic_name: str,
    ) -> None:
        """Test various topic name formats."""
        # Arrange
        full_topic_name = f"{unique_topic}_{topic_name}"
        topic = broadcast_channel.topic(full_topic_name)
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

            # Publish test messages
            producer.publish(b"test_msg_1")
            producer.publish(b"test_msg_2")

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 2
        assert received_messages == [b"test_msg_1", b"test_msg_2"]

    def test_extremely_long_topic_name(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test extremely long topic names."""
        # Arrange
        long_topic_name = unique_topic + "_" + "x" * 1000  # Over 1000 characters
        topic = broadcast_channel.topic(long_topic_name)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=5) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= 1:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            producer.publish(b"long_topic_test")

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 1
        assert received_messages[0] == b"long_topic_test"


class TestEdgeCaseMessages:
    """Test edge case message scenarios."""

    @pytest.mark.parametrize("message", EDGE_CASE_MESSAGES)
    def test_edge_case_messages(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        message: bytes,
    ) -> None:
        """Test various edge case messages."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=5) as subscription:
            received_messages = []

            def collect_messages():
                for msg in subscription:
                    received_messages.append(msg)
                    if len(received_messages) >= 1:
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 1
        assert received_messages[0] == message

    def test_null_bytes_in_messages(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test messages with null bytes."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        messages_with_nulls = [
            b"prefix\x00suffix",
            b"\x00\x00\x00",
            b"message\x00\x00end",
            b"\x00",
            b"start\x00middle\x00end",
        ]

        # Act
        with topic.subscribe(buffer=10) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    if len(received_messages) >= len(messages_with_nulls):
                        break

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            for message in messages_with_nulls:
                producer.publish(message)

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == len(messages_with_nulls)
        assert received_messages == messages_with_nulls


class TestPerformanceAndStress:
    """Test performance and stress scenarios."""

    @pytest.mark.parametrize("config", PERFORMANCE_TEST_CONFIGS)
    def test_performance_scenarios(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        config: dict[str, Any],
    ) -> None:
        """Test various performance scenarios."""
        # Arrange
        topic = broadcast_channel.topic(f"{unique_topic}_{config['name']}")
        producer = topic.as_producer()

        # Create test messages
        test_messages = create_stress_test_messages(
            config["message_count"],
            config["message_size"],
        )

        # Act
        with topic.subscribe(buffer=100, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)
                    # Continue collecting to see performance

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Measure throughput
            def publish_operation():
                for message in test_messages:
                    producer.publish(message)

            ops_per_sec, total_ops = measure_throughput(publish_operation, duration=1.0)

            # Wait for some messages to be received
            time.sleep(0.5)

            collector_thread.join(timeout=5.0)

        # Assert
        assert total_ops > 0, "No operations performed"
        assert ops_per_sec > 0, "Zero operations per second"
        assert len(received_messages) > 0, "No messages received"

        print(
            f"Performance test '{config['name']}': {ops_per_sec:.2f} ops/sec, "
            f"{total_ops} total ops, {len(received_messages)} messages received"
        )

    @pytest.mark.parametrize("config", STRESS_TEST_CONFIGS)
    def test_stress_scenarios(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        config: dict[str, Any],
    ) -> None:
        """Test various stress scenarios."""
        # Arrange
        topic = broadcast_channel.topic(f"{unique_topic}_{config['name']}")

        # Act
        with topic.subscribe(buffer=100, overflow=Overflow.DROP_OLDEST) as subscription:
            monitor = SubscriptionMonitor(subscription, timeout=15.0)
            monitor.start_monitoring()

            # Start concurrent publishers
            publishers = []
            for i in range(config["publisher_count"]):
                producer = topic.as_producer()
                publisher = ConcurrentPublisher(
                    producer,
                    message_count=config["messages_per_publisher"],
                    delay=0.001,
                )
                publisher.start_publishers(thread_count=1)
                publishers.append(publisher)

            # Wait for publishers to complete
            all_completed = True
            for publisher in publishers:
                if not publisher.wait_for_completion(timeout=10.0):
                    all_completed = False

            # Wait for messages
            expected_total = config["publisher_count"] * config["messages_per_publisher"]
            monitor.wait_for_messages(min(expected_total // 2, 100), timeout=10.0)
            monitor.stop()

        # Assert
        assert all_completed, f"Not all publishers completed for {config['name']}"
        received_messages = monitor.get_messages()
        assert len(received_messages) > 0, f"No messages received for {config['name']}"

        # Validate message integrity
        all_sent_messages = []
        for publisher in publishers:
            all_sent_messages.extend(publisher.get_all_messages())

        integrity_result = validate_message_integrity(all_sent_messages, received_messages)
        # Due to stress and DROP_OLDEST, we expect some message loss but not too much
        loss_ratio = integrity_result["missing_count"] / len(all_sent_messages) if all_sent_messages else 0
        assert loss_ratio < 0.5, f"Too many messages lost: {loss_ratio:.2%}"

        print(
            f"Stress test '{config['name']}': {len(received_messages)}/{len(all_sent_messages)} "
            f"messages received ({loss_ratio:.2%} loss)"
        )


class TestResourceLimits:
    """Test behavior at resource limits."""

    def test_maximum_buffer_size(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test behavior with maximum buffer size."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        max_buffer_size = 10000

        # Act
        with topic.subscribe(buffer=max_buffer_size, overflow=Overflow.DROP_OLDEST) as subscription:
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
                producer.publish(f"max_buffer_{i}".encode())

            collector_thread.join(timeout=5.0)

        # Assert
        assert len(received_messages) == 100
        expected = [f"max_buffer_{i}".encode() for i in range(100)]
        assert received_messages == expected

    def test_minimum_performance_requirements(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test minimum performance requirements."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        with topic.subscribe(buffer=50, overflow=Overflow.DROP_OLDEST) as subscription:
            received_messages = []

            def collect_messages():
                for message in subscription:
                    received_messages.append(message)

            collector_thread = threading.Thread(target=collect_messages, daemon=True)
            collector_thread.start()

            time.sleep(0.1)

            # Publish messages at a reasonable rate
            message_count = 100
            start_time = time.time()

            for i in range(message_count):
                producer.publish(f"perf_test_{i}".encode())

            publish_time = time.time() - start_time

            # Wait for messages
            time.sleep(0.5)

            collector_thread.join(timeout=5.0)

        # Assert
        # Should publish at least 100 messages per second
        publish_rate = message_count / publish_time
        assert publish_rate >= 100, f"Publish rate too slow: {publish_rate:.2f} msg/sec"

        # Should receive a reasonable number of messages
        assert len(received_messages) >= 50, f"Too few messages received: {len(received_messages)}"
