"""
Pytest fixtures and configuration for Redis broadcast channel integration tests.

This module provides shared fixtures for Redis client setup, broadcast channel
instances, and test utilities to ensure consistent test isolation and setup.
"""

import logging
import secrets
import threading
import time
from collections.abc import Generator
from typing import Any

import pytest
from redis import Redis
from testcontainers.redis import RedisContainer

from libs.broadcast_channel.channel import Overflow
from libs.broadcast_channel.redis.channel import BroadcastChannel

_logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer, None, None]:
    """
    Provide a Redis container for integration testing.

    This fixture starts a Redis container using testcontainers and yields
    the container instance. The container is automatically cleaned up
    after all tests complete.

    Yields:
        RedisContainer: The running Redis container
    """
    _logger.info("Starting Redis container for broadcast channel tests...")

    container = RedisContainer(image="redis:7-alpine", port=6379)
    container.start()

    # Wait for Redis to be ready
    redis_host = container.get_container_host_ip()
    redis_port = container.get_exposed_port(6379)

    # Test connection to ensure Redis is ready
    max_retries = 30
    for attempt in range(max_retries):
        try:
            test_client = Redis(host=redis_host, port=redis_port, decode_responses=False)
            test_client.ping()
            _logger.info(f"Redis container ready at {redis_host}:{redis_port}")
            break
        except Exception as e:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Redis container not ready after {max_retries} attempts: {e}")
            time.sleep(0.5)

    try:
        yield container
    finally:
        _logger.info("Stopping Redis container...")
        container.stop()


@pytest.fixture
def redis_client(redis_container: RedisContainer) -> Generator[Redis, None, None]:
    """
    Provide a Redis client connected to the test container.

    This fixture creates a Redis client instance connected to the
    Redis container provided by the redis_container fixture.

    Args:
        redis_container: The Redis container fixture

    Yields:
        Redis: A Redis client instance
    """
    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)

    client = Redis(
        host=redis_host,
        port=redis_port,
        decode_responses=False,  # Keep bytes for binary data
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )

    # Test connection
    client.ping()

    try:
        yield client
    finally:
        # Clean up any data left by tests
        try:
            client.flushdb()
        except Exception:
            pass  # Ignore cleanup errors
        client.close()


@pytest.fixture
def broadcast_channel(redis_client: Redis) -> BroadcastChannel:
    """
    Provide a BroadcastChannel instance for testing.

    This fixture creates a BroadcastChannel instance using the Redis client
    from the redis_client fixture.

    Args:
        redis_client: The Redis client fixture

    Returns:
        BroadcastChannel: A broadcast channel instance
    """
    return BroadcastChannel(redis_client)


@pytest.fixture
def unique_topic() -> Generator[str, None, None]:
    """
    Provide a unique topic name for each test.

    This fixture generates a unique topic name for each test to ensure
    test isolation and prevent interference between tests.

    Yields:
        str: A unique topic name
    """
    topic = f"test_topic_{secrets.token_hex(8)}"
    yield topic


@pytest.fixture(
    params=[
        Overflow.DROP_OLDEST,
        Overflow.DROP_NEWEST,
        Overflow.BLOCK,
    ]
)
def overflow_strategy(request: Any) -> Generator[Overflow, None, None]:
    """
    Parametrize tests with different overflow strategies.

    This fixture provides different overflow strategies for testing
    buffer management behavior.

    Args:
        request: Pytest request object

    Yields:
        Overflow: An overflow strategy
    """
    yield request.param


@pytest.fixture
def small_buffer_size() -> int:
    """
    Provide a small buffer size for testing overflow behavior.

    Returns:
        int: A small buffer size (3)
    """
    return 3


@pytest.fixture
def medium_buffer_size() -> int:
    """
    Provide a medium buffer size for general testing.

    Returns:
        int: A medium buffer size (10)
    """
    return 10


@pytest.fixture
def large_buffer_size() -> int:
    """
    Provide a large buffer size for performance testing.

    Returns:
        int: A large buffer size (1000)
    """
    return 1000


class MessageCollector:
    """
    Utility class for collecting messages from subscriptions in tests.

    This class provides a thread-safe way to collect messages from
    subscription iterators and wait for specific conditions.
    """

    def __init__(self, timeout: float = 5.0):
        """
        Initialize the message collector.

        Args:
            timeout: Default timeout for wait operations
        """
        self.messages: list[bytes] = []
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._timeout = timeout
        self._completed = False

    def collect_messages(self, subscription) -> None:
        """
        Collect messages from a subscription in a separate thread.

        Args:
            subscription: The subscription to collect messages from
        """

        def _collector():
            try:
                for message in subscription:
                    with self._lock:
                        self.messages.append(message)
                        self._condition.notify_all()
            except Exception as e:
                _logger.error(f"Error collecting messages: {e}")
            finally:
                with self._lock:
                    self._completed = True
                    self._condition.notify_all()

        thread = threading.Thread(target=_collector, daemon=True)
        thread.start()

    def wait_for_messages(self, count: int, timeout: float | None = None) -> bool:
        """
        Wait for a specific number of messages to be collected.

        Args:
            count: Number of messages to wait for
            timeout: Timeout in seconds (uses default if None)

        Returns:
            bool: True if the expected number of messages were received
        """
        if timeout is None:
            timeout = self._timeout

        deadline = time.time() + timeout

        with self._condition:
            while len(self.messages) < count and not self._completed:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)

            return len(self.messages) >= count

    def get_messages(self) -> list[bytes]:
        """
        Get all collected messages.

        Returns:
            list[bytes]: Copy of collected messages
        """
        with self._lock:
            return self.messages.copy()

    def clear(self) -> None:
        """Clear all collected messages."""
        with self._lock:
            self.messages.clear()

    def is_completed(self) -> bool:
        """
        Check if message collection is completed.

        Returns:
            bool: True if collection is completed
        """
        with self._lock:
            return self._completed


@pytest.fixture
def message_collector() -> Generator[MessageCollector, None, None]:
    """
    Provide a MessageCollector instance for testing.

    Yields:
        MessageCollector: A message collector instance
    """
    collector = MessageCollector()
    yield collector


@pytest.fixture
def test_messages() -> list[bytes]:
    """
    Provide a set of test messages for testing.

    Returns:
        list[bytes]: List of test messages
    """
    return [
        b"test_message_1",
        b"test_message_2",
        b"test_message_3",
        b"test_message_4",
        b"test_message_5",
        b"",  # Empty message
        "unicode_test_你好".encode("utf-8"),  # Unicode message
        b"large_message_" + b"x" * 1000,  # Large message
    ]


@pytest.fixture
def binary_test_messages() -> list[bytes]:
    """
    Provide binary test messages for testing.

    Returns:
        list[bytes]: List of binary test messages
    """
    return [
        bytes(range(256)),  # All byte values
        b"\x00\x01\x02\x03\x04",  # Null bytes and control characters
        b"\xff\xfe\xfd\xfc\xfb",  # High byte values
    ]
