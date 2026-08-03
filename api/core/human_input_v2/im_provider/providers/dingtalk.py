"""DingTalk OpenAPI boundary owned by ``DingTalkAdapter``.

One adapter-owned HTTP client and tenant-scoped access-token cache are shared
across capabilities. API credentials are bound to the configured corporation
by the authoritative ``POST /v1.0/oauth2/{corpId}/token`` exchange. Its request
uses ``client_id``, ``client_secret`` and the ``client_credentials`` grant; its
success response uses ``access_token`` and ``expires_in``. Provider API traffic
always verifies TLS; the generic HTTP-node verification switch does not apply
to credentials. The official token contract is documented at
https://open.dingtalk.com/document/orgapp/api-gettoken.md and exposed by the
official OpenAPI SDK as
``oauth2_1_0.Client.get_token(corp_id, GetTokenRequest)``.

Directory calls use legacy endpoints whose rate limit may be either HTTP 429
or HTTP 200 with ``errcode=88``. Both forms receive the same bounded retry at
the current traversal node or page, with a 0.1-second fallback delay when the
Provider supplies no usable retry interval. A snapshot is published only after
the complete traversal succeeds, so exhausted retries never expose partial
Directory state.

The adapter intentionally exposes no DingTalk Webhook or STREAM capability.
Its typed configuration therefore contains only API credentials and the
optional Directory pagination seam.
"""

from __future__ import annotations

import json
import logging
import math
import time
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.helper.ssrf_proxy import create_ssrf_protected_client
from core.human_input_v2.entities import IMProvider

from ..client_roles import _ProviderClientContext
from ..contracts import (
    CredentialTestResult,
    CredentialTestSuccess,
    DestinationTestResult,
    DirectoryEntry,
    DirectoryReadResult,
    DirectorySnapshot,
    MessageAccepted,
    MessageResult,
    OperationFailure,
    OperationFailureCode,
    PermissionFact,
)
from ..provider_types import DingTalkAdapterConfig, DingTalkMessageReference, DingTalkUserDestination

_DINGTALK_API_ROOT = "https://api.dingtalk.com"
_DINGTALK_LEGACY_API_ROOT = "https://oapi.dingtalk.com"
_ROOT_DEPARTMENT_ID = 1
_TOKEN_EXPIRY_SKEW_SECONDS = 60
_HTTP_TIMEOUT_SECONDS = 10.0
_DIRECTORY_PAGE_SIZE = 100
_MAX_DIRECTORY_RATE_LIMIT_RETRIES = 3
_DEFAULT_DIRECTORY_RETRY_AFTER_SECONDS = 0.1
_MAX_DIRECTORY_RETRY_AFTER_SECONDS = 60.0
_TOKEN_AUTHENTICATION_ERROR_CODES = frozenset(
    {"InvalidAuthentication", "invalid.client", "unauthorized.client", "unsupported.grant.type"}
)
_MISSING_PERMISSION_ERROR_CODES = frozenset({60011})
_LEGACY_RATE_LIMIT_ERROR_CODES = frozenset({88})
_MARKDOWN_TITLE_LIMIT = 64

logger = logging.getLogger(__name__)


class _TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    access_token: str
    expires_in: int


class _TokenErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: str


class _LegacyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    errcode: int
    errmsg: str


class _Department(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    dept_id: int


class _DepartmentListResponse(_LegacyResponse):
    result: tuple[_Department, ...] | None = None


class _User(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    user_id: str = Field(alias="userid")
    name: str
    email: str | None = None
    organization_email: str | None = Field(default=None, alias="org_email")
    active: bool | None = None


class _UserPage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    users: tuple[_User, ...] = Field(default=(), alias="list")
    has_more: bool
    next_cursor: int | None = None


class _UserListResponse(_LegacyResponse):
    result: _UserPage | None = None


class _UserGetResponse(_LegacyResponse):
    result: _User | None = None


class _MessageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    process_query_key: str = Field(alias="processQueryKey")


class _AccessToken:
    token: str
    expires_at: float

    def __init__(self, token: str, expires_at: float) -> None:
        self.token = token
        self.expires_at = expires_at


def _failure(code: OperationFailureCode, message: str) -> OperationFailure:
    return OperationFailure(IMProvider.DING_TALK, code, message)


def _encode_path_segment(provider_id: str) -> str:
    if provider_id in (".", ".."):
        raise ValueError("provider identifier must not be a dot path segment")
    try:
        return quote(provider_id, safe="", encoding="utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("provider identifier must be valid UTF-8") from error


def _build_http_client() -> httpx.Client:
    return create_ssrf_protected_client(verify=True, timeout=_HTTP_TIMEOUT_SECONDS)


class _DingTalkProviderClient:
    """Adapter-owned DingTalk API roles over one verified HTTP pool.

    Credential and Messaging operations are never replayed. Directory reads
    retry only HTTP 429 responses at the current node or page, then publish a
    snapshot only after the complete traversal succeeds.
    """

    _config: DingTalkAdapterConfig
    _http_client: httpx.Client
    _access_token: _AccessToken | None

    def __init__(self, config: DingTalkAdapterConfig, http_client: httpx.Client) -> None:
        self._config = config
        self._http_client = http_client
        self._access_token = None

    def _get_access_token(self) -> _AccessToken | OperationFailure:
        now = time.monotonic()
        if self._access_token is not None and self._access_token.expires_at > now:
            return self._access_token
        try:
            corporation_id = _encode_path_segment(self._config.corp_id)
            response = self._http_client.post(
                f"{_DINGTALK_API_ROOT}/v1.0/oauth2/{corporation_id}/token",
                json={
                    "client_id": self._config.client_id,
                    "client_secret": self._config.client_secret,
                    "grant_type": "client_credentials",
                },
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk access token request failed")
        except ValueError:
            return _failure(OperationFailureCode.AUTHENTICATION, "DingTalk corporation identifier was invalid")
        if response.status_code == 429:
            return _failure(OperationFailureCode.RATE_LIMITED, "DingTalk rate limited the access token request")
        if response.status_code >= 500:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk access token request was rejected")
        if response.status_code >= 400:
            try:
                token_error = _TokenErrorResponse.model_validate_json(response.content)
            except ValidationError:
                return _failure(OperationFailureCode.PROVIDER, "DingTalk access token request was rejected")
            if token_error.code in _TOKEN_AUTHENTICATION_ERROR_CODES:
                return _failure(OperationFailureCode.AUTHENTICATION, "DingTalk rejected the bound app credentials")
            return _failure(OperationFailureCode.PROVIDER, "DingTalk access token request was rejected")
        try:
            token_response = _TokenResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk access token response was invalid")
        if not token_response.access_token.strip() or token_response.expires_in <= 0:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk access token response was incomplete")
        self._access_token = _AccessToken(
            token_response.access_token,
            now + max(0, token_response.expires_in - _TOKEN_EXPIRY_SKEW_SECONDS),
        )
        return self._access_token

    def _confirm_legacy_permission(
        self,
        token: _AccessToken,
        path: str,
        request_body: dict[str, int],
    ) -> OperationFailure | None:
        try:
            response = self._http_client.post(
                f"{_DINGTALK_LEGACY_API_ROOT}{path}",
                params={"access_token": token.token},
                json=request_body,
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk permission probe request failed")
        if response.status_code == 401:
            return _failure(OperationFailureCode.AUTHENTICATION, "DingTalk rejected the access token")
        if response.status_code == 429:
            return _failure(OperationFailureCode.RATE_LIMITED, "DingTalk rate limited the permission probe")
        if response.status_code == 403:
            return _failure(
                OperationFailureCode.MISSING_PERMISSION, "DingTalk baseline directory permission is missing"
            )
        try:
            provider_response = _LegacyResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk permission probe response was invalid")
        if provider_response.errcode in _MISSING_PERMISSION_ERROR_CODES:
            return _failure(
                OperationFailureCode.MISSING_PERMISSION, "DingTalk baseline directory permission is missing"
            )
        if response.status_code >= 400 or provider_response.errcode != 0:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk permission probe was rejected")
        return None

    def test_credentials(self) -> CredentialTestResult:
        token = self._get_access_token()
        if isinstance(token, OperationFailure):
            return token
        permission_failure = self._confirm_legacy_permission(
            token,
            "/topapi/v2/department/listsub",
            {"dept_id": _ROOT_DEPARTMENT_ID},
        )
        if permission_failure is not None:
            return permission_failure
        permission_failure = self._confirm_legacy_permission(
            token,
            "/topapi/v2/user/list",
            {"dept_id": _ROOT_DEPARTMENT_ID, "cursor": 0, "size": 1},
        )
        if permission_failure is not None:
            return permission_failure
        return CredentialTestSuccess(
            provider=IMProvider.DING_TALK,
            provider_tenant_id=self._config.corp_id,
            permissions=(
                PermissionFact("contact.department.read", True),
                PermissionFact("contact.user.read", True),
            ),
        )

    def read_directory(self) -> DirectoryReadResult:
        credential_result = self.test_credentials()
        if isinstance(credential_result, OperationFailure):
            return credential_result
        token = self._get_access_token()
        if isinstance(token, OperationFailure):
            return token
        department_ids = self._read_department_ids(token)
        if isinstance(department_ids, OperationFailure):
            return department_ids

        entries_by_user_id: dict[str, DirectoryEntry] = {}
        for department_id in department_ids:
            department_entries = self._read_department_users(token, department_id)
            if isinstance(department_entries, OperationFailure):
                return department_entries
            for entry in department_entries:
                entries_by_user_id.setdefault(entry.provider_user_id, entry)
        return DirectorySnapshot(
            provider=IMProvider.DING_TALK,
            provider_tenant_id=credential_result.provider_tenant_id,
            entries=tuple(entries_by_user_id.values()),
        )

    def _read_department_ids(self, token: _AccessToken) -> tuple[int, ...] | OperationFailure:
        ordered_department_ids: list[int] = []
        pending_department_ids = [_ROOT_DEPARTMENT_ID]
        seen_department_ids: set[int] = set()
        while pending_department_ids:
            department_id = pending_department_ids.pop(0)
            if department_id in seen_department_ids:
                continue
            seen_department_ids.add(department_id)
            ordered_department_ids.append(department_id)
            response = self._directory_post(
                token,
                "/topapi/v2/department/listsub",
                {"dept_id": department_id},
            )
            if isinstance(response, OperationFailure):
                return response
            try:
                department_response = _DepartmentListResponse.model_validate_json(response.content)
            except ValidationError:
                return self._directory_failure("DingTalk department traversal was incomplete")
            if response.status_code >= 400 or department_response.errcode != 0 or department_response.result is None:
                return self._directory_failure("DingTalk department traversal was incomplete")
            pending_department_ids.extend(department.dept_id for department in department_response.result)
        return tuple(ordered_department_ids)

    def _read_department_users(
        self,
        token: _AccessToken,
        department_id: int,
    ) -> tuple[DirectoryEntry, ...] | OperationFailure:
        entries: list[DirectoryEntry] = []
        cursor = 0
        while True:
            response = self._directory_post(
                token,
                "/topapi/v2/user/list",
                {
                    "dept_id": department_id,
                    "cursor": cursor,
                    "size": self._config.directory_page_size or _DIRECTORY_PAGE_SIZE,
                },
            )
            if isinstance(response, OperationFailure):
                return response
            try:
                user_response = _UserListResponse.model_validate_json(response.content)
            except ValidationError:
                return self._directory_failure("DingTalk user traversal was incomplete")
            if response.status_code >= 400 or user_response.errcode != 0 or user_response.result is None:
                return self._directory_failure("DingTalk user traversal was incomplete")
            try:
                for user in user_response.result.users:
                    email = (user.email or "").strip() or (user.organization_email or "").strip() or None
                    entries.append(
                        DirectoryEntry(
                            provider_user_id=user.user_id,
                            display_name=user.name,
                            email=email,
                            available=user.active,
                        )
                    )
                if not user_response.result.has_more:
                    return tuple(entries)
                next_cursor = user_response.result.next_cursor
                if next_cursor is None or next_cursor <= cursor:
                    raise ValueError("provider pagination omitted a forward cursor")
                cursor = next_cursor
            except ValueError:
                return self._directory_failure("DingTalk user traversal was incomplete")

    def _directory_post(
        self,
        token: _AccessToken,
        path: str,
        request_body: dict[str, int],
    ) -> httpx.Response | OperationFailure:
        rate_limit_retries = 0
        while True:
            try:
                response = self._http_client.post(
                    f"{_DINGTALK_LEGACY_API_ROOT}{path}",
                    params={"access_token": token.token},
                    json=request_body,
                )
            except httpx.RequestError:
                return self._directory_failure("DingTalk directory request failed")
            provider_error_code: int | None = None
            if response.status_code != 429:
                try:
                    provider_error_code = _LegacyResponse.model_validate_json(response.content).errcode
                except ValidationError:
                    return response
            if response.status_code != 429 and provider_error_code not in _LEGACY_RATE_LIMIT_ERROR_CODES:
                return response
            if rate_limit_retries >= _MAX_DIRECTORY_RATE_LIMIT_RETRIES:
                return self._directory_failure("DingTalk directory remained rate limited")

            retry_after_seconds = self._directory_retry_after_seconds(response)
            rate_limit_retries += 1
            logger.warning(
                "DingTalk directory request was rate limited",
                extra={
                    "provider_tenant_id": self._config.corp_id,
                    "provider_path": path,
                    "provider_error_code": provider_error_code,
                    "retry_attempt": rate_limit_retries,
                    "retry_after_seconds": retry_after_seconds,
                },
            )
            time.sleep(retry_after_seconds)

    @staticmethod
    def _directory_retry_after_seconds(response: httpx.Response) -> float:
        try:
            retry_after_seconds = float(response.headers.get("retry-after", ""))
        except ValueError:
            return _DEFAULT_DIRECTORY_RETRY_AFTER_SECONDS
        if not math.isfinite(retry_after_seconds) or retry_after_seconds < 0:
            return _DEFAULT_DIRECTORY_RETRY_AFTER_SECONDS
        return min(retry_after_seconds, _MAX_DIRECTORY_RETRY_AFTER_SECONDS)

    @staticmethod
    def _directory_failure(message: str) -> OperationFailure:
        return _failure(OperationFailureCode.DIRECTORY_INCOMPLETE, message)

    @staticmethod
    def _authorization(token: _AccessToken) -> dict[str, str]:
        return {"x-acs-dingtalk-access-token": token.token}

    def test_destination(self, destination: DingTalkUserDestination) -> DestinationTestResult:
        token = self._get_access_token()
        if isinstance(token, OperationFailure):
            return token
        try:
            response = self._http_client.post(
                f"{_DINGTALK_LEGACY_API_ROOT}/topapi/v2/user/get",
                params={"access_token": token.token},
                json={"userid": destination.user_id},
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk destination check request failed")

        if response.status_code == 429:
            return _failure(OperationFailureCode.RATE_LIMITED, "DingTalk rate limited the destination check")
        if response.status_code >= 500:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk destination check failed upstream")
        if response.status_code == 401:
            return _failure(OperationFailureCode.AUTHENTICATION, "DingTalk rejected the access token")
        if response.status_code == 403:
            return _failure(OperationFailureCode.MISSING_PERMISSION, "DingTalk cannot read the destination user")
        try:
            user_response = _UserGetResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk destination response was invalid")
        if (
            response.status_code >= 400
            or user_response.errcode != 0
            or user_response.result is None
            or user_response.result.user_id != destination.user_id
        ):
            return _failure(
                OperationFailureCode.DESTINATION_UNREACHABLE,
                "DingTalk user is not reachable by the bound app",
            )
        return None

    def send_text(
        self,
        destination: DingTalkUserDestination,
        body: str,
    ) -> MessageResult[DingTalkMessageReference]:
        token = self._get_access_token()
        if isinstance(token, OperationFailure):
            return token
        title = self._markdown_title(body)
        message_parameters = json.dumps(
            {"title": title, "text": body},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            response = self._http_client.post(
                f"{_DINGTALK_API_ROOT}/v1.0/robot/oToMessages/batchSend",
                headers=self._authorization(token),
                json={
                    "robotCode": self._config.client_id,
                    "userIds": [destination.user_id],
                    "msgKey": "sampleMarkdown",
                    "msgParam": message_parameters,
                },
            )
        except httpx.RequestError:
            return _failure(
                OperationFailureCode.AMBIGUOUS,
                "DingTalk message request failed with an ambiguous outcome",
            )
        if response.status_code == 429:
            return _failure(OperationFailureCode.RATE_LIMITED, "DingTalk rate limited the message request")
        try:
            message_response = _MessageResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(
                OperationFailureCode.AMBIGUOUS,
                "DingTalk message response was invalid and the outcome is ambiguous",
            )
        if response.status_code >= 400:
            return _failure(OperationFailureCode.PROVIDER, "DingTalk rejected the message request")
        if not message_response.process_query_key.strip():
            return _failure(
                OperationFailureCode.AMBIGUOUS,
                "DingTalk accepted the request without an exact message reference",
            )
        return MessageAccepted(
            reference=DingTalkMessageReference(
                user_id=destination.user_id,
                message_id=message_response.process_query_key,
            ),
            provider_request_id=response.headers.get("x-acs-request-id"),
        )

    @staticmethod
    def _markdown_title(body: str) -> str:
        first_line = next((line.strip() for line in body.splitlines() if line.strip()), body.strip())
        plain_title = first_line.strip("#*_` ")
        return (plain_title or first_line)[:_MARKDOWN_TITLE_LIMIT]

    def close(self) -> None:
        self._http_client.close()


def create_dingtalk_client_context(
    config: DingTalkAdapterConfig,
) -> _ProviderClientContext[DingTalkUserDestination, DingTalkMessageReference]:
    client = _DingTalkProviderClient(config, _build_http_client())
    return _ProviderClientContext(
        credentials=client,
        directory=client,
        messaging=client,
        card=None,
        webhook=None,
        stream=None,
        owned_resources=(client,),
    )
