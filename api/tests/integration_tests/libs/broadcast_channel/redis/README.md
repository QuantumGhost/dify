# Redis Broadcast Channel Integration Tests

This directory contains comprehensive integration tests for the Redis broadcast channel implementation. The test suite covers all major functionality including basic operations, buffer management, concurrency, error handling, and edge cases.

## Test Structure

```
api/tests/integration_tests/libs/broadcast_channel/redis/
├── __init__.py                    # Test package initialization
├── conftest.py                    # Shared fixtures and configuration
├── test_basic_functionality.py    # Basic pub/sub operations (13 test methods)
├── test_buffer_management.py      # Buffer overflow behaviors (15 test methods)
├── test_threading_concurrency.py  # Threading and concurrency (14 test methods)
├── test_error_handling.py         # Error handling scenarios (18 test methods)
├── test_edge_cases.py            # Edge cases and boundary conditions (20 test methods)
├── README.md                      # This documentation
└── utils/
    ├── __init__.py
    ├── test_helpers.py           # Helper functions and utilities
    └── test_data.py             # Test data and constants
```

## Test Coverage

### 1. Basic Functionality (`test_basic_functionality.py`)
- Simple publish/subscribe operations
- Multiple subscribers to the same topic
- Different topics with independent message streams
- Message ordering guarantees
- Subscription lifecycle management
- Context manager behavior
- Message type handling (Unicode, empty, large messages)
- Producer and subscriber interface compliance

### 2. Buffer Management (`test_buffer_management.py`)
- **DROP_OLDEST**: Remove oldest messages when buffer is full
- **DROP_NEWEST**: Reject new messages when buffer is full
- **BLOCK**: Wait for space when buffer is full
- Buffer size validation (zero, negative, float, string values)
- Performance under high message rates
- Comparison of all overflow strategies with parametrized tests

### 3. Threading and Concurrency (`test_threading_concurrency.py`)
- Multiple concurrent publishers to the same topic
- Multiple concurrent subscribers to the same topic
- Resource cleanup and thread joining
- Context manager behavior under concurrency
- Thread safety of subscription operations
- Concurrent topic creation and destruction
- Subscription cleanup during active operations

### 4. Error Handling (`test_error_handling.py`)
- Invalid buffer sizes (various data types and edge cases)
- Operations on closed subscriptions
- Redis connection failures (publish, subscribe, listener thread)
- Malformed message handling (None, unsupported types, wrong channels)
- Exception propagation in listener threads
- Resource exhaustion scenarios

### 5. Edge Cases (`test_edge_cases.py`)
- Empty messages and special characters
- Large messages and memory limits (1MB, 10MB+)
- Rapid publish/subscribe cycles
- Subscription cleanup during active operations
- Message type handling (bytes, str, memoryview, bytearray)
- Topic name edge cases (long names, special characters, Unicode)
- Stress scenarios with many subscribers/topics

## Running Tests

### Prerequisites

- Docker and testcontainers library for Redis container management
- pytest framework
- All test dependencies installed in the development environment

### Running All Tests

```bash
cd api
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/ -v
```

### Running Specific Test Categories

```bash
# Basic functionality only
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/test_basic_functionality.py -v

# Buffer management tests
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/test_buffer_management.py -v

# Concurrency tests
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/test_threading_concurrency.py -v

# Error handling tests
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/test_error_handling.py -v

# Edge cases tests
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/test_edge_cases.py -v
```

### Running Tests with Specific Markers

```bash
# Run only parametrized tests
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/ -k "config" -v

# Run tests related to specific overflow strategies
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/ -k "drop_oldest" -v
```

### Running Tests with Different Verbosity Levels

```bash
# Quiet mode
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/ -q

# Verbose mode with output
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/ -v -s

# Very verbose mode
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/ -vv -s
```

## Test Configuration

### Redis Configuration

Tests use Redis containers managed by testcontainers. The Redis configuration is automatically handled by the `redis_container` fixture in `conftest.py`.

### Default Test Values

- **Default buffer size**: 10 messages
- **Small buffer size**: 3 messages (for overflow testing)
- **Large buffer size**: 1000 messages (for performance testing)
- **Default timeout**: 10.0 seconds
- **Test message size**: Variable (from empty to 100KB+)

### Customizing Test Parameters

You can modify test parameters by updating the values in `utils/test_data.py`:

```python
# Change buffer sizes for testing
MIN_BUFFER_SIZE = 1
MAX_BUFFER_SIZE = 1000
DEFAULT_BUFFER_SIZE = 10

# Modify timeout values
DEFAULT_TIMEOUT = 10.0
SHORT_TIMEOUT = 2.0
LONG_TIMEOUT = 30.0
```

## Test Utilities

### MessageCollector

A utility class for collecting messages from subscriptions in tests:

```python
from tests.integration_tests.libs.broadcast_channel.redis.conftest import MessageCollector

collector = MessageCollector(timeout=5.0)
collector.collect_messages(subscription)
assert collector.wait_for_messages(5)
messages = collector.get_messages()
```

### ConcurrentPublisher

A utility for stress testing with multiple publishers:

```python
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_helpers import ConcurrentPublisher

publisher = ConcurrentPublisher(producer, message_count=100, delay=0.01)
publisher.start_publishers(thread_count=3)
assert publisher.wait_for_completion()
messages = publisher.get_all_messages()
```

### SubscriptionMonitor

A utility for monitoring subscription activity:

```python
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_helpers import SubscriptionMonitor

monitor = SubscriptionMonitor(subscription, timeout=10.0)
monitor.start_monitoring()
assert monitor.wait_for_messages(10)
monitor.stop()
```

## Performance Considerations

### Test Duration

- **Basic functionality tests**: ~10 seconds
- **Buffer management tests**: ~15 seconds
- **Concurrency tests**: ~20 seconds
- **Error handling tests**: ~15 seconds
- **Edge cases tests**: ~30 seconds (includes large message tests)

### Resource Usage

- **Memory**: Tests use up to 100MB for large message testing
- **CPU**: Concurrency tests may use multiple CPU cores
- **Network**: Redis container communication uses localhost networking

### Optimization Tips

1. **Run tests in parallel**: Use `pytest -n auto` for parallel execution
2. **Skip heavy tests**: Use `-k "not large"` to skip large message tests
3. **Use specific test categories**: Run only the tests you need
4. **Adjust timeouts**: Increase timeouts for slower systems

## Troubleshooting

### Common Issues

#### Redis Container Failures

**Symptom**: Tests fail with Redis connection errors

**Solution**: 
- Ensure Docker is running
- Check port availability (default 6379)
- Verify testcontainers installation

#### Timeout Failures

**Symptom**: Tests fail with timeout errors

**Solution**:
- Increase timeout values in `conftest.py`
- Check system performance
- Run tests on a faster machine

#### Memory Issues

**Symptom**: Tests fail with memory errors

**Solution**:
- Reduce message sizes in test data
- Run tests individually
- Increase available memory

#### Thread-related Failures

**Symptom**: Tests fail with thread-related errors

**Solution**:
- Increase thread join timeouts
- Check for thread safety issues
- Run tests with fewer concurrent operations

### Debug Mode

Enable debug output for troubleshooting:

```bash
python -m pytest tests/integration_tests/libs/broadcast_channel/redis/ -v -s --log-cli-level=DEBUG
```

### Test Isolation

Each test uses a unique topic name to ensure isolation. If you encounter test interference:

1. Check topic name generation in fixtures
2. Verify Redis cleanup between tests
3. Run tests with `--forked` for complete isolation

## Contributing

### Adding New Tests

1. **Choose appropriate file**: Add tests to the most relevant test module
2. **Use existing fixtures**: Leverage fixtures in `conftest.py`
3. **Follow naming conventions**: Use descriptive test method names
4. **Add documentation**: Include docstrings explaining test purpose
5. **Handle cleanup**: Ensure proper resource cleanup

### Test Structure Guidelines

```python
class TestFeature:
    """Test feature description."""
    
    def test_specific_scenario(self, fixture1, fixture2):
        """Test specific scenario with clear description."""
        # Arrange
        # Set up test data and conditions
        
        # Act
        # Perform the operation being tested
        
        # Assert
        # Verify expected outcomes
```

### Best Practices

1. **Use fixtures**: Leverage existing fixtures for consistency
2. **Parametrize tests**: Use `@pytest.mark.parametrize` for similar test cases
3. **Handle exceptions**: Use `pytest.raises` for exception testing
4. **Clean up resources**: Ensure proper cleanup in all test paths
5. **Document edge cases**: Add comments for complex scenarios

## Performance Benchmarks

### Expected Performance

- **Small messages (100B)**: >1000 ops/sec
- **Medium messages (1KB)**: >500 ops/sec
- **Large messages (10KB)**: >100 ops/sec
- **Very large messages (100KB)**: >10 ops/sec

### Measuring Performance

Use the built-in performance measurement utilities:

```python
from tests.integration_tests.libs.broadcast_channel.redis.utils.test_helpers import measure_throughput

ops_per_sec, total_ops = measure_throughput(publish_operation, duration=1.0)
print(f"Performance: {ops_per_sec:.2f} ops/sec")
```

## Maintenance

### Regular Updates

1. **Update dependencies**: Keep test dependencies current
2. **Review test data**: Update test messages and configurations
3. **Check Redis compatibility**: Verify compatibility with new Redis versions
4. **Monitor test duration**: Keep test execution times reasonable

### Test Data Management

- **Message sets**: Update in `utils/test_data.py`
- **Configurations**: Modify dataclasses for new scenarios
- **Timeout values**: Adjust based on system performance

### Documentation Updates

- **README.md**: Keep this file current with test changes
- **Docstrings**: Update test documentation
- **Comments**: Add explanations for complex test logic
