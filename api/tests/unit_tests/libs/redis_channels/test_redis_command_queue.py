"""
Unit tests for Redis command queue implementation.
"""

from dataclasses import dataclass
from unittest.mock import Mock

import pytest
import redis

from libs.redis_channels.command_queue import RedisCommandQueue


@dataclass
class EnqueueTestCase:
    name: str
    command: bytes 
    expected_queue_size: int


def get_enqueue_test_cases() -> list[EnqueueTestCase]:
    """Get test cases for enqueue method."""
    return [
        EnqueueTestCase(
            name="simple_command",
            command=b'{"action": "pause", "node_id": "node_123"}',
            expected_queue_size=1,
        ),
        EnqueueTestCase(
            name="complex_command",
            command=b'{"action": "resume", "params": {"timeout": 30, "retry": true}, "metadata": ["tag1", "tag2"]}',
            expected_queue_size=3,
        ),
        EnqueueTestCase(
            name="empty_command",
            command=b'{}',
            expected_queue_size=1,
        ),
    ]


@dataclass
class DequeueTestCase:
    name: str
    timeout: float | None
    redis_return: tuple[bytes, bytes] | None
    expected_result: bytes | None
    expected_method: str  # "blpop" or "lpop"


def get_dequeue_test_cases() -> list[DequeueTestCase]:
    """Get test cases for dequeue method."""
    return [
        DequeueTestCase(
            name="immediate_dequeue_with_data",
            timeout=0,
            redis_return=b'{"action": "stop", "id": 456}',  # lpop returns just the value
            expected_result=b'{"action": "stop", "id": 456}',
            expected_method="lpop",
        ),
        DequeueTestCase(
            name="blocking_dequeue_with_data",
            timeout=5.0,
            redis_return=(b"queue_key", b'{"command": "restart"}'),
            expected_result=b'{"command": "restart"}',
            expected_method="blpop",
        ),
        DequeueTestCase(
            name="immediate_dequeue_empty_queue",
            timeout=0,
            redis_return=None,
            expected_result=None,
            expected_method="lpop",
        ),
        DequeueTestCase(
            name="blocking_dequeue_timeout",
            timeout=1.0,
            redis_return=None,
            expected_result=None,
            expected_method="blpop",
        ),
        DequeueTestCase(
            name="wait_forever",
            timeout=None,
            redis_return=(b"queue_key", b'{"waiting": "forever"}'),
            expected_result=b'{"waiting": "forever"}',
            expected_method="blpop",
        ),
    ]


class TestRedisCommandQueue:
    """Test RedisCommandQueue implementation."""

    def test_init(self):
        """Test queue initialization."""
        mock_redis = Mock(spec=redis.Redis)
        queue = RedisCommandQueue(mock_redis, "test_queue")
        
        assert queue._redis_client is mock_redis
        assert queue._key == "test_queue"

    @pytest.mark.parametrize("test_case", get_enqueue_test_cases(), ids=lambda tc: tc.name)
    def test_enqueue_success(self, test_case):
        """Test successful command enqueuing."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.rpush.return_value = test_case.expected_queue_size
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        queue.enqueue(test_case.command)
        
        mock_redis.rpush.assert_called_once_with("test_queue", test_case.command)

    def test_enqueue_redis_error(self):
        """Test enqueue with Redis error."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.rpush.side_effect = redis.RedisError("Connection failed")
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        
        with pytest.raises(redis.RedisError):
            queue.enqueue(b'{"action": "test"}')

    def test_enqueue_valid_string(self):
        """Test enqueue with string (should work as Redis handles string to bytes)."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.rpush.return_value = 1
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        
        # Test with string - should work
        queue.enqueue("test string")
        mock_redis.rpush.assert_called_once_with("test_queue", "test string")

    @pytest.mark.parametrize("test_case", get_dequeue_test_cases(), ids=lambda tc: tc.name)
    def test_dequeue_success(self, test_case):
        """Test successful command dequeuing."""
        mock_redis = Mock(spec=redis.Redis)
        
        if test_case.expected_method == "lpop":
            mock_redis.lpop.return_value = test_case.redis_return
        else:
            mock_redis.blpop.return_value = test_case.redis_return
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        result = queue.dequeue(test_case.timeout)
        
        assert result == test_case.expected_result
        
        if test_case.expected_method == "lpop":
            mock_redis.lpop.assert_called_once_with("test_queue")
        else:
            mock_redis.blpop.assert_called_once_with(["test_queue"], timeout=test_case.timeout)

    def test_dequeue_redis_error(self):
        """Test dequeue with Redis error."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.blpop.side_effect = redis.RedisError("Connection failed")
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        
        with pytest.raises(redis.RedisError):
            queue.dequeue(timeout=1.0)

    def test_dequeue_blocking_with_result(self):
        """Test blocking dequeue with result."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.blpop.return_value = (b"test_queue", b'{"valid": "json"}')
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        result = queue.dequeue(timeout=1.0)
        
        assert result == b'{"valid": "json"}'
        mock_redis.blpop.assert_called_once_with(["test_queue"], timeout=1.0)

    def test_peek_with_data(self):
        """Test peeking at queue with data."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.lindex.return_value = b'{"action": "peek_test", "priority": 1}'
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        result = queue.peek()
        
        assert result == b'{"action": "peek_test", "priority": 1}'
        mock_redis.lindex.assert_called_once_with("test_queue", 0)

    def test_peek_empty_queue(self):
        """Test peeking at empty queue."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.lindex.return_value = None
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        result = queue.peek()
        
        assert result is None
        mock_redis.lindex.assert_called_once_with("test_queue", 0)

    def test_peek_redis_error(self):
        """Test peek with Redis error."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.lindex.side_effect = redis.RedisError("Connection failed")
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        
        with pytest.raises(redis.RedisError):
            queue.peek()

    def test_peek_with_bytes_data(self):
        """Test peeking returns raw bytes data."""
        mock_redis = Mock(spec=redis.Redis)
        test_data = b'some raw bytes data'
        mock_redis.lindex.return_value = test_data
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        result = queue.peek()
        
        assert result == test_data
        mock_redis.lindex.assert_called_once_with("test_queue", 0)

    def test_size_with_items(self):
        """Test getting size of queue with items."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.llen.return_value = 5
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        result = queue.size()
        
        assert result == 5
        mock_redis.llen.assert_called_once_with("test_queue")

    def test_size_empty_queue(self):
        """Test getting size of empty queue."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.llen.return_value = 0
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        result = queue.size()
        
        assert result == 0
        mock_redis.llen.assert_called_once_with("test_queue")

    def test_size_redis_error(self):
        """Test size with Redis error."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.llen.side_effect = redis.RedisError("Connection failed")
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        
        with pytest.raises(redis.RedisError):
            queue.size()

    def test_clear_existing_queue(self):
        """Test clearing existing queue."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.delete.return_value = 1  # 1 key was deleted
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        queue.clear()
        
        mock_redis.delete.assert_called_once_with("test_queue")

    def test_clear_nonexistent_queue(self):
        """Test clearing non-existent queue."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.delete.return_value = 0  # 0 keys were deleted
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        queue.clear()
        
        mock_redis.delete.assert_called_once_with("test_queue")

    def test_clear_redis_error(self):
        """Test clear with Redis error."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.delete.side_effect = redis.RedisError("Connection failed")
        
        queue = RedisCommandQueue(mock_redis, "test_queue")
        
        with pytest.raises(redis.RedisError):
            queue.clear()

    def test_close(self):
        """Test closing queue."""
        mock_redis = Mock(spec=redis.Redis)
        queue = RedisCommandQueue(mock_redis, "test_queue")
        
        # Should not raise any error
        queue.close()

    def test_context_manager(self):
        """Test using queue as context manager."""
        mock_redis = Mock(spec=redis.Redis)
        
        with RedisCommandQueue(mock_redis, "test_queue") as queue:
            assert isinstance(queue, RedisCommandQueue)
        
        # Close should be called implicitly