"""Microsoft Graph and Bot Framework boundary owned by ``MicrosoftTeamsAdapter``.

Graph and Bot Framework access tokens use distinct scopes and cache entries.
The client never retries side-effecting Activity operations; directory-only
rate-limit handling remains internal and returns no partial snapshot.
Every Provider-owned identifier interpolated into a URL is encoded as one path
segment before a token-bearing request is built.
Bot token audience identifies this bot, while signing-key endorsements restrict
the Activity ``channelId``; these independent checks must not be conflated.
Token checks distinguish throttling and upstream failures from confirmed OAuth
client rejection.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Literal, TypedDict
from urllib.parse import quote

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError, field_validator

from core.helper.ssrf_proxy import create_ssrf_protected_client
from core.human_input_v2.entities import IMProvider

from ..client_roles import _ProviderClientContext
from ..contracts import (
    AuthenticatedIMEvent,
    CardActionKind,
    CardAssessment,
    CardIntent,
    CredentialTestResult,
    CredentialTestSuccess,
    DestinationTestResult,
    DirectoryEntry,
    DirectoryReadResult,
    DirectorySnapshot,
    ImmutableJSONObject,
    MessageAccepted,
    MessageResult,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
    PermissionFact,
    WebhookDelivery,
    WebhookParseResult,
    WebhookRejected,
    WebhookRequest,
    WebhookResponse,
    freeze_json_value,
)
from ..provider_types import (
    MicrosoftTeamsAdapterConfig,
    TeamsMessageReference,
    TeamsPersonalConversationDestination,
    _extract_https_origin,
)

_GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_BOT_SCOPE = "https://api.botframework.com/.default"
_REQUIRED_GRAPH_ROLES = ("Organization.Read.All", "User.Read.All")
_ACCOUNT_STATUS_ROLE = "User.EnableDisableAccount.All"
_HTTP_TIMEOUT_SECONDS = 10.0
_MAX_DIRECTORY_RATE_LIMIT_RETRIES = 3
_TOKEN_EXPIRY_SKEW_SECONDS = 60
_OPENID_CACHE_TTL_SECONDS = 3600
_JWK_CACHE_TTL_SECONDS = 3600
_ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"
_BOT_OPENID_METADATA_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
_BOT_ISSUER = "https://api.botframework.com"
_TOKEN_AUTHENTICATION_ERRORS = frozenset({"invalid_client"})
_CARD_SUBMIT_ACTIVITY_TYPE = "message"
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


def _encode_path_segment(provider_id: str) -> str:
    """Encode one Provider identifier without allowing dot-segment traversal."""
    if provider_id in (".", ".."):
        raise ValueError("provider identifier must not be a dot path segment")
    try:
        return quote(provider_id, safe="", encoding="utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("provider identifier must be valid Unicode") from error


class _TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    access_token: str
    expires_in: int


class _TokenErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    error: str


class _OrganizationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str


class _GraphUser(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    display_name: str = Field(alias="displayName")
    mail: str | None = None
    account_enabled: bool | None = Field(default=None, alias="accountEnabled")


class _GraphUsersResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    value: tuple[_GraphUser, ...]
    next_link: str | None = Field(default=None, alias="@odata.nextLink")


class _ActivityResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str


class _ConversationMemberResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str


class _OpenIDMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    issuer: str
    jwks_uri: str


class _BotClaims(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    expires_at: datetime = Field(alias="exp")
    service_url: str = Field(alias="serviceurl")


class _JWKSet(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    keys: tuple[dict[str, JsonValue], ...]


class _ActivityTenant(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Microsoft Activity tenant id must not be blank")
        return value


class _ActivityChannelData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    tenant: _ActivityTenant


class _ActivityAuthenticationContext(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    channel_id: str | None = Field(default=None, alias="channelId")
    service_url: str = Field(alias="serviceUrl")
    channel_data: _ActivityChannelData = Field(alias="channelData")


class _CardSubmitValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action_id: str
    value: str
    metadata: dict[str, str] | None = None

    @field_validator("action_id", "value")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Microsoft card submit values must not be blank")
        return value


class _Activity(_ActivityAuthenticationContext):
    type: Literal["message"]
    value: _CardSubmitValue
    timestamp: datetime | None = None

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Microsoft Activity timestamp must be timezone-aware")
        return value


class _ActivityPayload(TypedDict):
    type: str
    text: str


class _TokenCacheEntry:
    token: str
    expires_at: float
    roles: frozenset[str]

    def __init__(self, token: str, expires_at: float, roles: frozenset[str]) -> None:
        self.token = token
        self.expires_at = expires_at
        self.roles = roles


def _build_http_client() -> httpx.Client:
    return create_ssrf_protected_client(
        verify=True,
        timeout=_HTTP_TIMEOUT_SECONDS,
    )


def _failure(code: OperationFailureCode, message: str) -> OperationFailure:
    return OperationFailure(IMProvider.MS_TEAMS, code, message)


def _header(request: WebhookRequest, name: str) -> str | None:
    normalized = name.casefold()
    for header_name, header_value in request.headers:
        if header_name.casefold() == normalized:
            return header_value
    return None


def _card_payload(intent: CardIntent, metadata: OpaqueMetadata) -> dict[str, JsonValue]:
    """Render caller metadata only inside Adaptive Card submit data."""
    body: list[JsonValue] = []
    if intent.title is not None:
        body.append({"type": "TextBlock", "text": intent.title, "weight": "Bolder"})
    body.append({"type": "TextBlock", "text": intent.body, "wrap": True})
    if intent.facts:
        body.append(
            {
                "type": "FactSet",
                "facts": [{"title": name, "value": value} for name, value in intent.facts],
            }
        )
    submit_metadata: dict[str, JsonValue] = {}
    for key, value in metadata.entries:
        submit_metadata[key] = value
    actions: list[JsonValue] = []
    for action in intent.actions:
        if action.kind is CardActionKind.OPEN_URL:
            actions.append({"type": "Action.OpenUrl", "title": action.label, "url": action.value})
        else:
            actions.append(
                {
                    "type": "Action.Submit",
                    "title": action.label,
                    "data": {
                        "action_id": action.action_id,
                        "value": action.value,
                        "metadata": submit_metadata,
                    },
                }
            )
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
        "actions": actions,
    }


class _MicrosoftTeamsProviderClient:
    """Adapter-owned Graph and Bot roles over one caller-owned HTTP pool."""

    _config: MicrosoftTeamsAdapterConfig
    _http_client: httpx.Client
    _token_cache: dict[str, _TokenCacheEntry]
    _openid_metadata: _OpenIDMetadata | None
    _openid_metadata_expires_at: float
    _jwk_set: _JWKSet | None
    _jwk_set_expires_at: float

    def __init__(self, config: MicrosoftTeamsAdapterConfig, http_client: httpx.Client) -> None:
        self._config = config
        self._http_client = http_client
        self._token_cache = {}
        self._openid_metadata = None
        self._openid_metadata_expires_at = 0
        self._jwk_set = None
        self._jwk_set_expires_at = 0

    def _token(self, scope: str) -> _TokenCacheEntry | OperationFailure:
        cached = self._token_cache.get(scope)
        now = time.monotonic()
        if cached is not None and cached.expires_at > now:
            return cached
        try:
            tenant_path_segment = _encode_path_segment(self._config.tenant_id)
        except ValueError:
            return _failure(OperationFailureCode.AUTHENTICATION, "Microsoft tenant identifier was invalid")
        token_url = f"https://login.microsoftonline.com/{tenant_path_segment}/oauth2/v2.0/token"
        try:
            response = self._http_client.post(
                token_url,
                data={
                    "client_id": self._config.client_id,
                    "client_secret": self._config.client_secret,
                    "grant_type": "client_credentials",
                    "scope": scope,
                },
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.PROVIDER, "Microsoft token request failed")
        if response.status_code == 429:
            return _failure(OperationFailureCode.RATE_LIMITED, "Microsoft rate limited the token request")
        if response.status_code >= 500:
            return _failure(OperationFailureCode.PROVIDER, "Microsoft token service failed")
        if response.status_code >= 400:
            try:
                token_error = _TokenErrorResponse.model_validate_json(response.content)
            except ValidationError:
                return _failure(OperationFailureCode.PROVIDER, "Microsoft token request was rejected")
            if token_error.error in _TOKEN_AUTHENTICATION_ERRORS:
                return _failure(OperationFailureCode.AUTHENTICATION, "Microsoft rejected the bound credentials")
            return _failure(OperationFailureCode.PROVIDER, "Microsoft token request was rejected")
        try:
            token_response = _TokenResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.PROVIDER, "Microsoft token response was invalid")
        if not token_response.access_token.strip() or token_response.expires_in <= 0:
            return _failure(OperationFailureCode.PROVIDER, "Microsoft token response was incomplete")
        roles: frozenset[str] = frozenset()
        if scope == _GRAPH_SCOPE:
            try:
                claims = jwt.decode(
                    token_response.access_token,
                    options={"verify_signature": False, "verify_aud": False},
                    algorithms=["RS256", "none"],
                )
                raw_roles = claims.get("roles", ())
                if not isinstance(raw_roles, (list, tuple)) or not all(isinstance(role, str) for role in raw_roles):
                    return _failure(OperationFailureCode.PROVIDER, "Microsoft Graph token roles were invalid")
                roles = frozenset(raw_roles)
            except jwt.PyJWTError:
                return _failure(OperationFailureCode.PROVIDER, "Microsoft Graph token was invalid")
        entry = _TokenCacheEntry(
            token_response.access_token,
            now + max(0, token_response.expires_in - _TOKEN_EXPIRY_SKEW_SECONDS),
            roles,
        )
        self._token_cache[scope] = entry
        return entry

    def _graph_token(self) -> _TokenCacheEntry | OperationFailure:
        return self._token(_GRAPH_SCOPE)

    def _bot_token(self) -> _TokenCacheEntry | OperationFailure:
        return self._token(_BOT_SCOPE)

    def test_credentials(self) -> CredentialTestResult:
        token = self._graph_token()
        if isinstance(token, OperationFailure):
            return token
        missing_roles = tuple(role for role in _REQUIRED_GRAPH_ROLES if role not in token.roles)
        if missing_roles:
            return _failure(
                OperationFailureCode.MISSING_PERMISSION,
                f"Microsoft Graph token is missing required roles: {', '.join(missing_roles)}",
            )
        try:
            tenant_path_segment = _encode_path_segment(self._config.tenant_id)
        except ValueError:
            return _failure(OperationFailureCode.TENANT_IDENTIFICATION, "Microsoft tenant identifier was invalid")
        try:
            response = self._http_client.get(
                f"{_GRAPH_ROOT}/organization/{tenant_path_segment}",
                headers={"authorization": f"Bearer {token.token}"},
            )
            organization = _OrganizationResponse.model_validate_json(response.content)
        except httpx.RequestError:
            return _failure(OperationFailureCode.PROVIDER, "Microsoft organization request failed")
        except ValidationError:
            return _failure(OperationFailureCode.TENANT_IDENTIFICATION, "Microsoft organization response was invalid")
        if response.status_code >= 400 or organization.id != self._config.tenant_id:
            return _failure(OperationFailureCode.TENANT_IDENTIFICATION, "Microsoft tenant identity did not match")
        return CredentialTestSuccess(
            IMProvider.MS_TEAMS,
            organization.id,
            tuple(PermissionFact(role, True) for role in _REQUIRED_GRAPH_ROLES),
        )

    def read_directory(self) -> DirectoryReadResult:
        token = self._graph_token()
        if isinstance(token, OperationFailure):
            return token
        if "User.Read.All" not in token.roles:
            return _failure(OperationFailureCode.MISSING_PERMISSION, "Microsoft Graph token cannot read users")
        select_fields = "id,displayName,mail"
        if _ACCOUNT_STATUS_ROLE in token.roles:
            select_fields += ",accountEnabled"
        next_url: str | None = f"{_GRAPH_ROOT}/users"
        initial_query = {"$select": select_fields}
        if self._config.directory_page_size is not None:
            initial_query["$top"] = str(self._config.directory_page_size)
        query: dict[str, str] | None = initial_query
        entries: list[DirectoryEntry] = []
        while next_url is not None:
            try:
                next_origin = _extract_https_origin(next_url, origin_only=False, allow_query=True)
            except ValueError:
                return _failure(OperationFailureCode.DIRECTORY_INCOMPLETE, "Microsoft directory next link was invalid")
            if next_origin != "https://graph.microsoft.com":
                return _failure(
                    OperationFailureCode.DIRECTORY_INCOMPLETE, "Microsoft directory next link was untrusted"
                )
            retries = 0
            while True:
                try:
                    response = self._http_client.get(
                        next_url,
                        params=query,
                        headers={"authorization": f"Bearer {token.token}"},
                    )
                except httpx.RequestError:
                    return _failure(OperationFailureCode.DIRECTORY_INCOMPLETE, "Microsoft directory request failed")
                if response.status_code != 429:
                    break
                try:
                    retry_after = int(response.headers.get("retry-after", ""))
                except ValueError:
                    retry_after = -1
                if retry_after < 0 or retries >= _MAX_DIRECTORY_RATE_LIMIT_RETRIES:
                    return _failure(
                        OperationFailureCode.DIRECTORY_INCOMPLETE, "Microsoft directory remained rate limited"
                    )
                retries += 1
                time.sleep(retry_after)
            try:
                users_response = _GraphUsersResponse.model_validate_json(response.content)
            except ValidationError:
                return _failure(OperationFailureCode.DIRECTORY_INCOMPLETE, "Microsoft directory response was invalid")
            if response.status_code >= 400:
                return _failure(OperationFailureCode.DIRECTORY_INCOMPLETE, "Microsoft directory request was rejected")
            try:
                entries.extend(
                    DirectoryEntry(
                        user.id,
                        user.display_name,
                        user.mail,
                        user.account_enabled,
                    )
                    for user in users_response.value
                )
            except ValueError:
                return _failure(OperationFailureCode.DIRECTORY_INCOMPLETE, "Microsoft directory user was invalid")
            next_url = users_response.next_link
            query = None
        return DirectorySnapshot(IMProvider.MS_TEAMS, self._config.tenant_id, tuple(entries))

    def _destination_failure(
        self,
        destination: TeamsPersonalConversationDestination,
    ) -> OperationFailure | None:
        try:
            service_origin = _extract_https_origin(destination.service_url, origin_only=False)
        except ValueError:
            return _failure(OperationFailureCode.INVALID_DESTINATION, "Microsoft destination service URL is invalid")
        if service_origin not in self._config.trusted_service_url_origins:
            return _failure(OperationFailureCode.INVALID_DESTINATION, "Microsoft destination service URL is untrusted")
        try:
            _encode_path_segment(destination.conversation_id)
            _encode_path_segment(destination.user_id)
        except ValueError:
            return _failure(OperationFailureCode.INVALID_DESTINATION, "Microsoft destination identifier is invalid")
        return None

    def test_destination(self, destination: TeamsPersonalConversationDestination) -> DestinationTestResult:
        if failure := self._destination_failure(destination):
            return failure
        conversation_path_segment = _encode_path_segment(destination.conversation_id)
        user_path_segment = _encode_path_segment(destination.user_id)
        token = self._bot_token()
        if isinstance(token, OperationFailure):
            return token
        try:
            response = self._http_client.get(
                f"{destination.service_url.rstrip('/')}/v3/conversations/{conversation_path_segment}/members/{user_path_segment}",
                headers={"authorization": f"Bearer {token.token}"},
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.PROVIDER, "Microsoft destination check failed")
        if response.status_code in (403, 404):
            return _failure(OperationFailureCode.DESTINATION_UNREACHABLE, "Microsoft user is unreachable")
        if response.status_code >= 400:
            return _failure(OperationFailureCode.PROVIDER, "Microsoft destination check was rejected")
        try:
            member_response = _ConversationMemberResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.PROVIDER, "Microsoft destination response was invalid")
        if member_response.id != destination.user_id:
            return _failure(OperationFailureCode.DESTINATION_UNREACHABLE, "Microsoft destination user did not match")
        return None

    def send_text(
        self,
        destination: TeamsPersonalConversationDestination,
        body: str,
    ) -> MessageResult[TeamsMessageReference]:
        return self._send_activity(destination, {"type": "message", "text": body})

    def assess_card(self, intent: CardIntent) -> CardAssessment:
        return CardAssessment(True, None)

    def send_card(
        self,
        destination: TeamsPersonalConversationDestination,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[TeamsMessageReference]:
        return self._send_activity(
            destination,
            {
                "type": "message",
                "text": intent.fallback_text,
                "attachments": [
                    {"contentType": _ADAPTIVE_CARD_CONTENT_TYPE, "content": _card_payload(intent, metadata)}
                ],
            },
        )

    def update_card(
        self,
        reference: TeamsMessageReference,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[TeamsMessageReference]:
        destination = TeamsPersonalConversationDestination(
            reference.service_url,
            reference.conversation_id,
            reference.user_id,
        )
        return self._send_activity(
            destination,
            {
                "type": "message",
                "text": intent.fallback_text,
                "attachments": [
                    {"contentType": _ADAPTIVE_CARD_CONTENT_TYPE, "content": _card_payload(intent, metadata)}
                ],
            },
            activity_id=reference.activity_id,
        )

    def _send_activity(
        self,
        destination: TeamsPersonalConversationDestination,
        payload: dict[str, JsonValue] | _ActivityPayload,
        activity_id: str | None = None,
    ) -> MessageResult[TeamsMessageReference]:
        if failure := self._destination_failure(destination):
            return failure
        conversation_path_segment = _encode_path_segment(destination.conversation_id)
        activity_path_segment: str | None = None
        if activity_id is not None:
            try:
                activity_path_segment = _encode_path_segment(activity_id)
            except ValueError:
                return _failure(OperationFailureCode.INVALID_DESTINATION, "Microsoft Activity identifier is invalid")
        token = self._bot_token()
        if isinstance(token, OperationFailure):
            return token
        activity_url = f"{destination.service_url.rstrip('/')}/v3/conversations/{conversation_path_segment}/activities"
        if activity_path_segment is not None:
            activity_url += f"/{activity_path_segment}"
        try:
            response = self._http_client.request(
                "PUT" if activity_id is not None else "POST",
                activity_url,
                json=payload,
                headers={"authorization": f"Bearer {token.token}"},
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.AMBIGUOUS, "Microsoft Activity request outcome is ambiguous")
        if response.status_code >= 400:
            code = (
                OperationFailureCode.STALE_REFERENCE
                if activity_id is not None and response.status_code == 404
                else OperationFailureCode.PROVIDER
            )
            return _failure(code, "Microsoft rejected the Activity request")
        try:
            activity_response = _ActivityResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.AMBIGUOUS, "Microsoft Activity response was invalid")
        if activity_id is not None and activity_response.id != activity_id:
            return _failure(OperationFailureCode.AMBIGUOUS, "Microsoft update changed the Activity reference")
        reference = TeamsMessageReference(
            destination.service_url,
            destination.conversation_id,
            destination.user_id,
            activity_response.id,
        )
        return MessageAccepted(reference, response.headers.get("request-id"))

    def parse_webhook(self, request: WebhookRequest) -> WebhookParseResult:
        """Authenticate Bot context before classifying malformed Activity fields as HTTP 400."""
        rejected = WebhookRejected(WebhookResponse(401, (), b""))
        malformed = WebhookRejected(WebhookResponse(400, (), b""))
        if request.method != "POST":
            return rejected
        authorization = _header(request, "authorization")
        if authorization is None or not authorization.startswith("Bearer "):
            return rejected
        token = authorization.removeprefix("Bearer ").strip()
        try:
            provider_payload = _JSON_OBJECT_ADAPTER.validate_json(request.body)
            authentication_context = _ActivityAuthenticationContext.model_validate(provider_payload)
            metadata = self._load_openid_metadata()
            if metadata.issuer != _BOT_ISSUER:
                return rejected
            jwk_set = self._load_jwk_set(metadata)
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                return rejected
            key_data = next((key for key in jwk_set.keys if key.get("kid") == header["kid"]), None)
            if key_data is None:
                jwk_set = self._load_jwk_set(metadata, force_refresh=True)
                key_data = next((key for key in jwk_set.keys if key.get("kid") == header["kid"]), None)
                if key_data is None:
                    return rejected
            endorsements = key_data.get("endorsements")
            if endorsements is not None:
                if not isinstance(endorsements, list) or not all(
                    isinstance(endorsement, str) for endorsement in endorsements
                ):
                    return rejected
                if endorsements and authentication_context.channel_id not in endorsements:
                    return rejected
            signing_key = jwt.PyJWK.from_dict(key_data).key
            claims = _BotClaims.model_validate(
                jwt.decode(
                    token,
                    signing_key,
                    algorithms=["RS256"],
                    audience=self._config.bot_app_id,
                    issuer=_BOT_ISSUER,
                    options={"require": ["iss", "aud", "nbf", "exp", "serviceurl"]},
                )
            )
        except (httpx.RequestError, ValidationError, jwt.PyJWTError, StopIteration, ValueError):
            return rejected
        if (
            claims.service_url != authentication_context.service_url
            or authentication_context.channel_data.tenant.id != self._config.tenant_id
        ):
            return rejected
        try:
            activity = _Activity.model_validate(provider_payload)
        except ValidationError:
            return malformed
        event = AuthenticatedIMEvent(
            provider=IMProvider.MS_TEAMS,
            provider_tenant_id=activity.channel_data.tenant.id,
            provider_event_id=None,
            provider_event_time=activity.timestamp,
            received_at=request.received_at,
            provider_event_type=_CARD_SUBMIT_ACTIVITY_TYPE,
            provider_payload=ImmutableJSONObject(
                tuple((key, freeze_json_value(value)) for key, value in provider_payload.items())
            ),
        )
        replay_key = hashlib.sha256(token.encode() + b"\0" + request.body).hexdigest()
        return WebhookDelivery(
            event=event,
            accepted_response=WebhookResponse(200, (), b""),
            retry_response=WebhookResponse(500, (), b""),
            replay_key=replay_key,
            replay_expires_at=claims.expires_at.astimezone(UTC),
        )

    def _load_openid_metadata(self) -> _OpenIDMetadata:
        now = time.monotonic()
        if self._openid_metadata is None or self._openid_metadata_expires_at <= now:
            response = self._http_client.get(_BOT_OPENID_METADATA_URL)
            response.raise_for_status()
            metadata = _OpenIDMetadata.model_validate_json(response.content)
            if self._openid_metadata is None or self._openid_metadata.jwks_uri != metadata.jwks_uri:
                self._jwk_set = None
                self._jwk_set_expires_at = 0
            self._openid_metadata = metadata
            self._openid_metadata_expires_at = now + _OPENID_CACHE_TTL_SECONDS
        return self._openid_metadata

    def _load_jwk_set(self, metadata: _OpenIDMetadata, *, force_refresh: bool = False) -> _JWKSet:
        if _extract_https_origin(metadata.jwks_uri, origin_only=False) != "https://login.botframework.com":
            raise ValueError("Microsoft OpenID keys origin is untrusted")
        now = time.monotonic()
        if force_refresh or self._jwk_set is None or self._jwk_set_expires_at <= now:
            response = self._http_client.get(metadata.jwks_uri)
            response.raise_for_status()
            self._jwk_set = _JWKSet.model_validate_json(response.content)
            self._jwk_set_expires_at = now + _JWK_CACHE_TTL_SECONDS
        return self._jwk_set

    def close(self) -> None:
        self._http_client.close()


def create_microsoft_teams_client_context(
    config: MicrosoftTeamsAdapterConfig,
) -> _ProviderClientContext[TeamsPersonalConversationDestination, TeamsMessageReference]:
    client = _MicrosoftTeamsProviderClient(config, _build_http_client())
    return _ProviderClientContext(
        credentials=client,
        directory=client,
        messaging=client,
        card=client,
        webhook=client,
        stream=None,
        owned_resources=(client,),
    )
