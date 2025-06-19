from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from models.counter import Counter


class CounterService:
    def __init__(self, session_factory: sessionmaker | Engine):
        if isinstance(session_factory, Engine):
            session_factory = sessionmaker(bind=session_factory)
        self._session_factory = session_factory

    def nextval(self, key: str, initial_value: int = 1) -> int:
        """Returns the next value for the counter specified by key.

        This method manages its own transaction, ensuring the counter never rolls back,
        similar to PostgreSQL's `nextval` function for sequences.

        Args:
            key: The identifier for the counter. Should be properly scoped to avoid
                 performance degradation in the database.
            initial_value: The starting value if the counter doesn't exist yet.

        Note:
            For counters with relaxed persistence requirements, consider using
            Redis counters instead of database counters.
        """
        insert_stmt = insert(Counter).values(key=key, value=initial_value)

        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[Counter.key],
            set_={
                "value": Counter.value + 1,
            },
        ).returning(Counter.value)
        with self._session_factory() as session, session.begin():
            value = session.scalars(stmt).first()
        return value
