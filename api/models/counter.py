from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Counter(Base):
    """A PostgreSQL-backed counter model that provides storage for
    counter values without requiring Redis or other external systems.

    Note: Do not access this model directly.
    Always use the CounterService class for all counter operations.
    """

    __tablename__ = "counters"

    # Column length of 70 accommodates 36-character UUIDs plus
    # up to 34 characters for prefixes and suffixes.
    key: Mapped[str] = mapped_column(String(70), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger)
