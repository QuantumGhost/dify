"""
Redis-based broadcast channel for Pub/Sub messaging.
"""

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator

import redis
from redis.client import PubSub

logger = logging.getLogger(__name__)


class BroadcastChannel(ABC):
    """
    Interface for publish/subscribe broadcast channel.

    Used by GraphEngine to publish events to all subscribed APIs.
    Provides "at most once" delivery semantics.

    This class is not safe for concurrent use.
    """

    @abstractmethod
    def publish(self, message: bytes) -> None:
        """
        Publish a message to the channel the instance associated with.

        Args:
            message: The message data to publish
        """
        pass

    @abstractmethod
    def subscribe(self) -> Iterator[bytes]:
        """
        Subscribe to messages for the channel the instance associated with.

        Yields:
            Messages published to the channel
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the broadcast channel and clean up resources."""
        pass

    def __enter__(self) -> Iterator[bytes]:
        """Context manager entry."""
        return self.subscribe()

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit."""
        self.close()
        return False


class InvalidOperationError(Exception):
    pass


class RedisBroadcastChannel(BroadcastChannel):
    """
    Redis Pub/Sub based broadcast channel implementation.

    Provides "at most once" delivery semantics for messages published to channels.
    Uses Redis PUBLISH/SUBSCRIBE commands for real-time message delivery.
    """

    def __init__(self, redis_client: redis.Redis, key: str, cancel: threading.Event | None = None):
        """
        Initialize the Redis broadcast channel.

        Args:
            redis_client: Redis client instance to use for pub/sub operations
        """
        self._redis_client = redis_client
        self._key = key
        self._pubsub: PubSub | None = None
        self._cancel = cancel or threading.Event()
        self._closed = False

    def publish(self, message: bytes) -> None:
        """
        Publish a message to the given key using Redis PUBLISH.

        Args:
            message: The raw bytes message data to publish

        Raises:
            redis.RedisError: If Redis operation fails
        """
        self._redis_client.publish(self._key, message)

    def subscribe(self) -> Iterator[bytes]:
        """
        Subscribe to messages for the given key using Redis SUBSCRIBE.

        Yields:
            Raw bytes messages published to the channel

        Raises:
            InvalidOperationError: If Redis operation fails
            RuntimeError: If already subscribed to channels with different pubsub instance
        """
        if self._closed:
            raise InvalidOperationError("The RedisBroadcastChannel instance is closed")

        # Initialize pubsub if not already done
        if self._pubsub is None:
            self._pubsub = self._redis_client.pubsub()
            self._pubsub.subscribe(self._key)
            logger.debug("Subscribed to channel %s", self._key)
        else:
            raise InvalidOperationError(f"Currently RedisBroadcastChannel is already subscribing {self._key}")

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

    def close(self) -> None:
        """
        Close the broadcast channel and clean up all subscriptions.

        Raises:
            redis.RedisError: If Redis cleanup operations fail
        """
        if self._closed:
            raise InvalidOperationError("BroadcastChannel is already closed")

        if self._pubsub is not None:
            self._pubsub.unsubscribe(self._key)
            logger.debug("Unsubscribed from channel %s", self._key)
            # Close the pubsub connection
            self._pubsub.close()
            self._pubsub = None

        self._closed = True
        logger.debug("Closed Redis broadcast channel")
