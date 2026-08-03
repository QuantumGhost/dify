"""Feishu and Lark OpenAPI boundary owned by ``FeishuLarkAdapter``.

The provider selection determines one fixed OpenAPI host. One adapter-owned
HTTP client and tenant-token cache are reused across capabilities. Directory
reads start from the complete contact scope and publish entries only after every
scope, department, direct-user, and explicit-user page succeeds; provider
cursors never cross the capability boundary. Code-0 directory responses can
omit user names under field-level permission filtering; the adapter fails closed
without inferring names from other identity fields. Messaging validates Provider
address types before token acquisition, never replays send or update operations,
and preserves the exact message ID returned by Feishu/Lark. STREAM validates the
authenticated v2 envelope before exposing immutable provider facts; callback
return remains under the controlled SDK client's 200/500 ACK ownership.
Tenant-token checks distinguish throttling and upstream failures from confirmed
app credential rejection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from threading import Event, RLock
from typing import Protocol
from urllib.parse import quote

import httpx
from lark_oapi.core.json import JSON  # type: ignore[import-untyped]
from lark_oapi.event.callback.model.p2_card_action_trigger import (  # type: ignore[import-untyped]
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from core.helper.ssrf_proxy import create_ssrf_protected_client
from core.human_input_v2.entities import IMProvider

from ..client_roles import _ProviderClientContext
from ..contracts import (
    AuthenticatedIMEvent,
    CardActionKind,
    CardAssessment,
    CardIntent,
    CardSingleSelectInput,
    CardTextInput,
    CredentialTestResult,
    CredentialTestSuccess,
    DestinationTestResult,
    DirectoryEntry,
    DirectoryReadResult,
    DirectorySnapshot,
    EventAcceptance,
    ImmutableJSONObject,
    MessageAccepted,
    MessageResult,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
    PermissionFact,
    StopSignal,
    StreamRunResult,
    freeze_json_value,
)
from ..provider_types import FeishuLarkAdapterConfig, FeishuMessageReference, FeishuUserDestination

_FEISHU_API_ROOT = "https://open.feishu.cn/open-apis"
_LARK_API_ROOT = "https://open.larksuite.com/open-apis"
_OPEN_DEPARTMENT_ID_TYPE = "open_department_id"
_OPEN_USER_ID_TYPE = "open_id"
_SCOPE_PAGE_SIZE = 100
_DIRECTORY_PAGE_SIZE = 50
_MAX_DIRECTORY_RATE_LIMIT_RETRIES = 3
_TOKEN_EXPIRY_SKEW_SECONDS = 60
_HTTP_TIMEOUT_SECONDS = 10.0
_STREAM_STOP_POLL_SECONDS = 0.01
_STREAM_CLOSE_TIMEOUT_SECONDS = 10.0
_STREAM_RUN_CLOSE_TIMEOUT_SECONDS = 1.0
_SUPPORTED_RECEIVE_ID_TYPES = frozenset(("open_id", "user_id", "union_id", "email"))
_TENANT_READ_PERMISSION = "tenant:tenant:readonly"
_USER_BASE_READ_PERMISSION = "contact:user.base:readonly"
_TOKEN_AUTHENTICATION_ERROR_CODES = frozenset({10003})
_TENANT_PERMISSION_ERROR_CODES = frozenset({99991672})
_DIRECTORY_PERMISSION_ERROR_CODES = frozenset({40004, 40014})
_CARD_ACTION_EVENT_TYPE = "card.action.trigger"
_SECOND_TIMESTAMP_DIGITS = 10
_MILLISECOND_TIMESTAMP_DIGITS = 13
_MICROSECOND_TIMESTAMP_DIGITS = 16

logger = logging.getLogger(__name__)


class _TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: int
    msg: str
    tenant_access_token: str | None = None
    expire: int | None = None


class _Tenant(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    tenant_key: str | None = None


class _TenantData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    tenant: _Tenant | None = None


class _TenantResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: int
    msg: str
    data: _TenantData | None = None


class _ScopeData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    department_ids: tuple[str, ...] = ()
    user_ids: tuple[str, ...] = ()
    group_ids: tuple[str, ...] = ()
    has_more: bool = False
    page_token: str | None = None


class _ScopeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: int
    msg: str
    data: _ScopeData | None = None


class _DirectoryScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    department_ids: tuple[str, ...]
    user_ids: tuple[str, ...]


class _Department(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    open_department_id: str


class _DepartmentPageData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    items: tuple[_Department, ...] = ()
    has_more: bool = False
    page_token: str | None = None


class _DepartmentPageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: int
    msg: str
    data: _DepartmentPageData | None = None


class _UserStatus(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    is_frozen: bool | None = None
    is_resigned: bool | None = None
    is_activated: bool | None = None
    is_exited: bool | None = None
    is_unjoin: bool | None = None


class _User(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    open_id: str
    name: str | None = None
    email: str | None = None
    enterprise_email: str | None = None
    status: _UserStatus | None = None


class _UserPageData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    items: tuple[_User, ...] = ()
    has_more: bool = False
    page_token: str | None = None


class _UserPageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: int
    msg: str
    data: _UserPageData | None = None


class _UserData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    user: _User


class _UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: int
    msg: str
    data: _UserData | None = None


class _OpenAPIResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: int
    msg: str


class _BatchGetUserIDEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    user_id: str


class _BatchGetUserIDData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    user_list: tuple[_BatchGetUserIDEntry, ...] = ()


class _BatchGetUserIDResponse(_OpenAPIResponse):
    data: _BatchGetUserIDData | None = None


class _StreamEventHeader(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    event_id: str | None = None
    token: str
    create_time: str | None = None
    event_type: str
    tenant_key: str
    app_id: str

    @field_validator("event_id", "create_time")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional STREAM event header text must not be blank")
        return value

    @field_validator("token", "event_type", "tenant_key", "app_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("STREAM event header text must not be blank")
        return value


class _StreamEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    schema_: str = Field(alias="schema")
    header: _StreamEventHeader
    event: dict[str, JsonValue]

    @field_validator("schema_", mode="before")
    @classmethod
    def validate_schema(cls, value: object) -> object:
        if value != "2.0":
            raise ValueError("STREAM event schema must be 2.0")
        return value


class _MessageData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    message_id: str | None = None


class _MessageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: int
    msg: str
    data: _MessageData | None = None


class _TenantToken:
    token: str
    expires_at: float

    def __init__(self, token: str, expires_at: float) -> None:
        self.token = token
        self.expires_at = expires_at


def _failure(provider: IMProvider, code: OperationFailureCode, message: str) -> OperationFailure:
    return OperationFailure(provider, code, message)


def _api_root(provider: IMProvider) -> str:
    if provider is IMProvider.FEISHU:
        return _FEISHU_API_ROOT
    if provider is IMProvider.LARK:
        return _LARK_API_ROOT
    raise ValueError("Feishu/Lark client requires the Feishu or Lark provider")


def _build_http_client() -> httpx.Client:
    return create_ssrf_protected_client(
        verify=True,
        timeout=_HTTP_TIMEOUT_SECONDS,
    )


def _next_page_token(has_more: bool, page_token: str | None) -> str | None:
    if not has_more:
        return None
    normalized_token = page_token.strip() if page_token is not None else ""
    if not normalized_token:
        raise ValueError("provider pagination omitted its next page token")
    return normalized_token


def _user_availability(status: _UserStatus | None) -> bool | None:
    if status is None:
        return None
    known_statuses = (
        status.is_activated,
        status.is_frozen,
        status.is_resigned,
        status.is_exited,
        status.is_unjoin,
    )
    if all(status_value is None for status_value in known_statuses):
        return None
    if status.is_activated is False:
        return False
    if any(
        status_value is True
        for status_value in (status.is_frozen, status.is_resigned, status.is_exited, status.is_unjoin)
    ):
        return False
    return True if status.is_activated is True else None


def _user_to_directory_entry(user: _User, provider: IMProvider) -> DirectoryEntry | OperationFailure:
    display_name = (user.name or "").strip()
    if not display_name:
        return _failure(
            provider,
            OperationFailureCode.MISSING_PERMISSION,
            f"Feishu/Lark app is missing required permission: {_USER_BASE_READ_PERMISSION}",
        )
    email = (user.email or "").strip() or (user.enterprise_email or "").strip() or None
    return DirectoryEntry(
        user.open_id,
        display_name,
        email,
        _user_availability(user.status),
    )


def _encode_path_segment(provider_id: str) -> str:
    """Encode one Provider identifier without allowing dot-segment traversal."""
    if provider_id in (".", ".."):
        raise ValueError("provider identifier must not be a dot path segment")
    try:
        return quote(provider_id, safe="", encoding="utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("provider identifier must be valid UTF-8") from error


def _json_string(provider_value: dict[str, JsonValue]) -> str:
    return json.dumps(provider_value, ensure_ascii=False, separators=(",", ":"))


def _render_card(intent: CardIntent, metadata: OpaqueMetadata) -> dict[str, JsonValue]:
    """Render caller metadata only inside Provider-native submit values."""
    elements: list[JsonValue] = [{"tag": "markdown", "content": intent.body}]
    if intent.facts:
        elements.append(
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {"tag": "lark_md", "content": f"**{fact_name}**\n{fact_value}"},
                    }
                    for fact_name, fact_value in intent.facts
                ],
            }
        )
    if intent.inputs:
        form_elements: list[JsonValue] = []
        for card_input in intent.inputs:
            if isinstance(card_input, CardTextInput):
                input_element: dict[str, JsonValue] = {
                    "tag": "input",
                    "name": card_input.input_id,
                    "label": {"tag": "plain_text", "content": card_input.label},
                    "required": True,
                }
                if card_input.placeholder is not None:
                    input_element["placeholder"] = {"tag": "plain_text", "content": card_input.placeholder}
                if card_input.default_value is not None:
                    input_element["default_value"] = card_input.default_value
                form_elements.append(input_element)
            elif isinstance(card_input, CardSingleSelectInput):
                select_element: dict[str, JsonValue] = {
                    "tag": "select_static",
                    "name": card_input.input_id,
                    "placeholder": {
                        "tag": "plain_text",
                        "content": card_input.label,
                    },
                    "required": True,
                    "options": [
                        {"text": {"tag": "plain_text", "content": option.label}, "value": option.value}
                        for option in card_input.options
                    ],
                }
                if card_input.default_value is not None:
                    select_element["initial_option"] = card_input.default_value
                form_elements.append(select_element)
        elements.append({"tag": "form", "name": "dify_hitl_form", "elements": form_elements})
    if intent.actions:
        action_elements: list[JsonValue] = []
        caller_metadata: dict[str, JsonValue] = {}
        for key, value in metadata.entries:
            caller_metadata[key] = value
        for action in intent.actions:
            if action.kind is CardActionKind.OPEN_URL:
                button: dict[str, JsonValue] = {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": action.label},
                    "type": "default",
                    "behaviors": [{"type": "open_url", "default_url": action.value}],
                }
            else:
                submit_value: dict[str, JsonValue] = {
                    "action_id": action.action_id,
                    "value": action.value,
                    "metadata": caller_metadata,
                }
                button = {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": action.label},
                    "type": "primary",
                    "behaviors": [{"type": "callback", "value": submit_value}],
                }
                if intent.inputs:
                    button["form_action_type"] = "submit"
                    button["name"] = action.action_id
            action_elements.append(button)
        if intent.inputs:
            form = elements[-1]
            if not isinstance(form, dict):
                raise TypeError("Feishu/Lark form payload was invalid")
            form_elements = form["elements"]
            if not isinstance(form_elements, list):
                raise TypeError("Feishu/Lark form elements were invalid")
            form_elements.extend(action_elements)
        else:
            elements.extend(action_elements)
    card: dict[str, JsonValue] = {
        "schema": "2.0",
        "config": {"update_multi": True},
        "body": {"direction": "vertical", "elements": elements},
    }
    if intent.title is not None:
        card["header"] = {"title": {"tag": "plain_text", "content": intent.title}}
    return card


class _FeishuLarkProviderClient:
    """Adapter-owned API roles over one SSRF-protected HTTP pool."""

    _config: FeishuLarkAdapterConfig
    _api_root: str
    _http_client: httpx.Client
    _tenant_token: _TenantToken | None

    def __init__(self, config: FeishuLarkAdapterConfig, http_client: httpx.Client) -> None:
        self._config = config
        self._api_root = _api_root(config.provider)
        self._http_client = http_client
        self._tenant_token = None

    def _get_tenant_token(self) -> _TenantToken | OperationFailure:
        now = time.monotonic()
        if self._tenant_token is not None and self._tenant_token.expires_at > now:
            return self._tenant_token
        try:
            response = self._http_client.post(
                f"{self._api_root}/auth/v3/tenant_access_token/internal",
                json={"app_id": self._config.app_id, "app_secret": self._config.app_secret},
            )
        except httpx.RequestError:
            return _failure(
                self._config.provider,
                OperationFailureCode.PROVIDER,
                "Feishu/Lark tenant token request failed",
            )
        if response.status_code == 429:
            return _failure(
                self._config.provider,
                OperationFailureCode.RATE_LIMITED,
                "Feishu/Lark rate limited the tenant token request",
            )
        if response.status_code >= 500:
            return _failure(
                self._config.provider,
                OperationFailureCode.PROVIDER,
                "Feishu/Lark tenant token service failed",
            )
        try:
            token_response = _TokenResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(
                self._config.provider,
                OperationFailureCode.PROVIDER,
                "Feishu/Lark tenant token response was invalid",
            )
        if token_response.code in _TOKEN_AUTHENTICATION_ERROR_CODES:
            return _failure(
                self._config.provider,
                OperationFailureCode.AUTHENTICATION,
                "Feishu/Lark rejected the bound app credentials",
            )
        if response.status_code >= 400 or token_response.code != 0:
            return _failure(
                self._config.provider,
                OperationFailureCode.PROVIDER,
                "Feishu/Lark tenant token request was rejected",
            )
        if (
            token_response.tenant_access_token is None
            or not token_response.tenant_access_token.strip()
            or token_response.expire is None
            or token_response.expire <= 0
        ):
            return _failure(
                self._config.provider,
                OperationFailureCode.PROVIDER,
                "Feishu/Lark tenant token response was incomplete",
            )
        self._tenant_token = _TenantToken(
            token_response.tenant_access_token,
            now + max(0, token_response.expire - _TOKEN_EXPIRY_SKEW_SECONDS),
        )
        return self._tenant_token

    @staticmethod
    def _authorization(token: _TenantToken) -> dict[str, str]:
        return {"authorization": f"Bearer {token.token}"}

    def test_credentials(self) -> CredentialTestResult:
        token = self._get_tenant_token()
        if isinstance(token, OperationFailure):
            return token
        tenant_key = self._read_tenant_key(token)
        if isinstance(tenant_key, OperationFailure):
            return tenant_key
        directory_scope = self._read_directory_scope(token)
        if isinstance(directory_scope, OperationFailure):
            return directory_scope
        return CredentialTestSuccess(
            provider=self._config.provider,
            provider_tenant_id=tenant_key,
            permissions=(
                PermissionFact(_TENANT_READ_PERMISSION, True),
                PermissionFact("contact.scope.read", True),
            ),
        )

    def _read_tenant_key(self, token: _TenantToken) -> str | OperationFailure:
        try:
            tenant_response = self._http_client.get(
                f"{self._api_root}/tenant/v2/tenant/query",
                headers=self._authorization(token),
            )
            tenant_result = _TenantResponse.model_validate_json(tenant_response.content)
        except httpx.RequestError:
            return _failure(
                self._config.provider,
                OperationFailureCode.TENANT_IDENTIFICATION,
                "Feishu/Lark tenant query failed",
            )
        except ValidationError:
            return _failure(
                self._config.provider,
                OperationFailureCode.TENANT_IDENTIFICATION,
                "Feishu/Lark tenant response was invalid",
            )
        if tenant_result.code in _TENANT_PERMISSION_ERROR_CODES:
            return _failure(
                self._config.provider,
                OperationFailureCode.MISSING_PERMISSION,
                f"Feishu/Lark app is missing required permission: {_TENANT_READ_PERMISSION}",
            )
        tenant_key = tenant_result.data.tenant.tenant_key if tenant_result.data and tenant_result.data.tenant else None
        if (
            tenant_response.status_code >= 400
            or tenant_result.code != 0
            or tenant_key is None
            or not tenant_key.strip()
        ):
            return _failure(
                self._config.provider,
                OperationFailureCode.TENANT_IDENTIFICATION,
                "Feishu/Lark could not identify the tenant",
            )
        return tenant_key

    def _read_directory_scope(self, token: _TenantToken) -> _DirectoryScope | OperationFailure:
        department_ids: list[str] = []
        user_ids: list[str] = []
        seen_department_ids: set[str] = set()
        seen_user_ids: set[str] = set()
        next_page_token: str | None = None
        while True:
            query = {
                "user_id_type": _OPEN_USER_ID_TYPE,
                "department_id_type": _OPEN_DEPARTMENT_ID_TYPE,
                "page_size": str(self._config.directory_page_size or _SCOPE_PAGE_SIZE),
            }
            if next_page_token is not None:
                query["page_token"] = next_page_token
            response = self._directory_get(
                f"{self._api_root}/contact/v3/scopes",
                query,
                token,
            )
            if isinstance(response, OperationFailure):
                return response
            try:
                page = _ScopeResponse.model_validate_json(response.content)
                if response.status_code >= 400 or page.code != 0 or page.data is None:
                    raise ValueError("scope page was rejected")
                for raw_department_id in page.data.department_ids:
                    department_id = raw_department_id.strip()
                    if not department_id:
                        raise ValueError("scope department id was blank")
                    if department_id not in seen_department_ids:
                        seen_department_ids.add(department_id)
                        department_ids.append(department_id)
                for raw_user_id in page.data.user_ids:
                    user_id = raw_user_id.strip()
                    if not user_id:
                        raise ValueError("scope user id was blank")
                    if user_id not in seen_user_ids:
                        seen_user_ids.add(user_id)
                        user_ids.append(user_id)
                next_page_token = _next_page_token(page.data.has_more, page.data.page_token)
            except (ValidationError, ValueError):
                return self._directory_failure("Feishu/Lark contact scope traversal was incomplete")
            if next_page_token is None:
                return _DirectoryScope(
                    department_ids=tuple(department_ids),
                    user_ids=tuple(user_ids),
                )

    def read_directory(self) -> DirectoryReadResult:
        token = self._get_tenant_token()
        if isinstance(token, OperationFailure):
            return token
        tenant_key = self._read_tenant_key(token)
        if isinstance(tenant_key, OperationFailure):
            return tenant_key
        directory_scope = self._read_directory_scope(token)
        if isinstance(directory_scope, OperationFailure):
            return directory_scope
        department_ids = self._read_department_ids(token, directory_scope.department_ids)
        if isinstance(department_ids, OperationFailure):
            return department_ids

        entries_by_open_id: dict[str, DirectoryEntry] = {}
        for user_id in directory_scope.user_ids:
            explicit_entry = self._read_user_profile(token, user_id)
            if isinstance(explicit_entry, OperationFailure):
                return explicit_entry
            entries_by_open_id[explicit_entry.provider_user_id] = explicit_entry
        for department_id in department_ids:
            department_entries = self._read_department_users(token, department_id)
            if isinstance(department_entries, OperationFailure):
                return department_entries
            for entry in department_entries:
                entries_by_open_id.setdefault(entry.provider_user_id, entry)
        return DirectorySnapshot(
            self._config.provider,
            tenant_key,
            tuple(entries_by_open_id.values()),
        )

    def _read_department_ids(
        self,
        token: _TenantToken,
        root_department_ids: tuple[str, ...],
    ) -> tuple[str, ...] | OperationFailure:
        department_ids: list[str] = []
        seen_department_ids: set[str] = set()
        for root_department_id in root_department_ids:
            if root_department_id not in seen_department_ids:
                seen_department_ids.add(root_department_id)
                department_ids.append(root_department_id)
            next_page_token: str | None = None
            while True:
                query = {
                    "user_id_type": _OPEN_USER_ID_TYPE,
                    "department_id_type": _OPEN_DEPARTMENT_ID_TYPE,
                    "fetch_child": "true",
                    "page_size": str(self._config.directory_page_size or _DIRECTORY_PAGE_SIZE),
                }
                if next_page_token is not None:
                    query["page_token"] = next_page_token
                response = self._directory_get(
                    f"{self._api_root}/contact/v3/departments/{_encode_path_segment(root_department_id)}/children",
                    query,
                    token,
                )
                if isinstance(response, OperationFailure):
                    return response
                try:
                    page = _DepartmentPageResponse.model_validate_json(response.content)
                    if response.status_code >= 400 or page.code != 0 or page.data is None:
                        raise ValueError("department page was rejected")
                    for department in page.data.items:
                        department_id = department.open_department_id.strip()
                        if not department_id:
                            raise ValueError("department id was blank")
                        if department_id not in seen_department_ids:
                            seen_department_ids.add(department_id)
                            department_ids.append(department_id)
                    next_page_token = _next_page_token(page.data.has_more, page.data.page_token)
                except (ValidationError, ValueError):
                    return self._directory_failure("Feishu/Lark department traversal was incomplete")
                if next_page_token is None:
                    break
        return tuple(department_ids)

    def _read_department_users(
        self,
        token: _TenantToken,
        department_id: str,
    ) -> tuple[DirectoryEntry, ...] | OperationFailure:
        entries: list[DirectoryEntry] = []
        next_page_token: str | None = None
        while True:
            query = {
                "user_id_type": _OPEN_USER_ID_TYPE,
                "department_id_type": _OPEN_DEPARTMENT_ID_TYPE,
                "department_id": department_id,
                "page_size": str(self._config.directory_page_size or _DIRECTORY_PAGE_SIZE),
            }
            if next_page_token is not None:
                query["page_token"] = next_page_token
            response = self._directory_get(
                f"{self._api_root}/contact/v3/users/find_by_department",
                query,
                token,
            )
            if isinstance(response, OperationFailure):
                return response
            try:
                page = _UserPageResponse.model_validate_json(response.content)
                if response.status_code >= 400 or page.code != 0 or page.data is None:
                    raise ValueError("user page was rejected")
                for user in page.data.items:
                    entry = _user_to_directory_entry(user, self._config.provider)
                    if isinstance(entry, OperationFailure):
                        return entry
                    entries.append(entry)
                next_page_token = _next_page_token(page.data.has_more, page.data.page_token)
            except (ValidationError, ValueError):
                return self._directory_failure("Feishu/Lark user traversal was incomplete")
            if next_page_token is None:
                return tuple(entries)

    def _read_user_profile(
        self,
        token: _TenantToken,
        user_id: str,
    ) -> DirectoryEntry | OperationFailure:
        response = self._directory_get(
            f"{self._api_root}/contact/v3/users/{_encode_path_segment(user_id)}",
            {"user_id_type": _OPEN_USER_ID_TYPE},
            token,
        )
        if isinstance(response, OperationFailure):
            return response
        try:
            profile = _UserResponse.model_validate_json(response.content)
            if response.status_code >= 400 or profile.code != 0 or profile.data is None:
                raise ValueError("user profile was rejected")
            return _user_to_directory_entry(profile.data.user, self._config.provider)
        except (ValidationError, ValueError):
            return self._directory_failure("Feishu/Lark explicit user traversal was incomplete")

    def _directory_get(
        self,
        url: str,
        query: dict[str, str],
        token: _TenantToken,
    ) -> httpx.Response | OperationFailure:
        rate_limit_retries = 0
        while True:
            try:
                response = self._http_client.get(url, params=query, headers=self._authorization(token))
            except httpx.RequestError:
                return self._directory_failure("Feishu/Lark directory request failed")
            if response.status_code != 429:
                try:
                    openapi_response = _OpenAPIResponse.model_validate_json(response.content)
                except ValidationError:
                    return response
                if openapi_response.code in _DIRECTORY_PERMISSION_ERROR_CODES:
                    return _failure(
                        self._config.provider,
                        OperationFailureCode.MISSING_PERMISSION,
                        "Feishu/Lark contact scope does not include the requested directory resource",
                    )
                return response
            try:
                retry_after = int(response.headers.get("retry-after", ""))
            except ValueError:
                retry_after = -1
            if retry_after < 0 or rate_limit_retries >= _MAX_DIRECTORY_RATE_LIMIT_RETRIES:
                return self._directory_failure("Feishu/Lark directory remained rate limited")
            rate_limit_retries += 1
            time.sleep(retry_after)

    def _directory_failure(self, message: str) -> OperationFailure:
        return _failure(self._config.provider, OperationFailureCode.DIRECTORY_INCOMPLETE, message)

    def test_destination(self, destination: FeishuUserDestination) -> DestinationTestResult:
        if destination.receive_id_type not in _SUPPORTED_RECEIVE_ID_TYPES:
            return _failure(
                self._config.provider,
                OperationFailureCode.INVALID_DESTINATION,
                "Feishu/Lark destination receive ID type is invalid",
            )
        token = self._get_tenant_token()
        if isinstance(token, OperationFailure):
            return token
        headers = self._authorization(token)
        try:
            destination_response: _OpenAPIResponse
            if destination.receive_id_type == "email":
                response = self._http_client.post(
                    f"{self._api_root}/contact/v3/users/batch_get_id",
                    params={"user_id_type": _OPEN_USER_ID_TYPE},
                    json={"emails": [destination.receive_id]},
                    headers=headers,
                )
                destination_response = _BatchGetUserIDResponse.model_validate_json(response.content)
            else:
                destination_id = _encode_path_segment(destination.receive_id)
                response = self._http_client.get(
                    f"{self._api_root}/contact/v3/users/{destination_id}",
                    params={"user_id_type": destination.receive_id_type},
                    headers=headers,
                )
                destination_response = _OpenAPIResponse.model_validate_json(response.content)
        except httpx.RequestError:
            return _failure(
                self._config.provider,
                OperationFailureCode.PROVIDER,
                "Feishu/Lark destination check request failed",
            )
        except (ValidationError, ValueError):
            return _failure(
                self._config.provider,
                OperationFailureCode.PROVIDER,
                "Feishu/Lark destination check response was invalid",
            )
        if response.status_code >= 400 or destination_response.code != 0:
            return _failure(
                self._config.provider,
                OperationFailureCode.DESTINATION_UNREACHABLE,
                "Feishu/Lark destination is not reachable by the bound app",
            )
        if isinstance(destination_response, _BatchGetUserIDResponse) and (
            destination_response.data is None
            or not any(user.user_id.strip() for user in destination_response.data.user_list)
        ):
            return _failure(
                self._config.provider,
                OperationFailureCode.DESTINATION_UNREACHABLE,
                "Feishu/Lark destination is not reachable by the bound app",
            )
        return None

    def send_text(self, destination: FeishuUserDestination, body: str) -> MessageResult[FeishuMessageReference]:
        return self._send_message(
            destination=destination,
            message_type="text",
            content={"text": body},
            expected_reference=None,
        )

    def assess_card(self, intent: CardIntent) -> CardAssessment:
        return CardAssessment(representable=True, reason=None)

    def send_card(
        self,
        destination: FeishuUserDestination,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[FeishuMessageReference]:
        return self._send_message(
            destination=destination,
            message_type="interactive",
            content=_render_card(intent, metadata),
            expected_reference=None,
        )

    def update_card(
        self,
        reference: FeishuMessageReference,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[FeishuMessageReference]:
        return self._send_message(
            destination=None,
            message_type=None,
            content=_render_card(intent, metadata),
            expected_reference=reference,
        )

    def _send_message(
        self,
        *,
        destination: FeishuUserDestination | None,
        message_type: str | None,
        content: dict[str, JsonValue],
        expected_reference: FeishuMessageReference | None,
    ) -> MessageResult[FeishuMessageReference]:
        if destination is not None and destination.receive_id_type not in _SUPPORTED_RECEIVE_ID_TYPES:
            return _failure(
                self._config.provider,
                OperationFailureCode.INVALID_DESTINATION,
                "Feishu/Lark destination receive ID type is invalid",
            )
        token = self._get_tenant_token()
        if isinstance(token, OperationFailure):
            return token
        try:
            if expected_reference is None:
                if destination is None or message_type is None:
                    raise RuntimeError("new Feishu/Lark message requires a destination and type")
                response = self._http_client.post(
                    f"{self._api_root}/im/v1/messages",
                    params={"receive_id_type": destination.receive_id_type},
                    json={
                        "receive_id": destination.receive_id,
                        "msg_type": message_type,
                        "content": _json_string(content),
                    },
                    headers=self._authorization(token),
                )
            else:
                message_id = _encode_path_segment(expected_reference.message_id)
                response = self._http_client.patch(
                    f"{self._api_root}/im/v1/messages/{message_id}",
                    json={"content": _json_string(content)},
                    headers=self._authorization(token),
                )
        except httpx.RequestError:
            return _failure(
                self._config.provider,
                OperationFailureCode.AMBIGUOUS,
                "Feishu/Lark message request failed with an ambiguous outcome",
            )
        except ValueError:
            return _failure(
                self._config.provider,
                OperationFailureCode.STALE_REFERENCE,
                "Feishu/Lark message reference was invalid",
            )
        if response.status_code == 429:
            return _failure(
                self._config.provider,
                OperationFailureCode.RATE_LIMITED,
                "Feishu/Lark rate limited the message request",
            )
        if expected_reference is not None and response.status_code == 404:
            return _failure(
                self._config.provider,
                OperationFailureCode.STALE_REFERENCE,
                "Feishu/Lark no longer accepts the exact message reference",
            )
        try:
            message_response = _MessageResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(
                self._config.provider,
                OperationFailureCode.AMBIGUOUS,
                "Feishu/Lark message response was invalid and the outcome is ambiguous",
            )
        if response.status_code >= 400 or message_response.code != 0:
            return _failure(
                self._config.provider,
                OperationFailureCode.PROVIDER,
                "Feishu/Lark rejected the message request",
            )
        reference = expected_reference
        if reference is None:
            response_message_id = message_response.data.message_id if message_response.data is not None else None
            if response_message_id is None or not response_message_id.strip():
                return _failure(
                    self._config.provider,
                    OperationFailureCode.AMBIGUOUS,
                    "Feishu/Lark accepted the request without an exact message reference",
                )
            reference = FeishuMessageReference(response_message_id)
        provider_request_id = response.headers.get("x-tt-logid") or response.headers.get("x-request-id")
        return MessageAccepted(reference, provider_request_id)

    def close(self) -> None:
        self._http_client.close()


class _FeishuLarkStreamSDKClient(Protocol):
    """Public lifecycle exposed by the controlled pinned WebSocket fork."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class _FeishuLarkStreamRetryRequestedError(Exception):
    """Signal the pinned SDK DATA handler to emit its 500 retry ACK."""


class _FeishuLarkStreamEventListener:
    """Validate one card-action delivery and invoke the common sink synchronously."""

    _config: FeishuLarkAdapterConfig
    _accept: Callable[[AuthenticatedIMEvent], EventAcceptance]

    def __init__(
        self,
        config: FeishuLarkAdapterConfig,
        accept: Callable[[AuthenticatedIMEvent], EventAcceptance],
    ) -> None:
        self._config = config
        self._accept = accept

    def __call__(self, sdk_event: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        serialized_event = JSON.marshal(sdk_event)
        if serialized_event is None:
            raise ValueError("Feishu/Lark STREAM event could not be serialized")
        provider_envelope = _StreamEventEnvelope.model_validate_json(serialized_event)
        if provider_envelope.header.token != self._config.verification_token:
            raise ValueError("Feishu/Lark STREAM verification token does not match")
        if provider_envelope.header.app_id != self._config.app_id:
            raise ValueError("Feishu/Lark STREAM application does not match")
        if provider_envelope.header.event_type != _CARD_ACTION_EVENT_TYPE:
            raise ValueError("Feishu/Lark STREAM event type is unsupported")

        provider_event_time = self._event_time(provider_envelope.header.create_time)
        authenticated_event = AuthenticatedIMEvent(
            provider=self._config.provider,
            provider_tenant_id=provider_envelope.header.tenant_key,
            provider_event_id=provider_envelope.header.event_id,
            provider_event_time=provider_event_time,
            received_at=datetime.now(UTC),
            provider_event_type=provider_envelope.header.event_type,
            provider_payload=ImmutableJSONObject(
                tuple((key, freeze_json_value(value)) for key, value in provider_envelope.event.items())
            ),
        )
        if self._accept(authenticated_event) is not EventAcceptance.ACCEPTED:
            raise _FeishuLarkStreamRetryRequestedError("Feishu/Lark STREAM sink requested retry")
        return P2CardActionTriggerResponse()

    @staticmethod
    def _event_time(create_time: str | None) -> datetime | None:
        if create_time is None:
            return None
        try:
            timestamp = int(create_time)
            if len(create_time) == _SECOND_TIMESTAMP_DIGITS:
                return datetime.fromtimestamp(timestamp, tz=UTC)
            if len(create_time) == _MILLISECOND_TIMESTAMP_DIGITS:
                return datetime.fromtimestamp(timestamp / 1_000, tz=UTC)
            if len(create_time) == _MICROSECOND_TIMESTAMP_DIGITS:
                return datetime.fromtimestamp(timestamp / 1_000_000, tz=UTC)
        except (OSError, OverflowError, ValueError) as error:
            raise ValueError("Feishu/Lark STREAM event time is invalid") from error
        raise ValueError("Feishu/Lark STREAM event time has an unsupported precision")


class _FeishuLarkStreamClientRole:
    """Root-owned lifecycle and callback/ACK role for long connections.

    ``_state_lock`` protects close/running state and the active client-loop
    pair. It is never held while awaiting the SDK. The synchronous listener
    deliberately raises for invalid or retryable deliveries because the pinned
    SDK DATA handler owns the corresponding 500 ACK on the callback stack. A
    client is released only after an awaited ``stop()`` succeeds and the owned
    run completes; failed or timed-out cleanup retains the exact client so a
    later adapter close can retry it. ``_initializing`` covers the build window
    before publication. Once published, the controlled client supports
    stop-before-start, while ``_run_complete`` still gates successful close.
    """

    _config: FeishuLarkAdapterConfig
    _state_lock: RLock
    _running: bool
    _initializing: bool
    _closed: bool
    _loop: asyncio.AbstractEventLoop | None
    _stream_client: _FeishuLarkStreamSDKClient | None
    _stream_client_stopped: bool
    _run_complete: Event

    def __init__(self, config: FeishuLarkAdapterConfig) -> None:
        self._config = config
        self._state_lock = RLock()
        self._running = False
        self._initializing = False
        self._closed = False
        self._loop = None
        self._stream_client = None
        self._stream_client_stopped = False
        self._run_complete = Event()
        self._run_complete.set()

    def run_stream(
        self,
        accept: Callable[[AuthenticatedIMEvent], EventAcceptance],
        stop: StopSignal,
    ) -> StreamRunResult:
        if stop.is_set():
            return None
        with self._state_lock:
            if self._closed:
                return OperationFailure(
                    self._config.provider,
                    OperationFailureCode.CLOSED,
                    "Feishu/Lark STREAM client is closed",
                )
            if self._running:
                return OperationFailure(
                    self._config.provider,
                    OperationFailureCode.PROVIDER,
                    "Feishu/Lark STREAM client is already running",
                )
            if self._stream_client is not None:
                return OperationFailure(
                    self._config.provider,
                    OperationFailureCode.PROVIDER,
                    "Feishu/Lark STREAM client cleanup is incomplete",
                )
            self._running = True
            self._initializing = True
            self._run_complete.clear()
        try:
            asyncio.run(self._run_stream(accept, stop))
        except Exception:
            logger.exception("Feishu/Lark long-connection client stopped unexpectedly")
            return OperationFailure(
                self._config.provider,
                OperationFailureCode.PROVIDER,
                "Feishu/Lark STREAM client failed",
            )
        finally:
            with self._state_lock:
                self._initializing = False
                self._loop = None
                self._running = False
                if self._stream_client_stopped:
                    self._stream_client = None
                    self._stream_client_stopped = False
                self._run_complete.set()
        return None

    async def _run_stream(
        self,
        accept: Callable[[AuthenticatedIMEvent], EventAcceptance],
        stop: StopSignal,
    ) -> None:
        event_listener = _FeishuLarkStreamEventListener(self._config, accept)
        stream_client = _build_feishu_lark_stream_sdk_client(self._config, event_listener)
        loop = asyncio.get_running_loop()
        with self._state_lock:
            self._loop = loop
            self._stream_client = stream_client
            self._stream_client_stopped = False
            close_requested = self._closed

        start_task: asyncio.Task[None] | None = None
        stop_requested = False
        try:
            if close_requested:
                return
            start_task = asyncio.create_task(stream_client.start())
            await asyncio.sleep(0)
            with self._state_lock:
                self._initializing = False
                close_requested = close_requested or self._closed
            while not start_task.done():
                with self._state_lock:
                    close_requested = close_requested or self._closed
                if (stop.is_set() or close_requested) and not stop_requested:
                    stop_requested = True
                    await self._stop_stream_client(stream_client)
                if not start_task.done():
                    await asyncio.sleep(_STREAM_STOP_POLL_SECONDS)
            await start_task
        finally:
            try:
                if not stop_requested:
                    await self._stop_stream_client(stream_client)
            finally:
                if start_task is not None:
                    await start_task

    async def _stop_stream_client(self, stream_client: _FeishuLarkStreamSDKClient) -> None:
        with self._state_lock:
            if self._stream_client is not stream_client or self._stream_client_stopped:
                return
        await stream_client.stop()
        with self._state_lock:
            if self._stream_client is stream_client:
                self._stream_client_stopped = True
                if not self._running:
                    self._stream_client = None
                    self._stream_client_stopped = False

    def close(self) -> None:
        """Permanently suppress runs and synchronously confirm client cleanup.

        The running loop cannot wait on itself. In that case the caller gets a
        safe cleanup failure while the run loop observes ``_closed`` and owns
        the awaited stop. External close also confirms that the owned start task
        exits; the adapter root retains this role and exact client on timeout.
        """
        with self._state_lock:
            self._closed = True
            initializing = self._initializing
            running = self._running
            loop = self._loop
            stream_client = self._stream_client
        if initializing and stream_client is None:
            raise RuntimeError("Feishu/Lark STREAM cleanup must be retried after initialization finishes")
        if stream_client is None:
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if loop is not None and loop.is_running():
            if running_loop is loop:
                raise RuntimeError("Feishu/Lark STREAM cleanup must be retried outside its running event loop")
            future = asyncio.run_coroutine_threadsafe(self._stop_stream_client(stream_client), loop)
            try:
                future.result(timeout=_STREAM_CLOSE_TIMEOUT_SECONDS)
            except FutureTimeoutError as error:
                future.cancel()
                raise RuntimeError("Feishu/Lark STREAM client did not stop before the close deadline") from error
        else:
            if running_loop is not None:
                raise RuntimeError("Feishu/Lark STREAM cleanup must be retried outside a running event loop")
            asyncio.run(self._stop_stream_client(stream_client))
        if running and not self._run_complete.wait(timeout=_STREAM_RUN_CLOSE_TIMEOUT_SECONDS):
            raise RuntimeError("Feishu/Lark STREAM run did not finish before the close deadline")


def _build_feishu_lark_stream_sdk_client(
    config: FeishuLarkAdapterConfig,
    callback: Callable[[P2CardActionTrigger], P2CardActionTriggerResponse],
) -> _FeishuLarkStreamSDKClient:
    from lark_oapi.core.const import FEISHU_DOMAIN, LARK_DOMAIN  # type: ignore[import-untyped]

    from .feishu_lark_stream import create_controlled_lark_websocket_client

    domain = FEISHU_DOMAIN if config.provider is IMProvider.FEISHU else LARK_DOMAIN
    return create_controlled_lark_websocket_client(
        app_id=config.app_id,
        app_secret=config.app_secret,
        callback=callback,
        domain=domain,
    )


def create_feishu_lark_client_context(
    config: FeishuLarkAdapterConfig,
) -> _ProviderClientContext[FeishuUserDestination, FeishuMessageReference]:
    from .feishu_lark_webhook import create_feishu_lark_webhook_client

    client = _FeishuLarkProviderClient(config, _build_http_client())
    stream = _FeishuLarkStreamClientRole(config)
    webhook_client = create_feishu_lark_webhook_client(config)
    return _ProviderClientContext(
        credentials=client,
        directory=client,
        messaging=client,
        card=client,
        webhook=webhook_client,
        stream=stream,
        owned_resources=(client, stream),
    )
