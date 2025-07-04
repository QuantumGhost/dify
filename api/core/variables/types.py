from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from core.file.models import File


class ArrayValidation(StrEnum):
    """Strategy for validating array elements"""

    # Skip element validation (only check array container)
    NONE = "none"

    # Validate the first element (if array is non-empty)
    FIRST = "first"

    # Validate all elements in the array.
    ALL = "all"


class SegmentType(StrEnum):
    NUMBER = "number"
    INTEGER = "integer"
    FLOAT = "float"
    # BOOLEAN = "boolean"
    STRING = "string"
    OBJECT = "object"
    SECRET = "secret"

    FILE = "file"

    ARRAY_ANY = "array[any]"
    ARRAY_STRING = "array[string]"
    ARRAY_NUMBER = "array[number]"
    ARRAY_OBJECT = "array[object]"
    ARRAY_FILE = "array[file]"
    # ARRAY_INTEGER = "array[integer]"
    # ARRAY_FLOAT = "array[float]"
    # ARRAY_BOOLEAN = "array[boolean]"

    NONE = "none"

    GROUP = "group"

    # # special segment type, only to simplify
    # ANY = "any"

    def is_array_type(self) -> bool:
        return self in _ARRAY_TYPES

    # def element_type(self) -> "SegmentType":
    #     elem_type = _ARRAY_ELEMENT_TYPES_MAPPING.get(self)
    #     if elem_type is None:
    #         raise ValueError(...)

    #     return elem_type

    def _validate_array(self, value: Any, array_validation: ArrayValidation) -> bool:
        if not isinstance(value, list):
            return False
        # Skip element validation if array is empty
        if len(value) == 0:
            return True
        if self == SegmentType.ARRAY_ANY:
            return True
        element_type = _ARRAY_ELEMENT_TYPES_MAPPING[self]

        if array_validation == ArrayValidation.NONE:
            return True
        elif array_validation == ArrayValidation.FIRST:
            return element_type.is_valid(value[0])
        else:
            return all([element_type.is_valid(i, array_validation=ArrayValidation.NONE)] for i in value)

    def is_valid(self, value: Any, array_validation: ArrayValidation = ArrayValidation.FIRST) -> bool:
        """
        Check if a value matches the segment type

        Args:
            value: The value to validate
            array_validation: Validation strategy for array types (ignored for non-array types)

        Returns:
            True if the value matches the type under the given validation strategy
        """
        if self.is_array_type():
            return self._validate_array(value, array_validation)
        # elif self == SegmentType.ANY:
        #     return True
        elif self == SegmentType.NUMBER:
            return isinstance(value, (int, float))
        elif self == SegmentType.STRING:
            return isinstance(value, str)
        elif self == SegmentType.OBJECT:
            return isinstance(value, dict)
        elif self == SegmentType.SECRET:
            return isinstance(value, str)
        elif self == SegmentType.FILE:
            return isinstance(value, File)
        elif self == SegmentType.NONE:
            return value is None
        else:
            raise AssertionError("this statement should be unreachable.")

    def user_types(self) -> "SegmentType":
        if self in (SegmentType.INTEGER, SegmentType.FLOAT):
            return SegmentType.NUMBER
        return self


_ARRAY_TYPES = frozenset(
    [
        SegmentType.ARRAY_ANY,
        SegmentType.ARRAY_STRING,
        SegmentType.ARRAY_NUMBER,
        SegmentType.ARRAY_OBJECT,
        SegmentType.ARRAY_FILE,
    ]
)


_ARRAY_ELEMENT_TYPES_MAPPING: Mapping[SegmentType, SegmentType] = {
    # SegmentType.ARRAY_ANY: SegmentType.ANY,
    SegmentType.ARRAY_STRING: SegmentType.STRING,
    SegmentType.ARRAY_NUMBER: SegmentType.NUMBER,
    SegmentType.ARRAY_OBJECT: SegmentType.OBJECT,
    SegmentType.ARRAY_FILE: SegmentType.FILE,
}
