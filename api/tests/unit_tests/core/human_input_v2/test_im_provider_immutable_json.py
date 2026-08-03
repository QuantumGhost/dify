"""Lossless immutable JSON contract tests for authenticated IM payloads."""

from ast import literal_eval
from collections.abc import Callable
from datetime import UTC, datetime
from math import copysign, isfinite
from typing import Any, cast, override

import pytest

from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AuthenticatedIMEvent,
    ImmutableJSONArray,
    ImmutableJSONBoolean,
    ImmutableJSONFloat,
    ImmutableJSONInteger,
    ImmutableJSONObject,
    ImmutableJSONValue,
    MutableJSONValue,
    freeze_json_value,
    thaw_json_value,
)

_NOW = datetime(2026, 8, 3, 8, tzinfo=UTC)

type NumericJSONScalar = bool | int | float
type ImmutableValueBuilder = Callable[[NumericJSONScalar], object]
type NumberJSONScalar = int | float
type ImmutableNumberValueBuilder = Callable[[NumberJSONScalar], object]
type CanonicalValueBuilder = Callable[[object], object]


class _HostileInteger(int):
    @override
    def __bool__(self) -> bool:
        return not bool(int(self))

    @override
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 7


class _HostileFloat(float):
    @override
    def __bool__(self) -> bool:
        return not bool(float(self))

    @override
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 7


class _HostileString(str):  # noqa: FURB189
    @override
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 7


class _HostileImmutableJSONBoolean(ImmutableJSONBoolean):
    @override
    def __bool__(self) -> bool:
        return not self.value

    @override
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 7


class _HostileImmutableJSONInteger(ImmutableJSONInteger):
    @override
    def __bool__(self) -> bool:
        return not bool(self.value)

    @override
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 7


class _HostileImmutableJSONFloat(ImmutableJSONFloat):
    @override
    def __bool__(self) -> bool:
        return not bool(self.value)

    @override
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 7


class _HostileImmutableJSONArray(ImmutableJSONArray):
    @override
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 7


class _HostileImmutableJSONObject(ImmutableJSONObject):
    @override
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 7


def _runtime_untyped_provider_payload(value: object) -> Any:
    """Cross the deliberately dynamic legacy-input boundary used by runtime validation tests."""
    return value


def _authenticated_event_with_number(value: NumericJSONScalar) -> AuthenticatedIMEvent:
    return AuthenticatedIMEvent(
        provider=IMProvider.SLACK,
        provider_tenant_id="tenant-1",
        provider_event_id=None,
        provider_event_time=None,
        received_at=_NOW,
        provider_event_type="block_actions",
        provider_payload=_runtime_untyped_provider_payload((("number", value),)),
    )


def _immutable_object_with_number(value: NumericJSONScalar) -> ImmutableJSONObject:
    return ImmutableJSONObject((("number", value),))


def _immutable_array_with_number(value: NumericJSONScalar) -> ImmutableJSONArray:
    return ImmutableJSONArray((value,))


def _frozen_object_with_number(value: NumericJSONScalar) -> object:
    return freeze_json_value({"number": value})


def _frozen_array_with_number(value: NumericJSONScalar) -> object:
    return freeze_json_value([value])


def _frozen_nested_object_with_number(value: NumericJSONScalar) -> object:
    return freeze_json_value({"nested": {"number": value}})


def _frozen_nested_array_with_number(value: NumericJSONScalar) -> object:
    return freeze_json_value([[value]])


def _nested_immutable_object_with_number(value: NumericJSONScalar) -> ImmutableJSONObject:
    return ImmutableJSONObject((("nested", _immutable_object_with_number(value)),))


def _nested_immutable_array_with_number(value: NumericJSONScalar) -> ImmutableJSONArray:
    return ImmutableJSONArray((_immutable_array_with_number(value),))


def _freeze_scalar_number(value: NumericJSONScalar) -> object:
    return freeze_json_value(value)


def _freeze_nested_number(value: NumericJSONScalar) -> object:
    return freeze_json_value({"nested": [value]})


def _frozen_object_member(value: NumericJSONScalar) -> object:
    frozen_object = freeze_json_value({"number": value})
    assert isinstance(frozen_object, ImmutableJSONObject)
    return frozen_object[0][1]


def _frozen_array_member(value: NumericJSONScalar) -> object:
    frozen_array = freeze_json_value([value])
    assert isinstance(frozen_array, ImmutableJSONArray)
    return frozen_array[0]


def _direct_object_member(value: NumericJSONScalar) -> object:
    return _immutable_object_with_number(value)[0][1]


def _direct_array_member(value: NumericJSONScalar) -> object:
    return _immutable_array_with_number(value)[0]


def _frozen_nested_object_member(value: NumericJSONScalar) -> object:
    frozen_object = _frozen_nested_object_with_number(value)
    assert isinstance(frozen_object, ImmutableJSONObject)
    nested_object = frozen_object[0][1]
    assert isinstance(nested_object, ImmutableJSONObject)
    return nested_object[0][1]


def _frozen_nested_array_member(value: NumericJSONScalar) -> object:
    frozen_array = _frozen_nested_array_with_number(value)
    assert isinstance(frozen_array, ImmutableJSONArray)
    nested_array = frozen_array[0]
    assert isinstance(nested_array, ImmutableJSONArray)
    return nested_array[0]


def _direct_nested_object_member(value: NumericJSONScalar) -> object:
    nested_object = _nested_immutable_object_with_number(value)[0][1]
    assert isinstance(nested_object, ImmutableJSONObject)
    return nested_object[0][1]


def _direct_nested_array_member(value: NumericJSONScalar) -> object:
    nested_array = _nested_immutable_array_with_number(value)[0]
    assert isinstance(nested_array, ImmutableJSONArray)
    return nested_array[0]


def _authenticated_event_member(value: NumericJSONScalar) -> object:
    return _authenticated_event_with_number(value).provider_payload[0][1]


def _authenticated_event_with_payload(provider_payload: object) -> AuthenticatedIMEvent:
    return AuthenticatedIMEvent(
        provider=IMProvider.SLACK,
        provider_tenant_id="tenant-1",
        provider_event_id=None,
        provider_event_time=None,
        received_at=_NOW,
        provider_event_type="block_actions",
        provider_payload=_runtime_untyped_provider_payload(provider_payload),
    )


def _canonicalize_at_root(value: object) -> object:
    return freeze_json_value(_runtime_untyped_provider_payload(value))


def _canonicalize_at_direct_object_member(value: object) -> object:
    provider_object = ImmutableJSONObject((("value", _runtime_untyped_provider_payload(value)),))
    return provider_object[0][1]


def _canonicalize_at_direct_array_member(value: object) -> object:
    provider_array = ImmutableJSONArray((_runtime_untyped_provider_payload(value),))
    return provider_array[0]


def _canonicalize_at_frozen_nested_member(value: object) -> object:
    frozen_value = freeze_json_value(_runtime_untyped_provider_payload({"nested": [value]}))
    assert isinstance(frozen_value, ImmutableJSONObject)
    nested_array = frozen_value[0][1]
    assert isinstance(nested_array, ImmutableJSONArray)
    return nested_array[0]


def _canonicalize_at_direct_nested_member(value: object) -> object:
    nested_array = ImmutableJSONArray((_runtime_untyped_provider_payload(value),))
    provider_object = ImmutableJSONObject((("nested", nested_array),))
    canonical_array = provider_object[0][1]
    assert isinstance(canonical_array, ImmutableJSONArray)
    return canonical_array[0]


def _canonicalize_at_legacy_event_member(value: object) -> object:
    event = _authenticated_event_with_payload((("value", value),))
    return event.provider_payload[0][1]


def _canonicalize_at_current_event_member(value: object) -> object:
    provider_payload = ImmutableJSONObject((("value", _runtime_untyped_provider_payload(value)),))
    event = _authenticated_event_with_payload(provider_payload)
    return event.provider_payload[0][1]


def _assert_exact_canonical_tree(value: object) -> None:
    if value is None:
        return
    if isinstance(value, ImmutableJSONBoolean):
        assert type(value) is ImmutableJSONBoolean
        assert type(value.value) is bool
        return
    if isinstance(value, ImmutableJSONInteger):
        assert type(value) is ImmutableJSONInteger
        assert type(value.value) is int
        return
    if isinstance(value, ImmutableJSONFloat):
        assert type(value) is ImmutableJSONFloat
        assert type(value.value) is float
        return
    if isinstance(value, str):
        assert type(value) is str
        return
    if isinstance(value, ImmutableJSONArray):
        assert type(value) is ImmutableJSONArray
        for member in value:
            _assert_exact_canonical_tree(member)
        return
    if isinstance(value, ImmutableJSONObject):
        assert type(value) is ImmutableJSONObject
        for key, member in value:
            assert type(key) is str
            _assert_exact_canonical_tree(member)
        return
    pytest.fail(f"unexpected immutable JSON value: {value!r}")


def _assert_canonical_value(
    canonical_value: object,
    expected_type: type[object],
    expected_native_value: MutableJSONValue,
) -> None:
    assert type(canonical_value) is expected_type
    _assert_exact_canonical_tree(canonical_value)
    immutable_value = cast(ImmutableJSONValue, canonical_value)
    thawed_value = thaw_json_value(immutable_value)
    assert type(thawed_value) is type(expected_native_value)
    assert thawed_value == expected_native_value

    expected_value = freeze_json_value(expected_native_value)
    assert canonical_value == expected_value
    assert expected_value == canonical_value
    assert (canonical_value != expected_value) is False
    assert hash(canonical_value) == hash(expected_value)
    assert len({canonical_value, expected_value}) == 1
    keyed_values = {canonical_value: "canonical", expected_value: "expected"}
    assert len(keyed_values) == 1
    assert keyed_values[canonical_value] == "expected"


def _thaw_and_refreeze_duplicate_object() -> None:
    duplicate_object = ImmutableJSONObject((("k", 1), ("k", 2)))
    thawed_object = thaw_json_value(duplicate_object)
    freeze_json_value(thawed_object)


def _assert_boolean_and_number_are_distinct(
    build_value: ImmutableValueBuilder,
    boolean_scalar: bool,
    number_scalar: int,
) -> None:
    boolean_value = build_value(boolean_scalar)
    same_boolean_value = build_value(boolean_scalar)
    number_value = build_value(number_scalar)
    same_number_value = build_value(number_scalar)

    assert boolean_value != number_value
    assert number_value != boolean_value
    assert boolean_value == same_boolean_value
    assert number_value == same_number_value
    assert hash(boolean_value) == hash(same_boolean_value)
    assert hash(number_value) == hash(same_number_value)
    assert len({boolean_value, number_value}) == 2
    keyed_values = {boolean_value: "boolean", number_value: "number"}
    assert len(keyed_values) == 2
    assert keyed_values[boolean_value] == "boolean"
    assert keyed_values[number_value] == "number"


def _assert_integer_and_float_are_distinct(
    build_value: ImmutableNumberValueBuilder,
    integer_scalar: int,
    float_scalar: float,
) -> None:
    integer_value = build_value(integer_scalar)
    same_integer_value = build_value(integer_scalar)
    float_value = build_value(float_scalar)
    same_float_value = build_value(float_scalar)

    assert integer_value == same_integer_value
    assert (integer_value != same_integer_value) is False
    assert float_value == same_float_value
    assert (float_value != same_float_value) is False
    assert hash(integer_value) == hash(same_integer_value)
    assert hash(float_value) == hash(same_float_value)
    assert integer_value != float_value
    assert float_value != integer_value
    assert len({integer_value, float_value}) == 2
    keyed_values = {integer_value: "integer", float_value: "float"}
    assert len(keyed_values) == 2
    assert keyed_values[integer_value] == "integer"
    assert keyed_values[float_value] == "float"


def test_immutable_json_object_and_array_of_pairs_have_distinct_runtime_types() -> None:
    provider_object = freeze_json_value({"k": 1})
    provider_array_of_pairs = freeze_json_value([["k", 1]])

    assert isinstance(provider_object, ImmutableJSONObject)
    assert isinstance(provider_array_of_pairs, ImmutableJSONArray)
    assert isinstance(provider_array_of_pairs[0], ImmutableJSONArray)
    assert type(provider_object) is not type(provider_array_of_pairs)
    assert provider_object != provider_array_of_pairs
    assert provider_array_of_pairs != provider_object
    assert len({provider_object: "object", provider_array_of_pairs: "array"}) == 2
    keyed_values = {provider_object: "object", provider_array_of_pairs: "array"}
    assert keyed_values[provider_object] == "object"
    assert keyed_values[provider_array_of_pairs] == "array"

    empty_object = freeze_json_value({})
    empty_array = freeze_json_value([])
    assert empty_object != empty_array
    assert empty_array != empty_object
    assert len({empty_object: "object", empty_array: "array"}) == 2

    nested_object = freeze_json_value({"outer": {"k": 1}})
    nested_array_of_pairs = freeze_json_value({"outer": [["k", 1]]})
    assert nested_object != nested_array_of_pairs
    assert len({nested_object, nested_array_of_pairs}) == 2


def test_immutable_json_same_type_equality_and_hash_preserve_content_semantics() -> None:
    first_object = freeze_json_value({"k": [1, True, None]})
    same_object = freeze_json_value({"k": [1, True, None]})
    different_object = freeze_json_value({"k": [1, False, None]})
    first_array = freeze_json_value([["k", 1]])
    same_array = freeze_json_value([["k", 1]])
    different_array = freeze_json_value([["k", 2]])

    assert first_object == same_object
    assert hash(first_object) == hash(same_object)
    assert first_object != different_object
    assert first_array == same_array
    assert hash(first_array) == hash(same_array)
    assert first_array != different_array


@pytest.mark.parametrize(
    "build_value",
    [
        pytest.param(_freeze_scalar_number, id="root-scalar"),
        pytest.param(_authenticated_event_with_number, id="authenticated-event-root-object"),
        pytest.param(_immutable_object_with_number, id="direct-object"),
        pytest.param(_immutable_array_with_number, id="direct-array"),
        pytest.param(_nested_immutable_object_with_number, id="nested-object"),
        pytest.param(_nested_immutable_array_with_number, id="nested-array"),
        pytest.param(_frozen_object_member, id="frozen-object-member"),
        pytest.param(_frozen_array_member, id="frozen-array-member"),
        pytest.param(_direct_object_member, id="direct-object-member"),
        pytest.param(_direct_array_member, id="direct-array-member"),
    ],
)
@pytest.mark.parametrize(
    ("boolean_scalar", "number_scalar"),
    [
        pytest.param(True, 1, id="true-vs-one"),
        pytest.param(False, 0, id="false-vs-zero"),
    ],
)
def test_immutable_json_boolean_and_number_value_kinds_remain_distinct(
    build_value: ImmutableValueBuilder,
    boolean_scalar: bool,
    number_scalar: int,
) -> None:
    _assert_boolean_and_number_are_distinct(build_value, boolean_scalar, number_scalar)


@pytest.mark.parametrize(
    "build_value",
    [
        pytest.param(_freeze_scalar_number, id="root-scalar"),
        pytest.param(_frozen_object_with_number, id="frozen-object"),
        pytest.param(_frozen_array_with_number, id="frozen-array"),
        pytest.param(_frozen_nested_object_with_number, id="frozen-nested-object"),
        pytest.param(_frozen_nested_array_with_number, id="frozen-nested-array"),
        pytest.param(_immutable_object_with_number, id="direct-object"),
        pytest.param(_immutable_array_with_number, id="direct-array"),
        pytest.param(_nested_immutable_object_with_number, id="direct-nested-object"),
        pytest.param(_nested_immutable_array_with_number, id="direct-nested-array"),
        pytest.param(_authenticated_event_with_number, id="authenticated-event"),
    ],
)
@pytest.mark.parametrize(
    ("integer_scalar", "float_scalar"),
    [
        pytest.param(1, 1.0, id="one-vs-one-point-zero"),
        pytest.param(0, 0.0, id="zero-vs-positive-zero-point-zero"),
        pytest.param(0, -0.0, id="zero-vs-negative-zero-point-zero"),
    ],
)
def test_immutable_json_integer_and_float_representations_remain_distinct(
    build_value: ImmutableNumberValueBuilder,
    integer_scalar: int,
    float_scalar: float,
) -> None:
    _assert_integer_and_float_are_distinct(build_value, integer_scalar, float_scalar)


@pytest.mark.parametrize(
    "build_member",
    [
        pytest.param(_freeze_scalar_number, id="root-scalar"),
        pytest.param(_frozen_object_member, id="frozen-object-member"),
        pytest.param(_frozen_array_member, id="frozen-array-member"),
        pytest.param(_frozen_nested_object_member, id="frozen-nested-object-member"),
        pytest.param(_frozen_nested_array_member, id="frozen-nested-array-member"),
        pytest.param(_direct_object_member, id="direct-object-member"),
        pytest.param(_direct_array_member, id="direct-array-member"),
        pytest.param(_direct_nested_object_member, id="direct-nested-object-member"),
        pytest.param(_direct_nested_array_member, id="direct-nested-array-member"),
        pytest.param(_authenticated_event_member, id="authenticated-event-member"),
    ],
)
@pytest.mark.parametrize(
    "number",
    [
        pytest.param(1, id="integer"),
        pytest.param(1.0, id="float"),
        pytest.param(-0.0, id="negative-zero"),
    ],
)
def test_immutable_json_numbers_have_canonical_nominal_members_and_round_trip(
    build_member: ImmutableNumberValueBuilder,
    number: NumberJSONScalar,
) -> None:
    frozen_number = build_member(number)

    assert type(frozen_number) is not type(number)
    thawed_number = thaw_json_value(cast(ImmutableJSONValue, frozen_number))
    assert type(thawed_number) is type(number)
    assert thawed_number == number
    if isinstance(number, float) and number == 0.0:
        assert copysign(1.0, thawed_number) == copysign(1.0, number)
    refrozen_number = freeze_json_value(thawed_number)
    assert refrozen_number == frozen_number
    assert (refrozen_number != frozen_number) is False
    assert hash(refrozen_number) == hash(frozen_number)


@pytest.mark.parametrize("boolean_scalar", [True, False])
def test_immutable_json_boolean_representation_is_path_independent_and_round_trips(
    boolean_scalar: bool,
) -> None:
    root_boolean: ImmutableJSONValue = freeze_json_value(boolean_scalar)
    frozen_booleans = (
        root_boolean,
        _frozen_object_member(boolean_scalar),
        _frozen_array_member(boolean_scalar),
        _direct_object_member(boolean_scalar),
        _direct_array_member(boolean_scalar),
    )

    for frozen_boolean in frozen_booleans:
        assert isinstance(frozen_boolean, ImmutableJSONBoolean)
        assert type(frozen_boolean) is type(root_boolean)
        assert bool(frozen_boolean) is boolean_scalar
        thawed_boolean = thaw_json_value(frozen_boolean)
        assert type(thawed_boolean) is bool
        assert thawed_boolean is boolean_scalar
        refrozen_boolean = freeze_json_value(thawed_boolean)
        assert refrozen_boolean == frozen_boolean
        assert hash(refrozen_boolean) == hash(frozen_boolean)


def test_immutable_json_tagged_containers_never_equal_raw_tuples_in_either_direction() -> None:
    provider_object = freeze_json_value({"k": 1})
    provider_array_of_pairs = freeze_json_value([["k", 1]])
    raw_tuple = (("k", 1),)

    assert provider_object != raw_tuple
    assert raw_tuple != provider_object
    assert provider_array_of_pairs != raw_tuple
    assert raw_tuple != provider_array_of_pairs


def test_immutable_json_round_trip_preserves_every_container_and_scalar_kind() -> None:
    provider_json: MutableJSONValue = {
        "nested_object": {
            "nested_arrays": [["k", 1], [True, None], []],
            "empty_object": {},
        },
        "empty_array": [],
        "scalars": [True, False, None, 0, -2, 3.5, "text"],
    }

    frozen_json = freeze_json_value(provider_json)

    assert isinstance(frozen_json, ImmutableJSONObject)
    frozen_entries = dict(frozen_json)
    assert isinstance(frozen_entries["nested_object"], ImmutableJSONObject)
    assert isinstance(frozen_entries["empty_array"], ImmutableJSONArray)
    assert dict(frozen_entries["nested_object"])["empty_object"] == ImmutableJSONObject(())
    assert thaw_json_value(frozen_json) == provider_json


def test_authenticated_event_rejects_ambiguous_untagged_nested_container() -> None:
    ambiguous_payload = literal_eval('(("ambiguous", (("k", 1),)),)')

    with pytest.raises(TypeError, match="tagged immutable JSON containers"):
        AuthenticatedIMEvent(
            provider=IMProvider.SLACK,
            provider_tenant_id="tenant-1",
            provider_event_id=None,
            provider_event_time=None,
            received_at=_NOW,
            provider_event_type="block_actions",
            provider_payload=ambiguous_payload,
        )


def test_immutable_json_object_rejects_duplicate_keys_before_construction() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ImmutableJSONObject((("k", 1), ("k", 2)))


def test_nested_immutable_json_object_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ImmutableJSONObject(
            (
                (
                    "nested",
                    ImmutableJSONObject((("k", 1), ("k", 2))),
                ),
            )
        )


def test_authenticated_event_rejects_duplicate_keys_in_legacy_raw_object_tuple() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        AuthenticatedIMEvent(
            provider=IMProvider.SLACK,
            provider_tenant_id="tenant-1",
            provider_event_id=None,
            provider_event_time=None,
            received_at=_NOW,
            provider_event_type="block_actions",
            provider_payload=_runtime_untyped_provider_payload((("k", 1), ("k", 2))),
        )


def test_duplicate_object_keys_cannot_reach_thaw_and_refreeze_flow() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _thaw_and_refreeze_duplicate_object()


@pytest.mark.parametrize(
    "build_value",
    [
        pytest.param(_freeze_scalar_number, id="freeze-scalar"),
        pytest.param(_freeze_nested_number, id="freeze-nested"),
        pytest.param(_immutable_array_with_number, id="direct-array"),
        pytest.param(_immutable_object_with_number, id="direct-object"),
        pytest.param(_authenticated_event_with_number, id="authenticated-event"),
    ],
)
@pytest.mark.parametrize(
    "non_finite_number",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
    ],
)
def test_immutable_json_rejects_non_finite_numbers(
    build_value: ImmutableValueBuilder,
    non_finite_number: float,
) -> None:
    with pytest.raises(ValueError, match="finite"):
        build_value(non_finite_number)


@pytest.mark.parametrize(
    "number",
    [
        pytest.param(-2, id="integer"),
        pytest.param(3.5, id="float"),
        pytest.param(-0.0, id="negative-zero"),
    ],
)
def test_immutable_json_accepts_finite_numbers_without_changing_their_type(number: int | float) -> None:
    frozen_scalar = freeze_json_value(number)
    frozen_nested = freeze_json_value({"nested": [number]})
    direct_array = _immutable_array_with_number(number)
    direct_object = _immutable_object_with_number(number)
    authenticated_event = _authenticated_event_with_number(number)

    assert isinstance(frozen_nested, ImmutableJSONObject)
    nested_array = dict(frozen_nested)["nested"]
    assert isinstance(nested_array, ImmutableJSONArray)
    preserved_numbers = (
        frozen_scalar,
        nested_array[0],
        direct_array[0],
        direct_object[0][1],
        authenticated_event.provider_payload[0][1],
    )
    for frozen_number in preserved_numbers:
        assert type(frozen_number) is not type(number)
        thawed_number = thaw_json_value(cast(ImmutableJSONValue, frozen_number))
        assert type(thawed_number) is type(number)
        assert isinstance(thawed_number, (int, float))
        assert isfinite(thawed_number)
        if isinstance(number, float) and number == 0.0:
            assert isinstance(thawed_number, float)
            assert copysign(1.0, thawed_number) == copysign(1.0, number)


@pytest.mark.parametrize(
    "build_value",
    [
        pytest.param(_canonicalize_at_root, id="root-freeze"),
        pytest.param(_canonicalize_at_direct_object_member, id="direct-object"),
        pytest.param(_canonicalize_at_direct_array_member, id="direct-array"),
        pytest.param(_canonicalize_at_frozen_nested_member, id="frozen-nested"),
        pytest.param(_canonicalize_at_direct_nested_member, id="direct-nested"),
        pytest.param(_canonicalize_at_legacy_event_member, id="legacy-event"),
        pytest.param(_canonicalize_at_current_event_member, id="current-event"),
    ],
)
@pytest.mark.parametrize(
    "number",
    [
        pytest.param(0, id="zero-integer"),
        pytest.param(0.0, id="zero-float"),
        pytest.param(-0.0, id="negative-zero-float"),
        pytest.param(3, id="positive-integer"),
        pytest.param(-3, id="negative-integer"),
        pytest.param(2.5, id="positive-float"),
        pytest.param(-2.5, id="negative-float"),
    ],
)
def test_nominal_number_truthiness_matches_thawed_native_value(
    build_value: CanonicalValueBuilder,
    number: int | float,
) -> None:
    canonical_value = build_value(number)
    thawed_value = thaw_json_value(cast(ImmutableJSONValue, canonical_value))

    assert type(thawed_value) is type(number)
    assert bool(canonical_value) is bool(thawed_value)


@pytest.mark.parametrize(
    "build_value",
    [
        pytest.param(_canonicalize_at_root, id="root-freeze"),
        pytest.param(_canonicalize_at_direct_object_member, id="direct-object"),
        pytest.param(_canonicalize_at_direct_array_member, id="direct-array"),
        pytest.param(_canonicalize_at_frozen_nested_member, id="frozen-nested"),
        pytest.param(_canonicalize_at_direct_nested_member, id="direct-nested"),
        pytest.param(_canonicalize_at_legacy_event_member, id="legacy-event"),
        pytest.param(_canonicalize_at_current_event_member, id="current-event"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected_type", "expected_native_value"),
    [
        pytest.param(_HostileInteger(7), ImmutableJSONInteger, 7, id="raw-integer-subclass"),
        pytest.param(_HostileFloat(2.5), ImmutableJSONFloat, 2.5, id="raw-float-subclass"),
        pytest.param(_HostileString("value"), str, "value", id="raw-string-subclass"),
        pytest.param(
            _HostileImmutableJSONBoolean(True),
            ImmutableJSONBoolean,
            True,
            id="boolean-wrapper-subclass",
        ),
        pytest.param(
            _HostileImmutableJSONInteger(7),
            ImmutableJSONInteger,
            7,
            id="integer-wrapper-subclass",
        ),
        pytest.param(
            _HostileImmutableJSONFloat(2.5),
            ImmutableJSONFloat,
            2.5,
            id="float-wrapper-subclass",
        ),
        pytest.param(
            _HostileImmutableJSONArray((_HostileImmutableJSONInteger(7), _HostileString("value"))),
            ImmutableJSONArray,
            [7, "value"],
            id="array-subclass",
        ),
        pytest.param(
            _HostileImmutableJSONObject(
                ((_HostileString("key"), _HostileImmutableJSONArray((_HostileImmutableJSONFloat(2.5),))),)
            ),
            ImmutableJSONObject,
            {"key": [2.5]},
            id="object-subclass",
        ),
    ],
)
def test_canonicalization_removes_subclass_identity_and_behavior(
    build_value: CanonicalValueBuilder,
    value: object,
    expected_type: type[object],
    expected_native_value: MutableJSONValue,
) -> None:
    canonical_value = build_value(value)

    _assert_canonical_value(canonical_value, expected_type, expected_native_value)


@pytest.mark.parametrize(
    "boundary",
    ["root-freeze", "direct-object", "frozen-nested", "direct-nested", "legacy-event", "current-event"],
)
def test_object_key_subclasses_are_canonicalized_to_exact_strings(boundary: str) -> None:
    hostile_key = _HostileString("key")
    if boundary == "root-freeze":
        canonical_object = freeze_json_value(_runtime_untyped_provider_payload({hostile_key: 1}))
    elif boundary == "direct-object":
        canonical_object = ImmutableJSONObject(((hostile_key, 1),))
    elif boundary == "frozen-nested":
        outer_object = freeze_json_value(_runtime_untyped_provider_payload({"outer": {hostile_key: 1}}))
        assert isinstance(outer_object, ImmutableJSONObject)
        canonical_object = outer_object[0][1]
    elif boundary == "direct-nested":
        canonical_object = ImmutableJSONObject((("outer", ImmutableJSONObject(((hostile_key, 1),))),))[0][1]
    elif boundary == "legacy-event":
        canonical_object = _authenticated_event_with_payload(((hostile_key, 1),)).provider_payload
    else:
        payload = ImmutableJSONObject(((hostile_key, 1),))
        canonical_object = _authenticated_event_with_payload(payload).provider_payload

    assert isinstance(canonical_object, ImmutableJSONObject)
    _assert_exact_canonical_tree(canonical_object)
    assert canonical_object[0][0] == "key"


def test_authenticated_event_canonicalizes_current_container_subclass_recursively() -> None:
    payload = _HostileImmutableJSONObject(
        (
            (
                _HostileString("value"),
                _HostileImmutableJSONArray((_HostileImmutableJSONInteger(7), _HostileString("nested"))),
            ),
        )
    )

    event = _authenticated_event_with_payload(payload)

    _assert_canonical_value(event.provider_payload, ImmutableJSONObject, {"value": [7, "nested"]})


@pytest.mark.parametrize(
    ("constructor", "invalid_value", "error_pattern"),
    [
        pytest.param(ImmutableJSONBoolean, 1, "bool", id="boolean-from-integer"),
        pytest.param(ImmutableJSONBoolean, 1.0, "bool", id="boolean-from-float"),
        pytest.param(ImmutableJSONInteger, True, "int", id="integer-from-boolean"),
        pytest.param(ImmutableJSONInteger, 1.0, "int", id="integer-from-float"),
        pytest.param(ImmutableJSONInteger, _HostileInteger(1), "int", id="integer-from-subclass"),
        pytest.param(ImmutableJSONFloat, True, "float", id="float-from-boolean"),
        pytest.param(ImmutableJSONFloat, 1, "float", id="float-from-integer"),
        pytest.param(ImmutableJSONFloat, _HostileFloat(1.0), "float", id="float-from-subclass"),
        pytest.param(ImmutableJSONFloat, float("nan"), "finite", id="float-from-nan"),
        pytest.param(ImmutableJSONFloat, float("inf"), "finite", id="float-from-positive-infinity"),
        pytest.param(ImmutableJSONFloat, float("-inf"), "finite", id="float-from-negative-infinity"),
    ],
)
def test_direct_scalar_wrapper_constructors_reject_noncanonical_native_values(
    constructor: Callable[[Any], object],
    invalid_value: object,
    error_pattern: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=error_pattern):
        constructor(invalid_value)
