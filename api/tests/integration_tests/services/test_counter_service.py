import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from configs import dify_config
from services.counter import CounterService


def generate_key(prefix="test"):
    """Generate a unique key for testing"""
    return f"{prefix}_{uuid.uuid4().hex}"


@pytest.fixture(scope="module")
def engine():
    """Create a test database engine"""
    # Use PostgreSQL for testing with TEST_DATABASE_URL
    engine = create_engine(dify_config.SQLALCHEMY_DATABASE_URI, echo=True)
    return engine


@pytest.fixture
def session_factory(engine):
    """Create a session factory for testing"""
    return sessionmaker(bind=engine)


@pytest.fixture
def counter_service(session_factory):
    """Create a CounterService instance for testing"""
    return CounterService(session_factory)


class TestCounterService:
    """Integration tests for CounterService"""

    def test_nextval_creates_new_counter(self, counter_service, engine):
        """Test that nextval creates a new counter if it doesn't exist"""
        # Arrange
        key = generate_key("create")

        # Act
        value = counter_service.nextval(key)

        # Assert
        # The first value should be 1 (the default initial value)
        assert value == 1

        # Verify the counter was created in the database
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT value FROM counters WHERE key = '{key}'")).fetchone()
            assert result is not None
            assert result[0] == 1

    def test_nextval_increments_existing_counter(self, counter_service):
        """Test that nextval increments an existing counter"""
        # Arrange
        key = generate_key("increment")

        # Act
        first_value = counter_service.nextval(key)
        second_value = counter_service.nextval(key)
        third_value = counter_service.nextval(key)

        # Assert
        assert first_value == 1
        assert second_value == 2
        assert third_value == 3

    def test_multiple_counters_are_independent(self, counter_service):
        """Test that different counter keys are tracked independently"""
        # Arrange
        key1 = generate_key("multi1")
        key2 = generate_key("multi2")

        # Act
        value1_first = counter_service.nextval(key1)
        value2_first = counter_service.nextval(key2)
        value1_second = counter_service.nextval(key1)

        # Assert
        assert value1_first == 1
        assert value2_first == 1  # Different counter starts at 1
        assert value1_second == 2  # First counter increments to 2

    def test_counter_service_with_engine(self, engine):
        """Test that CounterService can be initialized with an engine directly"""
        # Arrange
        service = CounterService(engine)
        key = generate_key("engine")

        # Act
        value = service.nextval(key)

        # Assert
        assert value == 1  # Default initial_value is 1

    def test_nextval_with_custom_initial_value(self, counter_service):
        """Test that nextval uses the provided initial_value for new counters"""
        # Arrange
        key = generate_key("custom_init")
        initial_value = 100

        # Act
        value = counter_service.nextval(key, initial_value=initial_value)

        # Assert
        assert value == initial_value

    def test_nextval_with_custom_initial_value_increments_properly(self, counter_service):
        """Test that nextval with custom initial_value increments properly on subsequent calls"""
        # Arrange
        key = generate_key(prefix="custom_inc")
        initial_value = 50

        # Act
        first_value = counter_service.nextval(key, initial_value=initial_value)
        second_value = counter_service.nextval(key)  # No initial_value on second call

        # Assert
        assert first_value == initial_value
        assert second_value == initial_value + 1

    def test_nextval_initial_value_ignored_for_existing_counter(self, counter_service):
        """Test that initial_value is ignored for existing counters"""
        # Arrange
        key = generate_key("existing")

        # Create the counter first with initial_value=10
        first_value = counter_service.nextval(key, initial_value=10)

        # Act - Try to use a different initial_value
        second_value = counter_service.nextval(key, initial_value=20)

        # Assert
        assert first_value == 10
        assert second_value == 11  # Should be incremented from 10, not reset to 20

    def test_nextval_with_negative_initial_value(self, counter_service):
        """Test that nextval works correctly with negative initial values"""
        # Arrange
        key = generate_key("negative")
        initial_value = -10

        # Act
        first_value = counter_service.nextval(key, initial_value=initial_value)
        second_value = counter_service.nextval(key)

        # Assert
        assert first_value == initial_value
        assert second_value == initial_value + 1  # Should increment from the negative value

    def test_nextval_with_negative_initial_value_crosses_zero(self, counter_service):
        """Test that nextval correctly handles incrementing across zero from negative values"""
        # Arrange
        key = generate_key("cross_zero")
        initial_value = -1

        # Act
        first_value = counter_service.nextval(key, initial_value=initial_value)
        second_value = counter_service.nextval(key)
        third_value = counter_service.nextval(key)

        # Assert
        assert first_value == -1
        assert second_value == 0  # Incremented from -1 to 0
        assert third_value == 1  # Incremented from 0 to 1
