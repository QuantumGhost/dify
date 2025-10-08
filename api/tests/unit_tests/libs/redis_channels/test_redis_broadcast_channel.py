"""
Unit tests for Redis broadcast channel implementation.
"""

from dataclasses import dataclass
from unittest.mock import Mock

import pytest
import redis

from libs.redis_channels.broadcast_channel import RedisBroadcastChannel


@dataclass
class PublishTestCase:
    name: str
    message: bytes
    expected_subscribers: int


def get_publish_test_cases() -> list[PublishTestCase]:
    """Get test cases for publish method."""
    return [
        PublishTestCase(
            name="simple_bytes_message",
            message=b"test message",
            expected_subscribers=2,
        ),
        PublishTestCase(
            name="binary_data",
            message=b"\x01\x02\x03\x04",
            expected_subscribers=1,
        ),
        PublishTestCase(
            name="empty_message",
            message=b"",
            expected_subscribers=0,
        ),
    ]


class TestRedisBroadcastChannel:
    """Test RedisBroadcastChannel implementation."""

    def test_init(self):
        """Test channel initialization."""
        mock_redis = Mock(spec=redis.Redis)
        key = "test_key"
        channel = RedisBroadcastChannel(mock_redis, key)

        assert channel._redis_client is mock_redis
        assert channel._key == key
        assert channel._pubsub is None
        assert channel._closed is False

    @pytest.mark.parametrize("test_case", get_publish_test_cases(), ids=lambda tc: tc.name)
    def test_publish_success(self, test_case):
        """Test successful message publishing."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.publish.return_value = test_case.expected_subscribers
        key = "test_channel"

        channel = RedisBroadcastChannel(mock_redis, key)
        channel.publish(test_case.message)

        mock_redis.publish.assert_called_once_with(key, test_case.message)

    def test_publish_redis_error(self):
        """Test publish with Redis error."""
        mock_redis = Mock(spec=redis.Redis)
        mock_redis.publish.side_effect = redis.RedisError("Connection failed")
        key = "test_channel"

        channel = RedisBroadcastChannel(mock_redis, key)

        with pytest.raises(redis.RedisError):
            channel.publish(b"test_message")

    def test_publish_bytes_message(self):
        """Test publish with bytes message."""
        mock_redis = Mock(spec=redis.Redis)
        key = "test_channel"
        message = b"test message"

        channel = RedisBroadcastChannel(mock_redis, key)
        channel.publish(message)

        mock_redis.publish.assert_called_once_with(key, message)

    def test_subscribe_single_channel(self):
        """Test subscribing to a single channel."""
        mock_redis = Mock(spec=redis.Redis)
        mock_pubsub = Mock()
        mock_redis.pubsub.return_value = mock_pubsub
        key = "test_channel"

        # Mock get_message to return messages then None (to simulate no more messages)
        mock_messages = [
            {"type": "message", "channel": b"test_channel", "data": b"hello world"},
            {"type": "message", "channel": b"test_channel", "data": b"test message"},
            None,  # No more messages
        ]
        mock_pubsub.get_message.side_effect = mock_messages

        channel = RedisBroadcastChannel(mock_redis, key)
        message_iter = channel.subscribe()
        
        # Get the first two messages
        messages = []
        messages.append(next(message_iter))
        messages.append(next(message_iter))
        
        # Cancel the subscription after getting messages
        channel._cancel.set()

        # Should receive 2 actual messages
        assert len(messages) == 2
        assert messages[0] == b"hello world"
        assert messages[1] == b"test message"

        mock_pubsub.subscribe.assert_called_once_with(key)

    def test_subscribe_already_subscribed(self):
        """Test subscribing when already subscribed."""
        mock_redis = Mock(spec=redis.Redis)
        mock_pubsub = Mock()
        mock_redis.pubsub.return_value = mock_pubsub
        key = "test_channel"

        channel = RedisBroadcastChannel(mock_redis, key)
        channel._pubsub = mock_pubsub  # Simulate already subscribed

        from libs.redis_channels.broadcast_channel import InvalidOperationError

        with pytest.raises(InvalidOperationError, match="already subscribing"):
            next(channel.subscribe())

    def test_subscribe_closed_channel(self):
        """Test subscribe on closed channel."""
        mock_redis = Mock(spec=redis.Redis)
        key = "test_channel"

        channel = RedisBroadcastChannel(mock_redis, key)
        channel._closed = True

        from libs.redis_channels.broadcast_channel import InvalidOperationError

        with pytest.raises(InvalidOperationError, match="closed"):
            next(channel.subscribe())

    def test_close_with_subscription(self):
        """Test closing channel with active subscription."""
        mock_redis = Mock(spec=redis.Redis)
        mock_pubsub = Mock()
        key = "test_channel"

        channel = RedisBroadcastChannel(mock_redis, key)
        channel._pubsub = mock_pubsub

        channel.close()

        mock_pubsub.unsubscribe.assert_called_once_with(key)
        mock_pubsub.close.assert_called_once()
        assert channel._pubsub is None
        assert channel._closed is True

    def test_close_without_subscription(self):
        """Test closing channel without subscription."""
        mock_redis = Mock(spec=redis.Redis)
        key = "test_channel"

        channel = RedisBroadcastChannel(mock_redis, key)

        # Closing without subscription should work fine now
        channel.close()
        assert channel._closed is True

    def test_context_manager(self):
        """Test using channel as context manager."""
        mock_redis = Mock(spec=redis.Redis)
        key = "test_channel"

        channel = RedisBroadcastChannel(mock_redis, key)

        # Set up mock before entering context
        mock_pubsub = Mock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_messages = [
            {"type": "message", "channel": b"test_channel", "data": b"test"},
            None,  # No more messages
        ]
        mock_pubsub.get_message.side_effect = mock_messages

        # Test context manager entry
        with channel as ctx_iter:
            # Get one message then cancel
            message = next(ctx_iter)
            assert message == b"test"
            
            # Cancel to stop iteration
            channel._cancel.set()

    def test_subscribe_channel_mismatch(self):
        """Test assertion error when receiving message from wrong channel."""
        mock_redis = Mock(spec=redis.Redis)
        mock_pubsub = Mock()
        mock_redis.pubsub.return_value = mock_pubsub
        key = "test_channel"

        # Mock message from different channel
        mock_messages = [
            {"type": "message", "channel": b"wrong_channel", "data": b"test"},
        ]
        mock_pubsub.get_message.side_effect = mock_messages

        channel = RedisBroadcastChannel(mock_redis, key)

        with pytest.raises(AssertionError, match="expected message from test_channel, got wrong_channel"):
            message_iter = channel.subscribe()
            next(message_iter)  # This should raise the assertion error
