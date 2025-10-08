"""
Redis-based command queue for FIFO command processing.
"""

import logging
from abc import ABC, abstractmethod

import redis

logger = logging.getLogger(__name__)


class CommandQueue(ABC):
    """
    Interface for FIFO command queue.

    Used to send control commands from external systems to GraphEngine.
    Uses first-in-first-out ordering based on Redis List.
    """

    @abstractmethod
    def enqueue(self, command: bytes) -> None:
        """
        Enqueue a command to the given key.

        Args:
            key: The queue key to enqueue to
            command: The command data to enqueue
        """
        pass

    @abstractmethod
    def dequeue(self, timeout: int | None = None) -> bytes | None:
        """
        Dequeue a command from the given key.

        Args:
            key: The queue key to dequeue from
            timeout: Maximum time in seconds to wait for a command (0 = no wait, None = wait forever)

        Returns:
            The dequeued command data, or None if timeout reached
        """
        pass

    @abstractmethod
    def peek(self) -> bytes | None:
        """
        Peek at the next command without removing it.

        Args:
            key: The queue key to peek at

        Returns:
            The next command data, or None if queue is empty
        """
        pass

    @abstractmethod
    def size(self) -> int:
        """
        Get the size of the queue for the given key.

        Args:
            key: The queue key to check

        Returns:
            Number of commands in the queue
        """
        pass

    @abstractmethod
    def clear(self):
        """
        Clear all commands from the queue for the given key.

        Args:
            key: The queue key to clear

        Returns:
            Number of commands that were removed
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the command queue and clean up resources."""
        pass

    def __enter__(self):
        """Context manager entry."""
        return self

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        pass


class RedisCommandQueue(CommandQueue):
    """
    Redis List based FIFO command queue implementation.

    Uses Redis LIST data structure with LPUSH/BRPOP for FIFO ordering.
    Commands are JSON-serialized before storage and deserialized on retrieval.
    """

    def __init__(self, redis_client: redis.Redis, key: str):
        """
        Initialize the Redis command queue.

        Args:
            redis_client: Redis client instance to use for list operations
        """
        self._redis_client = redis_client
        self._key = key

    def enqueue(self, command: bytes) -> None:
        """
        Enqueue a command to the given key using Redis LPUSH.

        Args:
            key: The queue key to enqueue to
            command: The command data to enqueue (will be JSON serialized)

        Raises:
            redis.RedisError: If Redis operation fails
            TypeError: If command cannot be serialized to JSON
        """
        result = self._redis_client.rpush(self._key, command)
        logger.debug("Enqueued command to queue %s, queue size now: %d", self._key, result)

    def dequeue(self, timeout: int | None = None) -> bytes | None:
        """
        Dequeue a command from the given key using Redis BLPOP or LPOP.

        Args:
            timeout: Maximum time to wait for a command in seconds
                    (0 = no wait, None = wait forever)

        Returns:
            The dequeued command data, or None if timeout reached

        Raises:
            redis.RedisError: If Redis operation fails
        """
        if timeout == 0:
            return self._redis_client.lpop(self._key)

        # Use blocking dequeue
        result = self._redis_client.blpop([self._key], timeout=timeout)
        if result is None:
            logger.debug("Dequeue from list %s timed out", self._key)
            return None
        _, payload = result
        return payload

    def peek(self) -> bytes | None:
        """
        Peek at the next command without removing it using Redis LINDEX.

        Args:
            key: The queue key to peek at

        Returns:
            The next command data, or None if queue is empty

        Raises:
            redis.RedisError: If Redis operation fails
            json.JSONDecodeError: If command cannot be deserialized from JSON
        """
        # Get the leftmost element (next to be dequeued) without removing it
        payload = self._redis_client.lindex(self._key, 0)

        if payload is None:
            logger.debug("Queue %s is empty", self._key)
            return None

        return payload

    def size(self) -> int:
        """
        Get the size of the queue using Redis LLEN.

        Args:
            key: The queue key to check

        Returns:
            Number of commands in the queue

        Raises:
            redis.RedisError: If Redis operation fails
        """
        return self._redis_client.llen(self._key)

    def clear(self):
        """
        Clear all commands from the queue using Redis DEL.

        Args:
            key: The queue key to clear

        Returns:
            Number of commands that were removed (0 or 1 based on key existence)

        Raises:
            redis.RedisError: If Redis operation fails
        """
        # Delete the entire list
        self._redis_client.delete(self._key)
        logger.debug("Cleared queue %s", self._key)

    def close(self) -> None:
        """
        Close the command queue and clean up resources.

        Note: Redis client connections are typically managed externally,
        so this is mainly for interface compliance.
        """
        logger.debug("Redis command queue closed")
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure cleanup."""
        self.close()
