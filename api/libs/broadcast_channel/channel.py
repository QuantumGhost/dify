"""
Redis-based broadcast channel for Pub/Sub messaging.
"""

import logging
import types
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import AbstractContextManager
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


class Overflow(StrEnum):
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    BLOCK = "block"


class Publisher(ABC):
    @abstractmethod
    def publish(self, message: bytes) -> None:
        """
        Publish a message to the channel the instance associated with.

        Args:
            message: The message data to publish
        """
        pass


class Subscription(AbstractContextManager["Subscription"], Protocol):
    @abstractmethod
    def __iter__(self) -> Iterator[bytes]: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> "Subscription":
        return self

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> bool | None:
        pass


class Producer(Protocol):
    @abstractmethod
    def publish(self, payload: bytes) -> None: ...


class Subscriber(Protocol):
    @abstractmethod
    def subscribe(
        self,
        *,
        buffer: int = 1024,
        overflow: Overflow = Overflow.DROP_OLDEST,
    ) -> Subscription:
        pass


class Topic(Producer, Subscriber, Protocol):
    @abstractmethod
    def as_producer(self) -> Producer: ...

    @abstractmethod
    def as_subscriber(self) -> Subscriber: ...


class BroadcastChannel(Protocol):
    """"""

    @abstractmethod
    def topic(self, topic: str) -> "Topic": ...
