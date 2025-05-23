from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ComparisonOperator(StrEnum):
    """Comparison operator enum."""

    # for string or array
    CONTAINS = "contains"
    NOT_CONTAINS = "not contains"
    START_WITH = "start with"
    END_WITH = "end with"
    IS = "is"
    IS_NOT = "is not"
    EMPTY = "empty"
    NOT_EMPTY = "not empty"
    IN = "in"
    NOT_IN = "not in"
    ALL_OF = "all of"

    #
    EQUAL = "="
    NOT_EQUAL = "≠"
    LARGER_THAN = ">"
    LESS_THAN = "<"
    LARGER_THAN_OR_EQUAL = "≥"
    LESS_THAN_OR_EQUAL = "≤"
    IS_NULL = "is null"
    IS_NOT_NULL = "is not null"

    # for file
    EXISTS = "exists"
    NOT_EXISTS = "not exists"


SupportedComparisonOperator = Literal[
    # for string or array
    "contains",
    "not contains",
    "start with",
    "end with",
    "is",
    "is not",
    "empty",
    "not empty",
    "in",
    "not in",
    "all of",
    # for number
    "=",
    "≠",
    ">",
    "<",
    "≥",
    "≤",
    "null",
    "not null",
    # for file
    "exists",
    "not exists",
]


class SubCondition(BaseModel):
    key: str
    comparison_operator: SupportedComparisonOperator
    value: str | Sequence[str] | None = None


class SubVariableCondition(BaseModel):
    logical_operator: Literal["and", "or"]
    conditions: list[SubCondition] = Field(default_factory=list)


class Condition(BaseModel):
    variable_selector: list[str]
    comparison_operator: SupportedComparisonOperator
    value: str | Sequence[str] | None = None
    sub_variable_condition: SubVariableCondition | None = None
