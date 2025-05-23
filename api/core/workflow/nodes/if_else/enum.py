from enum import StrEnum


class ComparisonOperator(StrEnum):
    """Comparison operator enum."""

    CONTAINS = "contains"
    NOT_CONTAINS = "not contains"
    START_WITH = "start with"
    END_WITH = "end with"
    IS = "is"
    IS_NOT = "is not"
    EMPTY = "empty"
    NOT_EMPTY = "not empty"
    EQUAL = "="
    NOT_EQUAL = "≠"
    LARGER_THAN = ">"
    LESS_THAN = "<"
    LARGER_THAN_OR_EQUAL = "≥"
    LESS_THAN_OR_EQUAL = "≤"
    IS_NULL = "is null"
    IS_NOT_NULL = "is not null"
    IN = "in"
    NOT_IN = "not in"
    ALL_OF = "all of"
    EXISTS = "exists"
    NOT_EXISTS = "not exists"
