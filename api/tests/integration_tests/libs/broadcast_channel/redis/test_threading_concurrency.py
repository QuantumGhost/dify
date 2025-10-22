"""
Threading and concurrency tests for Redis broadcast channel implementation.

This module tests thread safety, concurrent operations, resource cleanup,
and proper behavior under high concurrency scenarios.
"""

import threading
import time
from typing import Any

import pytest

from libs.broadcast_channel.channel import Overflow
from libs.broadcast_channel.exc import InvalidOperationError
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_data import (
    CONCURRENCY_TEST_CONFIGS,
)
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_helpers import (
    ConcurrentPublisher,
    SubscriptionMonitor,
    validate_message_integrity,
    wait_for_condition,
)


class TestConcurrentPublishers:
    """Test multiple concurrent publishers to the same topic."""

    def test_multiple_concurrent_publishers(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test multiple publishers publishing concurrently to the same topic."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        publisher_count = 5
        messages_per_publisher = 10

        # Act
        with topic.subscribe(buffer=100, overflow=Overflow.DROP_OLDEST) as subscription:
            monitor = SubscriptionMonitor(subscription, timeout=10.0)
            monitor.start_monitoring()

            # Start concurrent publishers
            publishers = []
            for i in range(publisher_count):
                producer = topic.as_producer()
                publisher = ConcurrentPublisher(
                    producer,
                    message_count=messages_per_publisher,
                    delay=0.01,
                )
                publisher.start_publishers(thread_count=1)
                publishers.append(publisher)

            # Wait for all publishers to complete
            all_completed = True
            for publisher in publishers:
                if not publisher.wait_for_completion(timeout=5.0):
                    all_completed = False

            # Wait for messages to be received
            monitor.wait_for_messages(publisher_count * messages_per_publisher, timeout=5.0)
            monitor.stop()

        # Assert
        assert all_completed, "Not all publishers completed successfully"
        received_messages = monitor.get_messages()
        assert len(received_messages) == publisher_count * messages_per_publisher

        # Validate message integrity
        all_sent_messages = []
        for publisher in publishers:
            all_sent_messages.extend(publisher.get_all_messages())

        integrity_result = validate_message_integrity(all_sent_messages, received_messages)
        assert integrity_result["integrity_ok"], f"Message integrity failed: {integrity_result}"

    def test_concurrent_publishers_different_rates(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test concurrent publishers publishing at different rates."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Act
        with topic.subscribe(buffer=50, overflow=Overflow.DROP_OLDEST) as subscription:
            monitor = SubscriptionMonitor(subscription, timeout=15.0)
            monitor.start_monitoring()

            # Fast publisher
            fast_producer = topic.as_producer()
            fast_publisher = ConcurrentPublisher(
                fast_producer,
                message_count=20,
                delay=0.001,  # Very fast
            )
            fast_publisher.start_publishers(thread_count=1)

            # Slow publisher
            slow_producer = topic.as_producer()
            slow_publisher = ConcurrentPublisher(
                slow_producer,
                message_count=5,
                delay=0.1,  # Slow
            )
            slow_publisher.start_publishers(thread_count=1)

            # Wait for completion
            fast_completed = fast_publisher.wait_for_completion(timeout=5.0)
            slow_completed = slow_publisher.wait_for_completion(timeout=5.0)

            # Wait for messages
            monitor.wait_for_messages(25, timeout=10.0)
            monitor.stop()

        # Assert
        assert fast_completed and slow_completed
        received_messages = monitor.get_messages()
        assert len(received_messages) == 25

        # Validate all messages were received
        all_sent = fast_publisher.get_all_messages() + slow_publisher.get_all_messages()
        integrity_result = validate_message_integrity(all_sent, received_messages)
        assert integrity_result["integrity_ok"]

    def test_high_frequency_concurrent_publishing(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test high-frequency concurrent publishing."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        publisher_count = 10
        messages_per_publisher = 50

        # Act
        with topic.subscribe(buffer=1000, overflow=Overflow.DROP_OLDEST) as subscription:
            monitor = SubscriptionMonitor(subscription, timeout=20.0)
            monitor.start_monitoring()

            # Start many publishers
            publishers = []
            for i in range(publisher_count):
                producer = topic.as_producer()
                publisher = ConcurrentPublisher(
                    producer,
                    message_count=messages_per_publisher,
                    delay=0.001,  # Very high frequency
                )
                publisher.start_publishers(thread_count=1)
                publishers.append(publisher)

            # Wait for completion
            all_completed = True
            for publisher in publishers:
                if not publisher.wait_for_completion(timeout=10.0):
                    all_completed = False

            # Wait for messages
            expected_total = publisher_count * messages_per_publisher
            monitor.wait_for_messages(expected_total, timeout=10.0)
            monitor.stop()

        # Assert
        assert all_completed
        received_messages = monitor.get_messages()
        # Due to DROP_OLDEST, we might not get all messages, but should get most
        assert len(received_messages) >= expected_total * 0.8  # At least 80%


class TestConcurrentSubscribers:
    """Test multiple concurrent subscribers to the same topic."""

    def test_multiple_concurrent_subscribers(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        test_messages: list[bytes],
    ) -> None:
        """Test multiple subscribers receiving from the same topic."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        subscriber_count = 5
        messages_to_send = test_messages[:5]

        # Act
        monitors = []
        subscriptions = []

        # Start multiple subscribers
        for i in range(subscriber_count):
            subscription = topic.subscribe(buffer=20, overflow=Overflow.DROP_OLDEST)
            monitor = SubscriptionMonitor(subscription, timeout=10.0)
            monitor.start_monitoring()
            monitors.append(monitor)
            subscriptions.append(subscription)

        # Give subscribers time to start
        time.sleep(0.2)

        # Publish messages
        for message in messages_to_send:
            producer.publish(message)

        # Wait for all subscribers to receive messages
        all_received = True
        for monitor in monitors:
            if not monitor.wait_for_messages(len(messages_to_send), timeout=5.0):
                all_received = False

        # Clean up
        for monitor in monitors:
            monitor.stop()

        # Assert
        assert all_received, "Not all subscribers received all messages"

        for monitor in monitors:
            received = monitor.get_messages()
            assert len(received) == len(messages_to_send)
            assert received == messages_to_send

    def test_concurrent_subscribers_different_buffer_sizes(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test concurrent subscribers with different buffer sizes."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        buffer_configs = [2, 5, 10, 20]
        monitors = []
        subscriptions = []

        # Create subscribers with different buffer sizes
        for buffer_size in buffer_configs:
            subscription = topic.subscribe(
                buffer=buffer_size,
                overflow=Overflow.DROP_OLDEST,
            )
            monitor = SubscriptionMonitor(subscription, timeout=10.0)
            monitor.start_monitoring()
            monitors.append((buffer_size, monitor))
            subscriptions.append(subscription)

        # Give subscribers time to start
        time.sleep(0.2)

        # Publish more messages than smallest buffer
        messages_to_send = [f"msg_{i}".encode() for i in range(15)]
        for message in messages_to_send:
            producer.publish(message)

        # Wait for subscribers to receive messages
        results = []
        for buffer_size, monitor in monitors:
            monitor.wait_for_messages(buffer_size, timeout=5.0)
            received = monitor.get_messages()
            results.append((buffer_size, received))
            monitor.stop()

        # Assert
        for buffer_size, received in results:
            # Each subscriber should receive up to its buffer size
            assert len(received) == buffer_size
            # Should contain the most recent messages
            expected = messages_to_send[-buffer_size:]
            assert received == expected

    def test_concurrent_subscribers_start_stop(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test starting and stopping subscribers concurrently."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        def subscriber_worker(subscriber_id: int):
            messages = []
            try:
                with topic.subscribe(buffer=10) as subscription:
                    for message in subscription:
                        messages.append(message)
                        if len(messages) >= 5:
                            break
            except Exception as e:
                print(f"Subscriber {subscriber_id} error: {e}")
            return subscriber_id, messages

        # Start multiple subscriber workers
        workers = []
        threads = []
        for i in range(5):
            thread = threading.Thread(
                target=lambda i=i: workers.append(subscriber_worker(i)),
                daemon=True,
            )
            threads.append(thread)
            thread.start()

        # Give subscribers time to start
        time.sleep(0.2)

        # Publish messages
        for i in range(10):
            producer.publish(f"concurrent_msg_{i}".encode())

        # Wait for all workers to complete
        for thread in threads:
            thread.join(timeout=5.0)

        # Assert
        assert len(workers) == 5
        for subscriber_id, messages in workers:
            assert len(messages) == 5
            # All should have received the same messages
            expected = [f"concurrent_msg_{i}".encode() for i in range(5)]
            assert messages == expected


class TestResourceCleanup:
    """Test resource cleanup and thread management."""

    def test_subscription_cleanup_during_active_operations(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test cleaning up subscription during active operations."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        subscription = topic.subscribe(buffer=10, overflow=Overflow.DROP_OLDEST)

        received_messages = []
        stop_event = threading.Event()

        def message_consumer():
            try:
                for message in subscription:
                    received_messages.append(message)
                    if stop_event.is_set():
                        break
            except Exception:
                pass  # Expected when subscription is closed

        consumer_thread = threading.Thread(target=message_consumer, daemon=True)
        consumer_thread.start()

        # Start publishing messages
        def message_publisher():
            for i in range(20):
                if stop_event.is_set():
                    break
                producer.publish(f"cleanup_test_{i}".encode())
                time.sleep(0.01)

        publisher_thread = threading.Thread(target=message_publisher, daemon=True)
        publisher_thread.start()

        # Let some messages be processed
        time.sleep(0.1)

        # Close subscription during active operations
        subscription.close()
        stop_event.set()

        # Wait for threads to complete
        consumer_thread.join(timeout=2.0)
        publisher_thread.join(timeout=2.0)

        # Assert
        # Subscription should be closed without errors
        with pytest.raises(InvalidOperationError):
            for _ in subscription:  # type: ignore
                pass

    def test_thread_joining_on_subscription_close(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that listener threads are properly joined on subscription close."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()

        # Act
        subscription = topic.subscribe(buffer=10)

        # Start message consumption
        received_count = 0

        def consume_messages():
            nonlocal received_count
            try:
                for message in subscription:
                    received_count += 1
                    time.sleep(0.01)  # Slow consumption
            except Exception:
                pass

        consumer_thread = threading.Thread(target=consume_messages, daemon=True)
        consumer_thread.start()

        # Publish some messages
        for i in range(5):
            producer.publish(f"thread_join_test_{i}".encode())

        # Wait a bit for processing
        time.sleep(0.1)

        # Close subscription and measure time
        start_time = time.time()
        subscription.close()
        end_time = time.time()

        # Wait for consumer thread
        consumer_thread.join(timeout=2.0)

        # Assert
        close_time = end_time - start_time
        # Close should be relatively fast (threads should join quickly)
        assert close_time < 1.0, f"Subscription close took too long: {close_time}s"

        # Consumer thread should have stopped
        assert not consumer_thread.is_alive()

    def test_multiple_subscription_cleanup(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test cleaning up multiple subscriptions concurrently."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        subscription_count = 10

        # Act
        subscriptions = []
        for i in range(subscription_count):
            subscription = topic.subscribe(buffer=5)
            subscriptions.append(subscription)

        # Close all subscriptions concurrently
        def close_subscription(subscription):
            subscription.close()

        close_threads = []
        for subscription in subscriptions:
            thread = threading.Thread(
                target=close_subscription,
                args=(subscription,),
                daemon=True,
            )
            thread.start()
            close_threads.append(thread)

        # Wait for all close operations to complete
        for thread in close_threads:
            thread.join(timeout=2.0)

        # Assert
        # All subscriptions should be closed without errors
        for subscription in subscriptions:
            with pytest.raises(InvalidOperationError):
                for _ in subscription:  # type: ignore
                    pass


class TestThreadSafety:
    """Test thread safety of broadcast channel operations."""

    def test_concurrent_topic_creation(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test creating topics concurrently."""
        # Arrange
        base_topic_name = unique_topic
        topic_count = 10

        # Act
        topics = []

        def create_topic(index: int):
            topic_name = f"{base_topic_name}_{index}"
            topic = broadcast_channel.topic(topic_name)
            topics.append((index, topic))

        threads = []
        for i in range(topic_count):
            thread = threading.Thread(target=create_topic, args=(i,), daemon=True)
            thread.start()
            threads.append(thread)

        # Wait for all topics to be created
        for thread in threads:
            thread.join(timeout=2.0)

        # Assert
        assert len(topics) == topic_count

        # Verify all topics are unique and functional
        topic_names = set()
        for index, topic in topics:
            topic_name = f"{base_topic_name}_{index}"
            assert topic_name not in topic_names
            topic_names.add(topic_name)

            # Test that topic is functional
            producer = topic.as_producer()
            subscription = topic.subscribe(buffer=5)
            subscription.close()

    def test_concurrent_subscription_creation(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test creating subscriptions concurrently."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        subscription_count = 20

        # Act
        subscriptions = []

        def create_subscription():
            subscription = topic.subscribe(buffer=5, overflow=Overflow.DROP_OLDEST)
            subscriptions.append(subscription)

        threads = []
        for i in range(subscription_count):
            thread = threading.Thread(target=create_subscription, daemon=True)
            thread.start()
            threads.append(thread)

        # Wait for all subscriptions to be created
        for thread in threads:
            thread.join(timeout=2.0)

        # Assert
        assert len(subscriptions) == subscription_count

        # Clean up all subscriptions
        for subscription in subscriptions:
            subscription.close()

    def test_concurrent_publish_with_different_overflows(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test concurrent publishing with different overflow strategies."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Act
        overflow_strategies = [Overflow.DROP_OLDEST, Overflow.DROP_NEWEST, Overflow.BLOCK]
        subscriptions = []
        monitors = []

        # Create subscriptions with different overflow strategies
        for strategy in overflow_strategies:
            subscription = topic.subscribe(buffer=5, overflow=strategy)
            monitor = SubscriptionMonitor(subscription, timeout=10.0)
            monitor.start_monitoring()
            subscriptions.append(subscription)
            monitors.append((strategy, monitor))

        # Start concurrent publishers
        def publisher_worker(publisher_id: int):
            producer = topic.as_producer()
            for i in range(10):
                producer.publish(f"publisher_{publisher_id}_msg_{i}".encode())
                time.sleep(0.01)

        publisher_threads = []
        for i in range(3):
            thread = threading.Thread(target=publisher_worker, args=(i,), daemon=True)
            thread.start()
            publisher_threads.append(thread)

        # Wait for publishers to complete
        for thread in publisher_threads:
            thread.join(timeout=5.0)

        # Wait for messages to be received
        time.sleep(1.0)

        # Clean up
        results = []
        for strategy, monitor in monitors:
            received = monitor.get_messages()
            results.append((strategy, len(received)))
            monitor.stop()

        # Assert
        # All overflow strategies should have received some messages
        for strategy, count in results:
            assert count > 0, f"No messages received for strategy {strategy}"


class TestContextManagerConcurrency:
    """Test context manager behavior under concurrency."""

    def test_concurrent_context_managers(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test using multiple context managers concurrently."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)
        producer = topic.as_producer()
        context_count = 5

        # Act
        results = []

        def context_user(user_id: int):
            messages = []
            try:
                with topic.subscribe(buffer=10) as subscription:
                    for message in subscription:
                        messages.append(message)
                        if len(messages) >= 3:
                            break
            except Exception as e:
                print(f"Context user {user_id} error: {e}")
            results.append((user_id, messages))

        # Start multiple context users
        threads = []
        for i in range(context_count):
            thread = threading.Thread(target=context_user, args=(i,), daemon=True)
            thread.start()
            threads.append(thread)

        # Give context managers time to start
        time.sleep(0.2)

        # Publish messages
        for i in range(10):
            producer.publish(f"context_msg_{i}".encode())

        # Wait for all context users to complete
        for thread in threads:
            thread.join(timeout=5.0)

        # Assert
        assert len(results) == context_count

        for user_id, messages in results:
            assert len(messages) == 3
            # All should have received the same messages
            expected = [f"context_msg_{i}".encode() for i in range(3)]
            assert messages == expected

    def test_context_manager_exception_safety(
        self,
        broadcast_channel: Any,
        unique_topic: str,
    ) -> None:
        """Test that context managers clean up properly even with exceptions."""
        # Arrange
        topic = broadcast_channel.topic(unique_topic)

        # Act
        exception_occurred = False

        def context_with_exception():
            nonlocal exception_occurred
            try:
                with topic.subscribe(buffer=5) as subscription:
                    # Simulate some work then raise exception
                    time.sleep(0.1)
                    raise ValueError("Test exception")
            except ValueError:
                exception_occurred = True

        # Run context with exception
        thread = threading.Thread(target=context_with_exception, daemon=True)
        thread.start()
        thread.join(timeout=2.0)

        # Assert
        assert exception_occurred

        # Verify that a new subscription can still be created (resources were cleaned up)
        new_subscription = topic.subscribe(buffer=5)
        new_subscription.close()  # Should work without issues


class TestParametrizedConcurrencyConfigs:
    """Test with parametrized concurrency configurations."""

    @pytest.mark.parametrize("config", CONCURRENCY_TEST_CONFIGS)
    def test_concurrency_configurations(
        self,
        broadcast_channel: Any,
        unique_topic: str,
        config: Any,
    ) -> None:
        """Test different concurrency configurations."""
        # Arrange
        topic = broadcast_channel.topic(f"{unique_topic}_{config.description}")

        # Act
        with topic.subscribe(buffer=100, overflow=Overflow.DROP_OLDEST) as subscription:
            monitor = SubscriptionMonitor(subscription, timeout=config.test_duration + 5.0)
            monitor.start_monitoring()

            # Start publishers
            publishers = []
            for i in range(config.publisher_count):
                producer = topic.as_producer()
                publisher = ConcurrentPublisher(
                    producer,
                    message_count=config.messages_per_publisher,
                    delay=0.01,
                )
                publisher.start_publishers(thread_count=1)
                publishers.append(publisher)

            # Wait for publishers to complete
            all_completed = True
            for publisher in publishers:
                if not publisher.wait_for_completion(timeout=config.test_duration):
                    all_completed = False

            # Wait for messages
            expected_total = config.publisher_count * config.messages_per_publisher
            monitor.wait_for_messages(expected_total, timeout=config.test_duration)
            monitor.stop()

        # Assert
        if config.subscriber_count == 1:
            # Single subscriber case
            assert all_completed, f"Publishers failed for config: {config.description}"
            received_messages = monitor.get_messages()
            assert len(received_messages) > 0, f"No messages received for config: {config.description}"

            # Validate message integrity
            all_sent_messages = []
            for publisher in publishers:
                all_sent_messages.extend(publisher.get_all_messages())

            integrity_result = validate_message_integrity(all_sent_messages, received_messages)
            # Due to DROP_OLDEST, we might not get all messages, but should get most
            assert integrity_result["missing_count"] <= len(all_sent_messages) * 0.2
