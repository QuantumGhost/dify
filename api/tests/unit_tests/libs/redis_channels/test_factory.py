"""
Unit tests for Redis channels factory functions.
"""

from unittest.mock import Mock

import redis

from libs.redis_channels.broadcast_channel import BroadcastChannel, RedisBroadcastChannel
from libs.redis_channels.command_queue import CommandQueue, RedisCommandQueue
from libs.redis_channels.factory import create_broadcast_channel, create_command_queue


class TestFactory:
    """Test factory functions."""

    def test_create_broadcast_channel(self):
        """Test creating broadcast channel."""
        mock_redis = Mock(spec=redis.Redis)
        
        channel = create_broadcast_channel(mock_redis, "test_channel")
        
        assert isinstance(channel, BroadcastChannel)
        assert isinstance(channel, RedisBroadcastChannel)
        assert channel._redis_client is mock_redis
        assert channel._key == "test_channel"

    def test_create_command_queue(self):
        """Test creating command queue."""
        mock_redis = Mock(spec=redis.Redis)
        
        queue = create_command_queue(mock_redis, "test_queue")
        
        assert isinstance(queue, CommandQueue)
        assert isinstance(queue, RedisCommandQueue)
        assert queue._redis_client is mock_redis
        assert queue._key == "test_queue"