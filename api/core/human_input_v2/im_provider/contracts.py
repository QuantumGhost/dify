"""Provider-neutral IM adapter contracts and immutable boundary values.

The contracts stop at authenticated provider facts. Provider SDK objects,
transport authentication material, ACK handles, persistence, routing, and
business decoding stay outside this module. Concrete adapters own resources;
capability consumers receive only narrow views over the same root context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Literal, Protocol, TypeVar, override

from core.human_input_v2.entities import IMProvider

DestinationT = TypeVar("DestinationT", contravariant=True)
ReferenceT = TypeVar("ReferenceT")
MessagingReferenceT = TypeVar("MessagingReferenceT", covariant=True)


@dataclass(frozen=True, slots=True, eq=False)
class _ImmutableJSONNominalScalar[ScalarT]:
    """Nominal JSON scalar with exact native value and type-tagged value semantics."""

    value: ScalarT

    def __post_init__(self) -> None:
        """Validate the concrete scalar kind after dataclass initialization."""

    def _equality_key(self) -> object:
        return self.value

    def __bool__(self) -> bool:
        return bool(self.value)

    @override
    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other) or not isinstance(other, _ImmutableJSONNominalScalar):
            return False
        return self._equality_key() == other._equality_key()

    @override
    def __ne__(self, other: object) -> bool:
        return not self == other

    @override
    def __hash__(self) -> int:
        return hash((type(self), self._equality_key()))


@dataclass(frozen=True, slots=True, eq=False)
class ImmutableJSONBoolean(_ImmutableJSONNominalScalar[bool]):
    """Canonical immutable JSON boolean whose value semantics cannot alias a number."""

    @override
    def __post_init__(self) -> None:
        if type(self.value) is not bool:
            raise TypeError("immutable JSON boolean value must be a bool")


@dataclass(frozen=True, slots=True, eq=False)
class ImmutableJSONInteger(_ImmutableJSONNominalScalar[int]):
    """Canonical immutable JSON integer distinct from booleans and floats."""

    @override
    def __post_init__(self) -> None:
        if type(self.value) is not int:
            raise TypeError("immutable JSON integer value must be an int")


@dataclass(frozen=True, slots=True, eq=False)
class ImmutableJSONFloat(_ImmutableJSONNominalScalar[float]):
    """Canonical finite JSON float preserving its exact binary representation."""

    @override
    def __post_init__(self) -> None:
        if type(self.value) is not float:
            raise TypeError("immutable JSON float value must be a float")
        if not isfinite(self.value):
            raise ValueError("immutable JSON float value must be finite")

    @override
    def _equality_key(self) -> object:
        return self.value.hex()


type ImmutableJSONScalar = str | ImmutableJSONBoolean | ImmutableJSONInteger | ImmutableJSONFloat | None
type _MutableJSONScalar = str | int | float | bool | None
type MutableJSONValue = _MutableJSONScalar | list["MutableJSONValue"] | dict[str, "MutableJSONValue"]
type ImmutableJSONValue = ImmutableJSONScalar | ImmutableJSONArray | ImmutableJSONObject


class ImmutableJSONArray(tuple[ImmutableJSONValue, ...]):
    """Immutable JSON array whose value semantics cannot alias another container kind."""

    def __new__(
        cls,
        values: tuple[ImmutableJSONValue | bool | int | float, ...],
    ) -> ImmutableJSONArray:
        if not isinstance(values, tuple):
            raise TypeError("immutable JSON array values must be a tuple")
        canonical_values = tuple(_canonicalize_immutable_json_value(value) for value in tuple.__iter__(values))
        return super().__new__(cls, canonical_values)

    @override
    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other) or not isinstance(other, ImmutableJSONArray):
            return False
        return _immutable_json_semantic_key(self) == _immutable_json_semantic_key(other)

    @override
    def __ne__(self, other: object) -> bool:
        return not self == other

    @override
    def __hash__(self) -> int:
        return hash((type(self), _immutable_json_semantic_key(self)))


class ImmutableJSONObject(tuple[tuple[str, ImmutableJSONValue], ...]):
    """Immutable JSON object whose entries preserve order and distinct value semantics."""

    def __new__(
        cls,
        entries: tuple[tuple[str, ImmutableJSONValue | bool | int | float], ...],
    ) -> ImmutableJSONObject:
        if not isinstance(entries, tuple):
            raise TypeError("immutable JSON object entries must be a tuple")
        keys: set[str] = set()
        canonical_entries: list[tuple[str, ImmutableJSONValue]] = []
        for entry in tuple.__iter__(entries):
            if not isinstance(entry, tuple) or tuple.__len__(entry) != 2:
                raise TypeError("immutable JSON object entries must be string-keyed pairs")
            key = tuple.__getitem__(entry, 0)
            member = tuple.__getitem__(entry, 1)
            if not isinstance(key, str):
                raise TypeError("immutable JSON object entries must be string-keyed pairs")
            key = str.__str__(key)
            if key in keys:
                raise ValueError("immutable JSON object entries must not contain duplicate keys")
            keys.add(key)
            canonical_entries.append((key, _canonicalize_immutable_json_value(member)))
        return super().__new__(cls, tuple(canonical_entries))

    @override
    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other) or not isinstance(other, ImmutableJSONObject):
            return False
        return _immutable_json_semantic_key(self) == _immutable_json_semantic_key(other)

    @override
    def __ne__(self, other: object) -> bool:
        return not self == other

    @override
    def __hash__(self) -> int:
        return hash((type(self), _immutable_json_semantic_key(self)))


type _ImmutableJSONSemanticKey = (
    tuple[Literal["null"], None]
    | tuple[Literal["boolean"], bool]
    | tuple[Literal["integer"], int]
    | tuple[Literal["float"], str]
    | tuple[Literal["string"], str]
    | tuple[Literal["array"], tuple["_ImmutableJSONSemanticKey", ...]]
    | tuple[Literal["object"], tuple[tuple[str, "_ImmutableJSONSemanticKey"], ...]]
)


def _immutable_json_semantic_key(value: ImmutableJSONValue) -> _ImmutableJSONSemanticKey:
    if isinstance(value, ImmutableJSONBoolean):
        return ("boolean", value.value)
    if isinstance(value, ImmutableJSONInteger):
        return ("integer", value.value)
    if isinstance(value, ImmutableJSONFloat):
        return ("float", value.value.hex())
    if value is None:
        return ("null", None)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, ImmutableJSONArray):
        return ("array", tuple(_immutable_json_semantic_key(member) for member in value))
    if isinstance(value, ImmutableJSONObject):
        return (
            "object",
            tuple((key, _immutable_json_semantic_key(member)) for key, member in value),
        )
    raise TypeError("value is not immutable JSON")


def _canonicalize_immutable_json_value(value: object) -> ImmutableJSONValue:
    """Remove user-defined scalar and container behavior at the immutable boundary."""
    if type(value) is ImmutableJSONBoolean:
        return value
    if isinstance(value, ImmutableJSONBoolean):
        return ImmutableJSONBoolean(value.value)
    if type(value) is ImmutableJSONInteger:
        return value
    if isinstance(value, ImmutableJSONInteger):
        return ImmutableJSONInteger(int.__int__(value.value))
    if type(value) is ImmutableJSONFloat:
        return value
    if isinstance(value, ImmutableJSONFloat):
        return ImmutableJSONFloat(float.__float__(value.value))
    if isinstance(value, bool):
        return ImmutableJSONBoolean(value)
    if isinstance(value, int):
        return ImmutableJSONInteger(int.__int__(value))
    if isinstance(value, float):
        return ImmutableJSONFloat(float.__float__(value))
    if value is None:
        return value
    if type(value) is str:
        return value
    if isinstance(value, str):
        return str.__str__(value)
    if type(value) is ImmutableJSONObject:
        return value
    if isinstance(value, ImmutableJSONObject):
        return ImmutableJSONObject(tuple(tuple.__iter__(value)))
    if type(value) is ImmutableJSONArray:
        return value
    if isinstance(value, ImmutableJSONArray):
        return ImmutableJSONArray(tuple(tuple.__iter__(value)))
    raise TypeError("provider payload must contain only tagged immutable JSON containers")


def freeze_json_value(value: MutableJSONValue) -> ImmutableJSONValue:
    """Recursively freeze JSON with one canonical representation for every value kind."""
    return _freeze_json_value(value)


def _freeze_json_value(value: MutableJSONValue) -> ImmutableJSONValue:
    if isinstance(value, dict):
        return ImmutableJSONObject(tuple((key, _freeze_json_value(member)) for key, member in value.items()))
    if isinstance(value, list):
        return ImmutableJSONArray(tuple(_freeze_json_value(member) for member in value))
    return _canonicalize_immutable_json_value(value)


def thaw_json_value(value: ImmutableJSONValue) -> MutableJSONValue:
    """Return a structurally faithful mutable JSON copy for a consumer boundary."""
    if isinstance(value, ImmutableJSONBoolean):
        return value.value
    if isinstance(value, ImmutableJSONInteger):
        return value.value
    if isinstance(value, ImmutableJSONFloat):
        return value.value
    if isinstance(value, ImmutableJSONObject):
        return {key: thaw_json_value(member) for key, member in value}
    if isinstance(value, ImmutableJSONArray):
        return [thaw_json_value(member) for member in value]
    return value


def _require_non_blank(field_name: str, value: str) -> str:
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{field_name} must not be blank")
    return normalized_value


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class OpaqueMetadata:
    """Immutable caller correlation hints with unique opaque string keys.

    Providers round-trip this value inside submit controls. Returned metadata
    is user-controlled input and must never be treated as authorization proof.
    """

    entries: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise TypeError("opaque metadata entries must be a tuple")
        keys: set[str] = set()
        for entry in self.entries:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("opaque metadata entries must be string pairs")
            key, value = entry
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("opaque metadata entries must be string pairs")
            if not key.strip():
                raise ValueError("opaque metadata keys must not be blank")
            if key in keys:
                raise ValueError("opaque metadata keys must be unique")
            keys.add(key)

    def as_dict(self) -> dict[str, str]:
        """Return a mutable copy for one provider serialization boundary."""
        return dict(self.entries)


class OperationFailureCode(StrEnum):
    """Stable safe failure categories shared across provider boundaries."""

    CLOSED = "closed"
    AUTHENTICATION = "authentication"
    TENANT_IDENTIFICATION = "tenant_identification"
    MISSING_PERMISSION = "missing_permission"
    DIRECTORY_INCOMPLETE = "directory_incomplete"
    DESTINATION_UNREACHABLE = "destination_unreachable"
    INVALID_DESTINATION = "invalid_destination"
    RENDERING = "rendering"
    STALE_REFERENCE = "stale_reference"
    RATE_LIMITED = "rate_limited"
    AMBIGUOUS = "ambiguous"
    PROVIDER = "provider"
    EVENT_AUTHENTICATION = "event_authentication"
    EVENT_RETRY = "event_retry"


@dataclass(frozen=True, slots=True)
class OperationFailure:
    """Provider-normalized failure that never carries credentials or raw SDK state."""

    provider: IMProvider
    code: OperationFailureCode
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", _require_non_blank("failure message", self.message))


@dataclass(frozen=True, slots=True)
class PermissionFact:
    """Safe baseline permission fact returned by credential testing."""

    name: str
    granted: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_blank("permission name", self.name))


@dataclass(frozen=True, slots=True)
class CredentialTestSuccess:
    """Authenticated provider and stable tenant facts for bound credentials."""

    provider: IMProvider
    provider_tenant_id: str
    permissions: tuple[PermissionFact, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_tenant_id",
            _require_non_blank("provider tenant id", self.provider_tenant_id),
        )
        if not isinstance(self.permissions, tuple) or not self.permissions:
            raise ValueError("credential success requires confirmed permissions")
        if not all(permission.granted for permission in self.permissions):
            raise ValueError("credential success cannot contain a denied permission")


type CredentialTestResult = CredentialTestSuccess | OperationFailure


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """Minimal identity facts retained in a complete provider snapshot."""

    provider_user_id: str
    display_name: str
    email: str | None
    available: bool | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_user_id", _require_non_blank("provider user id", self.provider_user_id))
        object.__setattr__(self, "display_name", _require_non_blank("display name", self.display_name))
        if self.email is not None:
            object.__setattr__(self, "email", _require_non_blank("email", self.email))


@dataclass(frozen=True, slots=True)
class DirectorySnapshot:
    """One immutable complete directory read with no provider cursor state."""

    provider: IMProvider
    provider_tenant_id: str
    entries: tuple[DirectoryEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_tenant_id",
            _require_non_blank("provider tenant id", self.provider_tenant_id),
        )
        if not isinstance(self.entries, tuple):
            raise TypeError("directory entries must be a tuple")


type DirectoryReadResult = DirectorySnapshot | OperationFailure


class CardActionKind(StrEnum):
    """Portable card controls supported by provider-specific assessment."""

    OPEN_URL = "open_url"
    SUBMIT = "submit"


@dataclass(frozen=True, slots=True)
class CardAction:
    """One normalized card action with opaque provider-independent value."""

    action_id: str
    label: str
    kind: CardActionKind
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _require_non_blank("card action id", self.action_id))
        object.__setattr__(self, "label", _require_non_blank("card action label", self.label))
        object.__setattr__(self, "value", _require_non_blank("card action value", self.value))


@dataclass(frozen=True, slots=True)
class CardIntent:
    """Field-complete generic card intent assessed before provider rendering."""

    title: str | None
    body: str
    facts: tuple[tuple[str, str], ...]
    actions: tuple[CardAction, ...]
    fallback_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.facts, tuple) or not isinstance(self.actions, tuple):
            raise TypeError("card facts and actions must be tuples")
        if self.title is not None:
            object.__setattr__(self, "title", _require_non_blank("card title", self.title))
        object.__setattr__(self, "body", _require_non_blank("card body", self.body))
        object.__setattr__(self, "fallback_text", _require_non_blank("card fallback text", self.fallback_text))
        for fact_name, fact_value in self.facts:
            _require_non_blank("card fact name", fact_name)
            _require_non_blank("card fact value", fact_value)


@dataclass(frozen=True, slots=True)
class CardAssessment:
    """Side-effect-free provider representability decision."""

    representable: bool
    reason: str | None

    def __post_init__(self) -> None:
        if self.reason is not None:
            object.__setattr__(self, "reason", _require_non_blank("assessment reason", self.reason))


@dataclass(frozen=True, slots=True)
class MessageAccepted[ReferenceT]:
    """Provider acceptance evidence, distinct from end-user delivery."""

    reference: ReferenceT
    provider_request_id: str | None

    def __post_init__(self) -> None:
        if self.provider_request_id is not None:
            object.__setattr__(
                self,
                "provider_request_id",
                _require_non_blank("provider request id", self.provider_request_id),
            )


type MessageResult[ReferenceT] = MessageAccepted[ReferenceT] | OperationFailure
type DestinationTestResult = OperationFailure | None
type CardAssessmentResult = CardAssessment | OperationFailure


@dataclass(frozen=True, slots=True)
class WebhookRequest:
    """Framework-neutral Webhook input captured at the HTTP boundary."""

    method: str
    headers: tuple[tuple[str, str], ...]
    query: tuple[tuple[str, str], ...]
    body: bytes
    received_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", _require_non_blank("HTTP method", self.method).upper())
        _require_aware("received_at", self.received_at)


@dataclass(frozen=True, slots=True)
class WebhookResponse:
    """Framework-neutral response already encoded for one provider."""

    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def __post_init__(self) -> None:
        if not 100 <= self.status_code <= 599:
            raise ValueError("status code must be a valid HTTP status")


@dataclass(frozen=True, slots=True)
class AuthenticatedIMEvent:
    """Immutable authenticated provider evidence passed to independent consumers.

    ``provider_event_id`` is optional by design. Concrete provider code may set
    it only when the provider supplies a documented redelivery-stable event ID;
    hashes, timestamps, message references, and ACK envelopes are not IDs.
    """

    provider: IMProvider
    provider_tenant_id: str
    provider_event_id: str | None
    provider_event_time: datetime | None
    received_at: datetime
    provider_event_type: str | None
    provider_payload: ImmutableJSONObject

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_tenant_id",
            _require_non_blank("provider tenant id", self.provider_tenant_id),
        )
        if self.provider_event_id is not None:
            object.__setattr__(
                self,
                "provider_event_id",
                _require_non_blank("provider event id", self.provider_event_id),
            )
        if self.provider_event_type is not None:
            object.__setattr__(
                self,
                "provider_event_type",
                _require_non_blank("provider event type", self.provider_event_type),
            )
        if self.provider_event_time is not None:
            _require_aware("provider_event_time", self.provider_event_time)
        _require_aware("received_at", self.received_at)
        raw_provider_payload = self.provider_payload
        if isinstance(raw_provider_payload, ImmutableJSONObject):
            provider_payload = ImmutableJSONObject(tuple(tuple.__iter__(raw_provider_payload)))
        elif isinstance(raw_provider_payload, tuple):
            provider_payload = ImmutableJSONObject(raw_provider_payload)
        else:
            raise TypeError("provider payload must be an immutable JSON object")
        object.__setattr__(self, "provider_payload", provider_payload)


class EventAcceptance(StrEnum):
    """Whether the application sink took responsibility for one event."""

    ACCEPTED = "accepted"
    RETRY = "retry"


class IMEventSink(Protocol):
    """The only downstream dependency of provider event capabilities."""

    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        """Take responsibility for one authenticated event or request retry."""
        ...


class StopSignal(Protocol):
    """Thread-safe stop observation used by long-running stream clients."""

    def is_set(self) -> bool:
        """Return whether the caller requested stream termination."""
        ...


@dataclass(frozen=True, slots=True)
class WebhookChallenge:
    """Authenticated provider challenge response that bypasses the sink."""

    response: WebhookResponse


@dataclass(frozen=True, slots=True)
class WebhookRejected:
    """Provider-authentication or control rejection that bypasses the sink."""

    response: WebhookResponse


@dataclass(frozen=True, slots=True)
class WebhookDelivery:
    """Authenticated event plus provider-specific ACK and replay facts.

    A replay key is internal transport evidence, not a Provider event ID. The
    adapter remembers it only after the sink accepts the delivery and only
    until the authenticated request can no longer be replayed.
    """

    event: AuthenticatedIMEvent
    accepted_response: WebhookResponse
    retry_response: WebhookResponse
    replay_key: str | None = None
    replay_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if (self.replay_key is None) != (self.replay_expires_at is None):
            raise ValueError("Webhook replay key and expiration must be provided together")
        if self.replay_key is not None:
            object.__setattr__(self, "replay_key", _require_non_blank("Webhook replay key", self.replay_key))
        if self.replay_expires_at is not None:
            _require_aware("replay_expires_at", self.replay_expires_at)


type WebhookParseResult = WebhookChallenge | WebhookRejected | WebhookDelivery
type StreamRunResult = OperationFailure | None


class IMDirectory(Protocol):
    """Adapter-bound complete-snapshot directory view."""

    def read_snapshot(self) -> DirectoryReadResult:
        """Return a complete immutable snapshot or one typed failure."""
        ...


class IMMessaging(Protocol[DestinationT, MessagingReferenceT]):
    """Required basic messaging view for one provider destination type."""

    def test_destination(self, destination: DestinationT) -> DestinationTestResult:
        """Test provider destination reachability without changing credentials."""
        ...

    def send_text(self, destination: DestinationT, body: str) -> MessageResult[MessagingReferenceT]:
        """Make at most one provider send operation with no automatic replay."""
        ...


class IMDynamicCardMessaging(Protocol[DestinationT, ReferenceT]):
    """Optional card assessment, send, and exact-reference update view."""

    def assess(self, intent: CardIntent) -> CardAssessmentResult:
        """Assess representability without making a provider call."""
        ...

    def send_card(
        self,
        destination: DestinationT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]:
        """Render one card and round-trip metadata only through submit controls."""
        ...

    def update_card(
        self,
        reference: ReferenceT,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[ReferenceT]:
        """Update the exact reference with submit-only metadata round-tripping."""
        ...


class IMWebhookEvents(Protocol):
    """Caller-driven provider Webhook handling capability."""

    def handle(self, request: WebhookRequest, sink: IMEventSink) -> WebhookResponse:
        """Return the encoded provider response after applying sink ACK semantics."""
        ...


class IMStreamEvents(Protocol):
    """SDK-driven provider stream lifecycle capability."""

    def run(self, sink: IMEventSink, stop: StopSignal) -> StreamRunResult:
        """Own connection callbacks, reconnect, stop, and ACK mapping."""
        ...


class IMProviderAdapter(Protocol[DestinationT, ReferenceT]):
    """Immutable composition root exposing narrow shared-context views."""

    def test_credentials(self) -> CredentialTestResult: ...

    @property
    def directory(self) -> IMDirectory: ...

    @property
    def messaging(self) -> IMMessaging[DestinationT, ReferenceT]: ...

    @property
    def dynamic_card_messaging(self) -> IMDynamicCardMessaging[DestinationT, ReferenceT] | None: ...

    @property
    def webhook_events(self) -> IMWebhookEvents | None: ...

    @property
    def stream_events(self) -> IMStreamEvents | None: ...

    def close(self) -> None: ...
