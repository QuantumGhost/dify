"""WeCom API boundary owned by ``WeComAdapter``.

One adapter-owned TLS-verified HTTP pool and corporation-token cache are shared
across credential, Directory, and Messaging roles. The official
``gettoken`` exchange binds the configured corporation and application secret;
``agent/get`` then confirms the bound agent and its user, department, and tag
visibility. Capability access itself performs no external I/O.
Token checks distinguish throttling and upstream failures from confirmed
corporation credential rejection.

Directory and Messaging use the same private API client. Each Directory call
resolves current agent visibility into a fresh complete snapshot; Messaging
checks exactly one remote user and never invokes Directory during send.
The adapter intentionally exposes no WeCom Webhook or STREAM capability, so
callback authentication and encryption material are outside its configuration.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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
from ..provider_types import WeComAdapterConfig, WeComMessageReference, WeComUserDestination

_WECOM_API_ROOT = "https://qyapi.weixin.qq.com/cgi-bin"
_HTTP_TIMEOUT_SECONDS = 10.0
_TOKEN_EXPIRY_SKEW_SECONDS = 60
_MAX_DIRECTORY_RATE_LIMIT_RETRIES = 3
_DEFAULT_DIRECTORY_RETRY_AFTER_SECONDS = 0.1
_MAX_DIRECTORY_RETRY_AFTER_SECONDS = 60.0
_AUTHENTICATION_ERROR_CODES = frozenset({40001, 40013, 40014, 42001})
_MISSING_PERMISSION_ERROR_CODES = frozenset({60011})

logger = logging.getLogger(__name__)


class _TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    errcode: int
    errmsg: str
    access_token: str | None = None
    expires_in: int | None = None


class _AgentUser(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    user_id: str = Field(alias="userid")

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("WeCom agent-visible user id must not be blank")
        return value


class _AgentUsers(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    users: tuple[_AgentUser, ...] = Field(default=(), alias="user")


class _AgentDepartments(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    department_ids: tuple[int, ...] = Field(default=(), alias="partyid")


class _AgentTags(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    tag_ids: tuple[int, ...] = Field(default=(), alias="tagid")


class _AgentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    errcode: int
    errmsg: str
    agent_id: int | None = Field(default=None, alias="agentid")
    visible_users: _AgentUsers = Field(default_factory=_AgentUsers, alias="allow_userinfos")
    visible_departments: _AgentDepartments = Field(default_factory=_AgentDepartments, alias="allow_partys")
    visible_tags: _AgentTags = Field(default_factory=_AgentTags, alias="allow_tags")
    closed: int | None = Field(default=None, alias="close")


class _Department(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    department_id: int = Field(alias="id")


class _DepartmentListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    errcode: int
    errmsg: str
    departments: tuple[_Department, ...] = Field(default=(), alias="department")


class _User(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    user_id: str = Field(alias="userid")
    name: str
    email: str | None = None
    business_email: str | None = Field(default=None, alias="biz_mail")
    status: int


class _UserListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    errcode: int
    errmsg: str
    users: tuple[_User, ...] = Field(default=(), alias="userlist")


class _WeComResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    errcode: int
    errmsg: str


class _UserResponse(_WeComResponse):
    user_id: str = Field(alias="userid")
    name: str
    email: str | None = None
    business_email: str | None = Field(default=None, alias="biz_mail")
    status: int


class _TagUser(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    user_id: str = Field(alias="userid")
    name: str


class _TagResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    errcode: int
    errmsg: str
    users: tuple[_TagUser, ...] = Field(default=(), alias="userlist")
    department_ids: tuple[int, ...] = Field(default=(), alias="partylist")


class _MessageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    errcode: int
    errmsg: str
    invalid_users: str = Field(default="", alias="invaliduser")
    message_id: str | None = Field(default=None, alias="msgid")


@dataclass(frozen=True, slots=True)
class _AccessToken:
    token: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class _AgentVisibility:
    user_ids: frozenset[str]
    department_ids: frozenset[str]
    tag_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class _ResolvedVisibility:
    entries: tuple[DirectoryEntry, ...]
    user_ids: frozenset[str]
    department_ids: frozenset[str]
    tag_ids: frozenset[str]


def _failure(code: OperationFailureCode, message: str) -> OperationFailure:
    return OperationFailure(IMProvider.WE_COM, code, message)


def _build_http_client(*, verify: bool, timeout: float) -> httpx.Client:
    return create_ssrf_protected_client(verify=verify, timeout=timeout)


class _WeComProviderClient:
    """Adapter-owned WeCom roles over one verified HTTP pool."""

    _config: WeComAdapterConfig
    _http_client: httpx.Client
    _access_token: _AccessToken | None

    def __init__(self, config: WeComAdapterConfig, http_client: httpx.Client) -> None:
        self._config = config
        self._http_client = http_client
        self._access_token = None

    def _get_access_token(self) -> _AccessToken | OperationFailure:
        now = time.monotonic()
        if self._access_token is not None and self._access_token.expires_at > now:
            return self._access_token
        try:
            response = self._http_client.get(
                f"{_WECOM_API_ROOT}/gettoken",
                params={"corpid": self._config.corp_id, "corpsecret": self._config.corp_secret},
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.PROVIDER, "WeCom access token request failed")
        if response.status_code == 429:
            return _failure(OperationFailureCode.RATE_LIMITED, "WeCom rate limited the access token request")
        if response.status_code >= 500:
            return _failure(OperationFailureCode.PROVIDER, "WeCom access token service failed")
        try:
            token_response = _TokenResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.PROVIDER, "WeCom access token response was invalid")
        if token_response.errcode in _AUTHENTICATION_ERROR_CODES:
            return _failure(OperationFailureCode.AUTHENTICATION, "WeCom rejected the bound corporation credentials")
        if response.status_code >= 400 or token_response.errcode != 0:
            return _failure(OperationFailureCode.PROVIDER, "WeCom access token request was rejected")
        if (
            token_response.access_token is None
            or not token_response.access_token.strip()
            or token_response.expires_in is None
            or token_response.expires_in <= 0
        ):
            return _failure(OperationFailureCode.PROVIDER, "WeCom access token response was incomplete")
        self._access_token = _AccessToken(
            token_response.access_token,
            now + max(0, token_response.expires_in - _TOKEN_EXPIRY_SKEW_SECONDS),
        )
        return self._access_token

    def _read_agent_visibility(self, token: _AccessToken) -> _AgentVisibility | OperationFailure:
        try:
            response = self._http_client.get(
                f"{_WECOM_API_ROOT}/agent/get",
                params={"access_token": token.token, "agentid": self._config.agent_id},
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.PROVIDER, "WeCom agent visibility request failed")
        if response.status_code == 429:
            return _failure(OperationFailureCode.RATE_LIMITED, "WeCom rate limited the agent visibility request")
        try:
            agent_response = _AgentResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.PROVIDER, "WeCom agent visibility response was invalid")
        if agent_response.errcode in _AUTHENTICATION_ERROR_CODES:
            return _failure(OperationFailureCode.AUTHENTICATION, "WeCom rejected the access token")
        if agent_response.errcode in _MISSING_PERMISSION_ERROR_CODES:
            return _failure(OperationFailureCode.MISSING_PERMISSION, "WeCom agent visibility permission is missing")
        if response.status_code >= 400 or agent_response.errcode != 0:
            return _failure(OperationFailureCode.PROVIDER, "WeCom agent visibility request was rejected")
        if agent_response.agent_id is None or str(agent_response.agent_id) != self._config.agent_id:
            return _failure(OperationFailureCode.AUTHENTICATION, "WeCom agent identity did not match")
        if agent_response.closed != 0:
            return _failure(OperationFailureCode.MISSING_PERMISSION, "WeCom application is disabled")
        return _AgentVisibility(
            user_ids=frozenset(user.user_id for user in agent_response.visible_users.users),
            department_ids=frozenset(
                str(department_id) for department_id in agent_response.visible_departments.department_ids
            ),
            tag_ids=frozenset(str(tag_id) for tag_id in agent_response.visible_tags.tag_ids),
        )

    def test_credentials(self) -> CredentialTestResult:
        token = self._get_access_token()
        if isinstance(token, OperationFailure):
            return token
        visibility = self._read_agent_visibility(token)
        if isinstance(visibility, OperationFailure):
            return visibility
        return CredentialTestSuccess(
            provider=IMProvider.WE_COM,
            provider_tenant_id=self._config.corp_id,
            permissions=(PermissionFact("agent.visibility.read", True),),
        )

    def read_directory(self) -> DirectoryReadResult:
        token = self._get_access_token()
        if isinstance(token, OperationFailure):
            return token
        visibility = self._read_agent_visibility(token)
        if isinstance(visibility, OperationFailure):
            return visibility
        resolved_visibility = self._resolve_visibility(token, visibility)
        if isinstance(resolved_visibility, OperationFailure):
            return resolved_visibility
        return DirectorySnapshot(
            provider=IMProvider.WE_COM,
            provider_tenant_id=self._config.corp_id,
            entries=resolved_visibility.entries,
        )

    def _resolve_visibility(
        self,
        token: _AccessToken,
        visibility: _AgentVisibility,
    ) -> _ResolvedVisibility | OperationFailure:
        entries_by_user_id: dict[str, DirectoryEntry] = {}
        for user_id in sorted(visibility.user_ids, key=self._provider_id_sort_key):
            explicit_user = self._read_explicit_user(token, user_id)
            if isinstance(explicit_user, OperationFailure):
                return explicit_user
            self._merge_directory_entry(entries_by_user_id, explicit_user)

        department_ids = self._read_visible_department_ids(token, visibility.department_ids)
        if isinstance(department_ids, OperationFailure):
            return department_ids
        department_failure = self._read_departments_into_entries(token, department_ids, entries_by_user_id)
        if department_failure is not None:
            return department_failure

        tag_department_ids: set[str] = set()
        for tag_id in sorted(visibility.tag_ids, key=self._provider_id_sort_key):
            tag_scope = self._read_tag_scope(token, tag_id)
            if isinstance(tag_scope, OperationFailure):
                return tag_scope
            tag_entries, tag_parties = tag_scope
            for entry in tag_entries:
                self._merge_directory_entry(entries_by_user_id, entry)
            tag_department_ids.update(tag_parties)

        unvisited_tag_departments = tag_department_ids.difference(department_ids)
        tag_scoped_department_ids = self._read_visible_department_ids(token, frozenset(unvisited_tag_departments))
        if isinstance(tag_scoped_department_ids, OperationFailure):
            return tag_scoped_department_ids
        department_failure = self._read_departments_into_entries(
            token,
            tag_scoped_department_ids,
            entries_by_user_id,
        )
        if department_failure is not None:
            return department_failure

        return _ResolvedVisibility(
            entries=tuple(entries_by_user_id.values()),
            user_ids=frozenset(entries_by_user_id),
            department_ids=frozenset((*department_ids, *tag_scoped_department_ids)),
            tag_ids=visibility.tag_ids,
        )

    def _read_explicit_user(self, token: _AccessToken, user_id: str) -> DirectoryEntry | OperationFailure:
        response = self._directory_get(
            "/user/get",
            {"access_token": token.token, "userid": user_id},
        )
        if isinstance(response, OperationFailure):
            return response
        try:
            user_response = _UserResponse.model_validate_json(response.content)
            if response.status_code >= 400 or user_response.errcode != 0 or user_response.user_id != user_id:
                raise ValueError("explicit user read was rejected")
            return DirectoryEntry(
                provider_user_id=user_response.user_id,
                display_name=user_response.name,
                email=(user_response.email or "").strip() or (user_response.business_email or "").strip() or None,
                available=user_response.status == 1,
            )
        except (ValidationError, ValueError):
            return self._directory_failure("WeCom explicit user traversal was incomplete")

    def _read_tag_scope(
        self,
        token: _AccessToken,
        tag_id: str,
    ) -> tuple[tuple[DirectoryEntry, ...], tuple[str, ...]] | OperationFailure:
        response = self._directory_get(
            "/tag/get",
            {"access_token": token.token, "tagid": tag_id},
        )
        if isinstance(response, OperationFailure):
            return response
        try:
            tag_response = _TagResponse.model_validate_json(response.content)
            if response.status_code >= 400 or tag_response.errcode != 0:
                raise ValueError("tag read was rejected")
            entries = tuple(
                DirectoryEntry(
                    provider_user_id=user.user_id,
                    display_name=user.name,
                    email=None,
                    available=None,
                )
                for user in tag_response.users
            )
            return entries, tuple(map(str, tag_response.department_ids))
        except (ValidationError, ValueError):
            return self._directory_failure("WeCom tag traversal was incomplete")

    def _read_departments_into_entries(
        self,
        token: _AccessToken,
        department_ids: tuple[str, ...],
        entries_by_user_id: dict[str, DirectoryEntry],
    ) -> OperationFailure | None:
        for department_id in department_ids:
            department_entries = self._read_department_users(token, department_id)
            if isinstance(department_entries, OperationFailure):
                return department_entries
            for entry in department_entries:
                self._merge_directory_entry(entries_by_user_id, entry)
        return None

    @staticmethod
    def _merge_directory_entry(
        entries_by_user_id: dict[str, DirectoryEntry],
        entry: DirectoryEntry,
    ) -> None:
        existing_entry = entries_by_user_id.get(entry.provider_user_id)
        if existing_entry is None:
            entries_by_user_id[entry.provider_user_id] = entry
            return
        email = existing_entry.email or entry.email
        available = existing_entry.available if existing_entry.available is not None else entry.available
        entries_by_user_id[entry.provider_user_id] = DirectoryEntry(
            provider_user_id=existing_entry.provider_user_id,
            display_name=existing_entry.display_name,
            email=email,
            available=available,
        )

    def _read_visible_department_ids(
        self,
        token: _AccessToken,
        visible_department_ids: frozenset[str],
    ) -> tuple[str, ...] | OperationFailure:
        ordered_department_ids: list[str] = []
        for visible_department_id in sorted(visible_department_ids, key=self._provider_id_sort_key):
            response = self._directory_get(
                "/department/list",
                {"access_token": token.token, "id": visible_department_id},
            )
            if isinstance(response, OperationFailure):
                return response
            try:
                department_response = _DepartmentListResponse.model_validate_json(response.content)
                if response.status_code >= 400 or department_response.errcode != 0:
                    raise ValueError("department list was rejected")
                department_ids = (
                    visible_department_id,
                    *map(str, (item.department_id for item in department_response.departments)),
                )
                for department_id in department_ids:
                    if department_id not in ordered_department_ids:
                        ordered_department_ids.append(department_id)
            except (ValidationError, ValueError):
                return self._directory_failure("WeCom department traversal was incomplete")
        return tuple(ordered_department_ids)

    def _read_department_users(
        self,
        token: _AccessToken,
        department_id: str,
    ) -> tuple[DirectoryEntry, ...] | OperationFailure:
        response = self._directory_get(
            "/user/list",
            {"access_token": token.token, "department_id": department_id},
        )
        if isinstance(response, OperationFailure):
            return response
        try:
            users_response = _UserListResponse.model_validate_json(response.content)
            if response.status_code >= 400 or users_response.errcode != 0:
                raise ValueError("user list was rejected")
            return tuple(
                DirectoryEntry(
                    provider_user_id=user.user_id,
                    display_name=user.name,
                    email=(user.email or "").strip() or (user.business_email or "").strip() or None,
                    available=user.status == 1,
                )
                for user in users_response.users
            )
        except (ValidationError, ValueError):
            return self._directory_failure("WeCom user traversal was incomplete")

    def _directory_get(
        self,
        path: str,
        query: dict[str, str],
    ) -> httpx.Response | OperationFailure:
        rate_limit_retries = 0
        while True:
            try:
                response = self._http_client.get(f"{_WECOM_API_ROOT}{path}", params=query)
            except httpx.RequestError:
                return self._directory_failure("WeCom directory request failed")
            if response.status_code != 429:
                return response
            if rate_limit_retries >= _MAX_DIRECTORY_RATE_LIMIT_RETRIES:
                return self._directory_failure("WeCom directory remained rate limited")

            retry_after_seconds = self._directory_retry_after_seconds(response)
            rate_limit_retries += 1
            logger.warning(
                "WeCom directory request was rate limited",
                extra={
                    "provider_tenant_id": self._config.corp_id,
                    "provider_path": path,
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
    def _provider_id_sort_key(provider_id: str) -> tuple[int, int | str]:
        try:
            return (0, int(provider_id))
        except ValueError:
            return (1, provider_id)

    @staticmethod
    def _directory_failure(message: str) -> OperationFailure:
        return _failure(OperationFailureCode.DIRECTORY_INCOMPLETE, message)

    def test_destination(self, destination: WeComUserDestination) -> DestinationTestResult:
        token = self._get_access_token()
        if isinstance(token, OperationFailure):
            return token
        try:
            response = self._http_client.get(
                f"{_WECOM_API_ROOT}/user/get",
                params={"access_token": token.token, "userid": destination.user_id},
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.PROVIDER, "WeCom destination check request failed")
        if response.status_code == 429:
            return _failure(OperationFailureCode.RATE_LIMITED, "WeCom rate limited the destination check")
        try:
            provider_response = _WeComResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.PROVIDER, "WeCom destination check response was invalid")
        if provider_response.errcode in _AUTHENTICATION_ERROR_CODES:
            return _failure(OperationFailureCode.AUTHENTICATION, "WeCom rejected the access token")
        if provider_response.errcode in _MISSING_PERMISSION_ERROR_CODES:
            return _failure(OperationFailureCode.MISSING_PERMISSION, "WeCom cannot read the destination user")
        if response.status_code >= 400 or provider_response.errcode != 0:
            return _failure(
                OperationFailureCode.DESTINATION_UNREACHABLE,
                "WeCom user is not reachable by the bound agent",
            )
        try:
            user_response = _UserResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(OperationFailureCode.PROVIDER, "WeCom destination check response was invalid")
        if user_response.user_id != destination.user_id:
            return _failure(
                OperationFailureCode.DESTINATION_UNREACHABLE,
                "WeCom user is not reachable by the bound agent",
            )
        return None

    def send_text(
        self,
        destination: WeComUserDestination,
        body: str,
    ) -> MessageResult[WeComMessageReference]:
        token = self._get_access_token()
        if isinstance(token, OperationFailure):
            return token
        try:
            agent_id = int(self._config.agent_id)
        except ValueError:
            return _failure(OperationFailureCode.AUTHENTICATION, "WeCom agent identifier was invalid")
        request_body: dict[str, object] = {
            "msgtype": "text",
            "agentid": agent_id,
            "text": {"content": body},
        }
        request_body["touser"] = destination.user_id
        try:
            response = self._http_client.post(
                f"{_WECOM_API_ROOT}/message/send",
                params={"access_token": token.token},
                json=request_body,
            )
        except httpx.RequestError:
            return _failure(OperationFailureCode.AMBIGUOUS, "WeCom message request failed with an ambiguous outcome")
        if response.status_code == 429:
            return _failure(OperationFailureCode.RATE_LIMITED, "WeCom rate limited the message request")
        try:
            message_response = _MessageResponse.model_validate_json(response.content)
        except ValidationError:
            return _failure(
                OperationFailureCode.AMBIGUOUS,
                "WeCom message response was invalid and the outcome is ambiguous",
            )
        if response.status_code >= 400 or message_response.errcode != 0:
            return _failure(OperationFailureCode.PROVIDER, "WeCom rejected the message request")
        if message_response.invalid_users.strip():
            return _failure(
                OperationFailureCode.AMBIGUOUS,
                "WeCom did not accept the exact destination user",
            )
        if message_response.message_id is None or not message_response.message_id.strip():
            return _failure(
                OperationFailureCode.AMBIGUOUS,
                "WeCom accepted the request without an exact message reference",
            )
        return MessageAccepted(reference=WeComMessageReference(message_response.message_id), provider_request_id=None)

    def close(self) -> None:
        self._http_client.close()


def create_wecom_client_context(
    config: WeComAdapterConfig,
) -> _ProviderClientContext[WeComUserDestination, WeComMessageReference]:
    client = _WeComProviderClient(
        config,
        _build_http_client(verify=True, timeout=_HTTP_TIMEOUT_SECONDS),
    )
    return _ProviderClientContext(
        credentials=client,
        directory=client,
        messaging=client,
        card=None,
        webhook=None,
        stream=None,
        owned_resources=(client,),
    )
