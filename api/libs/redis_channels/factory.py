"""
Factory functions for creating Redis-based communication channels.
"""

import redis

from libs.redis_channels.broadcast_channel import BroadcastChannel, RedisBroadcastChannel
from libs.redis_channels.command_queue import CommandQueue, RedisCommandQueue


def create_broadcast_channel(redis_client: redis.Redis, key: str) -> BroadcastChannel:
    """
    Create a Redis-based broadcast channel.
    
    Args:
        redis_client: Redis client instance to use
        key: Channel key for Redis operations
        
    Returns:
        BroadcastChannel implementation using Redis Pub/Sub
    """
    return RedisBroadcastChannel(redis_client, key)


def create_command_queue(redis_client: redis.Redis, key: str) -> CommandQueue:
    """
    Create a Redis-based command queue.
    
    Args:
        redis_client: Redis client instance to use
        key: Queue key for Redis operations
        
    Returns:
        CommandQueue implementation using Redis List
    """
    return RedisCommandQueue(redis_client, key)