"""
Unit tests for SegmentType.is_array_type method.

This module provides comprehensive test coverage for the is_array_type method
of the SegmentType enum, ensuring proper identification of array and non-array types.
"""

from dataclasses import dataclass

from core.variables.types import SegmentType


@dataclass
class SegmentTypeTestCase:
    """
    Test case data structure for SegmentType testing.

    Uses dataclass for simple test data structures.
    """

    segment_type: SegmentType
    expected_result: bool
    description: str


class TestSegmentTypeIsArrayType:
    """
    Test class for SegmentType.is_array_type method.

    Provides comprehensive coverage of all SegmentType values to ensure
    correct identification of array and non-array types.
    """

    def test_is_array_type_comprehensive(self):
        """
        Test that all segment types return correct boolean values for is_array_type method.

        Validates that:
        - Array types (ARRAY_ANY, ARRAY_STRING, ARRAY_NUMBER, ARRAY_OBJECT, ARRAY_FILE) return True
        - Non-array types (ANY, NUMBER, STRING, OBJECT, SECRET, FILE, NONE, GROUP) return False
        - All return values are boolean type
        """
        # Array type test cases
        test_cases = [
            SegmentTypeTestCase(
                segment_type=SegmentType.ARRAY_ANY,
                expected_result=True,
                description="ARRAY_ANY should be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.ARRAY_STRING,
                expected_result=True,
                description="ARRAY_STRING should be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.ARRAY_NUMBER,
                expected_result=True,
                description="ARRAY_NUMBER should be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.ARRAY_OBJECT,
                expected_result=True,
                description="ARRAY_OBJECT should be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.ARRAY_FILE,
                expected_result=True,
                description="ARRAY_FILE should be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.ANY,
                expected_result=False,
                description="ANY should not be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.NUMBER,
                expected_result=False,
                description="NUMBER should not be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.STRING,
                expected_result=False,
                description="STRING should not be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.OBJECT,
                expected_result=False,
                description="OBJECT should not be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.SECRET,
                expected_result=False,
                description="SECRET should not be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.FILE,
                expected_result=False,
                description="FILE should not be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.NONE,
                expected_result=False,
                description="NONE should not be identified as array type",
            ),
            SegmentTypeTestCase(
                segment_type=SegmentType.GROUP,
                expected_result=False,
                description="GROUP should not be identified as array type",
            ),
        ]

        # Test all array types
        for test_case in test_cases:
            segment_type = test_case.segment_type

            result = segment_type.is_array_type()

            assert result == test_case.expected_result, test_case.description
            assert isinstance(result, bool), f"Return type should be boolean for {segment_type}"

    def test_all_segment_types_coverage(self):
        """
        Test that all SegmentType enum values are covered in our test cases.

        Ensures comprehensive coverage by verifying that every SegmentType
        value is tested for the is_array_type method.
        """
        # Arrange
        all_segment_types = set(SegmentType)
        expected_array_types = {
            SegmentType.ARRAY_ANY,
            SegmentType.ARRAY_STRING,
            SegmentType.ARRAY_NUMBER,
            SegmentType.ARRAY_OBJECT,
            SegmentType.ARRAY_FILE,
        }
        expected_non_array_types = {
            # SegmentType.ANY,
            SegmentType.NUMBER,
            SegmentType.STRING,
            SegmentType.OBJECT,
            SegmentType.SECRET,
            SegmentType.FILE,
            SegmentType.NONE,
            SegmentType.GROUP,
        }

        # Act & Assert
        covered_types = expected_array_types | expected_non_array_types
        assert covered_types == all_segment_types, "All SegmentType values should be covered in tests"
        assert len(all_segment_types) == 13, "Expected 13 total SegmentType values"
        assert len(expected_array_types) == 5, "Expected 5 array types"
        assert len(expected_non_array_types) == 8, "Expected 8 non-array types"

    def test_all_enum_values_are_supported(self):
        """
        Test that all enum values are supported and return boolean values.

        Validates that every SegmentType enum value can be processed by
        is_array_type method and returns a boolean value.
        """
        enum_values: list[SegmentType] = list(SegmentType)
        for seg_type in enum_values:
            is_array = seg_type.is_array_type()
            assert isinstance(is_array, bool), f"is_array_type does not return a boolean for segment type {seg_type}"
