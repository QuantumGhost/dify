"""Negative public typing contract for canonical immutable JSON scalars."""

from core.human_input_v2.im_provider import (
    ImmutableJSONArray,
    ImmutableJSONBoolean,
    ImmutableJSONFloat,
    ImmutableJSONInteger,
    ImmutableJSONObject,
    ImmutableJSONScalar,
    ImmutableJSONValue,
)

raw_bool_scalar: ImmutableJSONScalar = True  # static-error
raw_int_scalar: ImmutableJSONScalar = 1  # static-error
raw_float_scalar: ImmutableJSONScalar = 1.0  # static-error
raw_bool_value: ImmutableJSONValue = True  # static-error
raw_int_value: ImmutableJSONValue = 1  # static-error
raw_float_value: ImmutableJSONValue = 1.0  # static-error

canonical_bool_scalar: ImmutableJSONScalar = ImmutableJSONBoolean(True)
canonical_int_scalar: ImmutableJSONScalar = ImmutableJSONInteger(1)
canonical_float_scalar: ImmutableJSONScalar = ImmutableJSONFloat(1.0)
canonical_bool_value: ImmutableJSONValue = ImmutableJSONBoolean(True)
canonical_int_value: ImmutableJSONValue = ImmutableJSONInteger(1)
canonical_float_value: ImmutableJSONValue = ImmutableJSONFloat(1.0)

accepted_array_input = ImmutableJSONArray((True, 1, 1.0))
accepted_object_input = ImmutableJSONObject((("boolean", True), ("integer", 1), ("float", 1.0)))
