"""Provider adapters for Human Input IM directory synchronization.

Only this module imports provider SDK models. Application services consume
``ProviderDirectoryEntry`` values and safe diagnostics, so SDK payloads,
exceptions, and credentials cannot leak into controller responses.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import lark_oapi as lark
from lark_oapi.api.contact.v3 import ListDepartmentRequest, ListUserRequest
from lark_oapi.api.tenant.v2 import QueryTenantRequest
from lark_oapi.core.exception import (
    AccessDeniedException,
    AccessTokenException,
    InvalidArgsException,
    NoAuthorizationException,
    ObtainAccessTokenException,
    UnmarshalException,
)
from requests.exceptions import RequestException

from core.human_input_v2.entities import IMIntegrationStatus, IMProvider
from core.human_input_v2.im_integration import (
    EncryptedCredentials,
    ProviderDirectoryEntry,
    ProviderTenantIdentity,
)

_SDK_EXCEPTIONS = (
    AccessDeniedException,
    AccessTokenException,
    InvalidArgsException,
    NoAuthorizationException,
    ObtainAccessTokenException,
    UnmarshalException,
)
_CONNECTION_TEST_EXCEPTIONS = (*_SDK_EXCEPTIONS, RequestException)
_DIRECTORY_READ_EXCEPTIONS = (*_SDK_EXCEPTIONS, RequestException)
_DIRECTORY_PAGE_SIZE = 50
_ROOT_DEPARTMENT_ID = "0"


class ProviderAdapterError(Exception):
    """Safe provider failure whose message is suitable for operators."""


class UnsupportedProviderError(ProviderAdapterError):
    """Directory synchronization is not registered for this provider."""


class InvalidProviderCredentialsError(ProviderAdapterError):
    """The provider credential value is incomplete or malformed."""


@dataclass(frozen=True, slots=True)
class ProviderCredentials:
    """Immutable provider-neutral credential value."""

    provider: IMProvider
    _values: tuple[tuple[str, str | None], ...]

    def to_mapping(self) -> dict[str, str | None]:
        return dict(self._values)


@dataclass(frozen=True, slots=True)
class _CredentialField:
    name: str
    stored_name: str
    required: bool
    strip: bool = False


@dataclass(frozen=True, slots=True)
class _ProviderRegistration:
    credential_fields: tuple[_CredentialField, ...]
    client_factory: Callable[[ProviderCredentials], ProviderDirectoryClient]


@dataclass(frozen=True, slots=True)
class ProviderConnectionDiagnostic:
    """Credential-free connection test result."""

    status: IMIntegrationStatus
    message: str
    provider_tenant: ProviderTenantIdentity | None

    @property
    def connected(self) -> bool:
        return self.status is IMIntegrationStatus.CONNECTED


class ProviderDirectoryClient(Protocol):
    """Provider-neutral directory capability used by sync orchestration."""

    provider: IMProvider

    def test_connection(self) -> ProviderConnectionDiagnostic:
        """Validate credentials and resolve the provider tenant identity."""
        ...

    def list_directory_entries(self) -> tuple[ProviderDirectoryEntry, ...]:
        """Return all visible users as normalized provider-neutral entries."""
        ...


class FeishuLarkDirectoryAdapter:
    """Official ``lark-oapi`` adapter shared by Feishu and Lark."""

    provider: IMProvider
    _client: object

    def __init__(self, *, provider: IMProvider, app_id: str, app_secret: str) -> None:
        if provider not in (IMProvider.FEISHU, IMProvider.LARK):
            raise ValueError("FeishuLarkDirectoryAdapter only supports Feishu and Lark")
        domain = lark.FEISHU_DOMAIN if provider is IMProvider.FEISHU else lark.LARK_DOMAIN
        self.provider = provider
        self._client = (
            lark.Client.builder()
            .app_id(app_id.strip())
            .app_secret(app_secret)
            .domain(domain)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

    def test_connection(self) -> ProviderConnectionDiagnostic:
        """Query tenant metadata and collapse SDK and transport failures into safe diagnostics."""

        try:
            response = self._client.tenant.v2.tenant.query(QueryTenantRequest.builder().build())  # type: ignore[attr-defined]
        except _CONNECTION_TEST_EXCEPTIONS:
            return ProviderConnectionDiagnostic(
                status=IMIntegrationStatus.CONNECTION_ERROR,
                message="Unable to connect to the IM provider with the supplied credentials.",
                provider_tenant=None,
            )
        if not response.success():
            return ProviderConnectionDiagnostic(
                status=_status_for_provider_code(response.code),
                message=_safe_provider_message(response.code),
                provider_tenant=None,
            )
        tenant = response.data.tenant if response.data is not None else None
        tenant_key = tenant.tenant_key.strip() if tenant is not None and tenant.tenant_key else ""
        if not tenant_key:
            return ProviderConnectionDiagnostic(
                status=IMIntegrationStatus.CONNECTION_ERROR,
                message="The IM provider did not return a tenant identity.",
                provider_tenant=None,
            )
        return ProviderConnectionDiagnostic(
            status=IMIntegrationStatus.CONNECTED,
            message="Connection successful.",
            provider_tenant=ProviderTenantIdentity(self.provider, tenant_key),
        )

    def list_directory_entries(self) -> tuple[ProviderDirectoryEntry, ...]:
        """Read root and descendant departments, normalizing each visible user."""

        entries_by_provider_user_id: dict[str, ProviderDirectoryEntry] = {}
        for department_id in self._list_department_ids():
            for entry in self._list_department_entries(department_id):
                entries_by_provider_user_id[entry.provider_user_id] = entry
        return tuple(entries_by_provider_user_id.values())

    def _list_department_ids(self) -> tuple[str, ...]:
        """Return the root plus every descendant department visible to the app."""

        department_ids = [_ROOT_DEPARTMENT_ID]
        page_token: str | None = None
        while True:
            builder = (
                ListDepartmentRequest.builder()
                .department_id_type("open_department_id")
                .parent_department_id(_ROOT_DEPARTMENT_ID)
                .fetch_child(True)
                .page_size(_DIRECTORY_PAGE_SIZE)
            )
            if page_token:
                builder.page_token(page_token)
            try:
                response = self._client.contact.v3.department.list(builder.build())  # type: ignore[attr-defined]
            except _DIRECTORY_READ_EXCEPTIONS as error:
                raise ProviderAdapterError("Unable to read the IM provider directory.") from error
            if not response.success():
                raise ProviderAdapterError(_safe_provider_message(response.code))
            data = response.data
            if data is None:
                break
            for department in data.items or ():
                department_id = _first_non_blank(getattr(department, "open_department_id", None))
                if department_id is not None and department_id not in department_ids:
                    department_ids.append(department_id)
            if data.has_more is not True:
                break
            page_token = data.page_token
            if not isinstance(page_token, str) or not page_token:
                raise ProviderAdapterError("The IM provider returned an invalid directory page.")
        return tuple(department_ids)

    def _list_department_entries(self, department_id: str) -> tuple[ProviderDirectoryEntry, ...]:
        """Page direct members of one department."""

        entries: list[ProviderDirectoryEntry] = []
        page_token: str | None = None
        while True:
            builder = (
                ListUserRequest.builder()
                .department_id_type("open_department_id")
                .department_id(department_id)
                .user_id_type("open_id")
                .page_size(_DIRECTORY_PAGE_SIZE)
            )
            if page_token:
                builder.page_token(page_token)
            try:
                response = self._client.contact.v3.user.list(builder.build())  # type: ignore[attr-defined]
            except _DIRECTORY_READ_EXCEPTIONS as error:
                raise ProviderAdapterError("Unable to read the IM provider directory.") from error
            if not response.success():
                raise ProviderAdapterError(_safe_provider_message(response.code))
            data = response.data
            if data is None:
                break
            for user in data.items or ():
                entries.append(_normalize_user(user))
            if data.has_more is not True:
                break
            page_token = data.page_token
            if not isinstance(page_token, str) or not page_token:
                raise ProviderAdapterError("The IM provider returned an invalid directory page.")
        return tuple(entries)


def _normalize_user(user: object) -> ProviderDirectoryEntry:
    """Convert one SDK user model without retaining the raw SDK payload."""

    provider_user_id = _first_non_blank(
        getattr(user, "open_id", None),
        getattr(user, "user_id", None),
        getattr(user, "union_id", None),
    )
    if provider_user_id is None:
        raise ProviderAdapterError("The IM provider returned a user without a stable identifier.")
    display_name = _first_non_blank(
        getattr(user, "name", None),
        getattr(user, "en_name", None),
        getattr(user, "nickname", None),
    )
    email = _first_non_blank(
        getattr(user, "enterprise_email", None),
        getattr(user, "email", None),
    )
    return ProviderDirectoryEntry.create(
        provider_user_id=provider_user_id,
        display_name=display_name,
        email=email,
        raw_payload={
            "provider_user_id": provider_user_id,
            "display_name": display_name,
            "email": email,
        },
    )


def _first_non_blank(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _status_for_provider_code(code: int) -> IMIntegrationStatus:
    if code in {99991663, 99991668, 99991672, 99991679}:
        return IMIntegrationStatus.PERMISSION_ISSUE
    return IMIntegrationStatus.CONNECTION_ERROR


def _safe_provider_message(code: int) -> str:
    status = _status_for_provider_code(code)
    if status is IMIntegrationStatus.PERMISSION_ISSUE:
        return "The IM application does not have permission to read the tenant directory."
    return "The IM provider rejected the request."


_FEISHU_LARK_CREDENTIAL_FIELDS = (
    _CredentialField("app_id", "app_id", required=True, strip=True),
    _CredentialField("app_secret", "encrypted_app_secret", required=True),
    _CredentialField("verification_token", "encrypted_verification_token", required=False),
    _CredentialField("encrypt_key", "encrypted_encrypt_key", required=False),
)


def _create_feishu_lark_client(credentials: ProviderCredentials) -> ProviderDirectoryClient:
    values = credentials.to_mapping()
    app_id = values["app_id"]
    app_secret = values["app_secret"]
    if app_id is None or app_secret is None:
        raise InvalidProviderCredentialsError("The IM integration credentials are invalid.")
    return FeishuLarkDirectoryAdapter(
        provider=credentials.provider,
        app_id=app_id,
        app_secret=app_secret,
    )


_PROVIDER_REGISTRY = {
    IMProvider.FEISHU: _ProviderRegistration(
        credential_fields=_FEISHU_LARK_CREDENTIAL_FIELDS,
        client_factory=_create_feishu_lark_client,
    ),
    IMProvider.LARK: _ProviderRegistration(
        credential_fields=_FEISHU_LARK_CREDENTIAL_FIELDS,
        client_factory=_create_feishu_lark_client,
    ),
}


def create_provider_credentials(
    provider: IMProvider,
    values: Mapping[str, object],
) -> ProviderCredentials:
    """Validate one registry-defined plaintext credential value."""

    fields = _credential_fields(provider)
    known_names = {field.name for field in fields}
    if set(values) - known_names:
        raise InvalidProviderCredentialsError("The IM integration credentials are invalid.")
    normalized: list[tuple[str, str | None]] = []
    for field in fields:
        value = values.get(field.name)
        if value is None and not field.required:
            normalized.append((field.name, None))
            continue
        if not isinstance(value, str):
            raise InvalidProviderCredentialsError("The IM integration credentials are invalid.")
        if field.strip:
            value = value.strip()
        if not value:
            if field.required:
                raise InvalidProviderCredentialsError("The IM integration credentials are invalid.")
            value = None
        normalized.append((field.name, value))
    return ProviderCredentials(provider, tuple(normalized))


def encrypt_provider_credentials(
    credentials: ProviderCredentials,
    encrypt: Callable[[str], str],
) -> EncryptedCredentials:
    """Serialize plaintext credentials using registry-defined storage keys."""

    values = credentials.to_mapping()
    encrypted: dict[str, str | None] = {}
    for field in _credential_fields(credentials.provider):
        value = values[field.name]
        encrypted[field.stored_name] = value if field.stored_name == field.name or value is None else encrypt(value)
    return EncryptedCredentials.from_mapping(encrypted)


def decrypt_provider_credentials(
    provider: IMProvider,
    values: Mapping[str, object],
    decrypt: Callable[[str], str],
) -> ProviderCredentials:
    """Deserialize credentials using registry-defined storage keys."""

    plaintext: dict[str, str | None] = {}
    for field in _credential_fields(provider):
        value = values.get(field.stored_name)
        if value is None and not field.required:
            plaintext[field.name] = None
            continue
        if not isinstance(value, str) or not value:
            raise InvalidProviderCredentialsError("The stored IM integration credentials are invalid.")
        plaintext[field.name] = value if field.stored_name == field.name else decrypt(value)
    return create_provider_credentials(provider, plaintext)


def create_provider_client(credentials: ProviderCredentials) -> ProviderDirectoryClient:
    """Build the registered provider adapter without exposing credential fields."""

    return _provider_registration(credentials.provider).client_factory(credentials)


def _credential_fields(provider: IMProvider) -> tuple[_CredentialField, ...]:
    return _provider_registration(provider).credential_fields


def _provider_registration(provider: IMProvider) -> _ProviderRegistration:
    registration = _PROVIDER_REGISTRY.get(provider)
    if registration is None:
        raise UnsupportedProviderError("Directory synchronization is not supported.")
    return registration


__all__ = [
    "FeishuLarkDirectoryAdapter",
    "InvalidProviderCredentialsError",
    "ProviderAdapterError",
    "ProviderConnectionDiagnostic",
    "ProviderCredentials",
    "ProviderDirectoryClient",
    "UnsupportedProviderError",
    "create_provider_client",
    "create_provider_credentials",
    "decrypt_provider_credentials",
    "encrypt_provider_credentials",
]
