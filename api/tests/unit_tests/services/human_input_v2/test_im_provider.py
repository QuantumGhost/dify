"""Unit tests for the provider-neutral Feishu and Lark directory adapter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import lark_oapi as lark
import pytest
from lark_oapi.core.exception import InvalidArgsException
from requests.exceptions import RequestException

from core.human_input_v2.entities import IMIntegrationStatus, IMProvider
from core.human_input_v2.im_integration import ProviderTenantIdentity
from services.human_input_v2.im_provider import (
    _PROVIDER_REGISTRY,
    FeishuLarkDirectoryAdapter,
    InvalidProviderCredentialsError,
    ProviderAdapterError,
    ProviderConnectionDiagnostic,
    UnsupportedProviderError,
    _CredentialField,
    _normalize_user,
    _ProviderRegistration,
    create_provider_client,
    create_provider_credentials,
    decrypt_provider_credentials,
    encrypt_provider_credentials,
)


def _adapter(provider: IMProvider = IMProvider.FEISHU) -> FeishuLarkDirectoryAdapter:
    adapter = object.__new__(FeishuLarkDirectoryAdapter)
    adapter.provider = provider
    adapter._client = MagicMock()
    return adapter


@pytest.mark.parametrize(
    ("provider", "domain"),
    [
        (IMProvider.FEISHU, lark.FEISHU_DOMAIN),
        (IMProvider.LARK, lark.LARK_DOMAIN),
    ],
)
def test_adapter_builds_official_sdk_client_for_each_supported_domain(
    provider: IMProvider,
    domain: str,
) -> None:
    builder = MagicMock()
    builder.app_id.return_value = builder
    builder.app_secret.return_value = builder
    builder.domain.return_value = builder
    builder.log_level.return_value = builder

    with patch("services.human_input_v2.im_provider.lark.Client.builder", return_value=builder):
        adapter = FeishuLarkDirectoryAdapter(provider=provider, app_id=" app-id ", app_secret="secret")

    assert adapter.provider is provider
    builder.app_id.assert_called_once_with("app-id")
    builder.domain.assert_called_once_with(domain)
    builder.build.assert_called_once_with()


def test_adapter_rejects_unsupported_provider() -> None:
    with pytest.raises(ValueError, match="only supports"):
        FeishuLarkDirectoryAdapter(provider=IMProvider.SLACK, app_id="app-id", app_secret="secret")


def test_connection_returns_confirmed_provider_tenant() -> None:
    adapter = _adapter(IMProvider.LARK)
    adapter._client.tenant.v2.tenant.query.return_value = SimpleNamespace(
        success=lambda: True,
        data=SimpleNamespace(tenant=SimpleNamespace(tenant_key=" tenant-key ")),
    )

    diagnostic = adapter.test_connection()

    assert diagnostic == ProviderConnectionDiagnostic(
        status=IMIntegrationStatus.CONNECTED,
        message="Connection successful.",
        provider_tenant=ProviderTenantIdentity(IMProvider.LARK, "tenant-key"),
    )
    assert diagnostic.connected is True


@pytest.mark.parametrize(
    ("response", "expected_status", "expected_message"),
    [
        (
            SimpleNamespace(success=lambda: False, code=99991663),
            IMIntegrationStatus.PERMISSION_ISSUE,
            "does not have permission",
        ),
        (
            SimpleNamespace(success=lambda: False, code=123),
            IMIntegrationStatus.CONNECTION_ERROR,
            "rejected the request",
        ),
        (
            SimpleNamespace(success=lambda: True, data=None),
            IMIntegrationStatus.CONNECTION_ERROR,
            "did not return a tenant identity",
        ),
    ],
)
def test_connection_maps_provider_failures_to_safe_diagnostics(
    response: object,
    expected_status: IMIntegrationStatus,
    expected_message: str,
) -> None:
    adapter = _adapter()
    adapter._client.tenant.v2.tenant.query.return_value = response

    diagnostic = adapter.test_connection()

    assert diagnostic.status is expected_status
    assert expected_message in diagnostic.message
    assert diagnostic.provider_tenant is None
    assert diagnostic.connected is False


def test_connection_sanitizes_sdk_exception_details() -> None:
    adapter = _adapter()
    adapter._client.tenant.v2.tenant.query.side_effect = InvalidArgsException("secret=credential")

    diagnostic = adapter.test_connection()

    assert diagnostic.status is IMIntegrationStatus.CONNECTION_ERROR
    assert "secret=credential" not in diagnostic.message


def test_connection_sanitizes_network_exception_details() -> None:
    adapter = _adapter()
    adapter._client.tenant.v2.tenant.query.side_effect = RequestException("dns secret=credential")

    diagnostic = adapter.test_connection()

    assert diagnostic.status is IMIntegrationStatus.CONNECTION_ERROR
    assert diagnostic.message == "Unable to connect to the IM provider with the supplied credentials."
    assert "secret=credential" not in diagnostic.message
    assert diagnostic.provider_tenant is None


def test_directory_read_pages_and_normalizes_provider_records() -> None:
    adapter = _adapter()
    first = SimpleNamespace(
        success=lambda: True,
        data=SimpleNamespace(
            items=[
                SimpleNamespace(
                    open_id=" open-1 ",
                    user_id="ignored",
                    union_id="ignored",
                    name=" Reviewer ",
                    en_name=None,
                    nickname=None,
                    enterprise_email=" REVIEWER@EXAMPLE.COM ",
                    email="ignored@example.com",
                )
            ],
            has_more=True,
            page_token="next-page",
        ),
    )
    second = SimpleNamespace(
        success=lambda: True,
        data=SimpleNamespace(
            items=[SimpleNamespace(open_id=None, user_id="user-2", union_id=None, name=None, en_name="Second")],
            has_more=False,
            page_token=None,
        ),
    )
    adapter._client.contact.v3.user.list.side_effect = [first, second]

    entries = adapter.list_directory_entries()

    assert [entry.provider_user_id for entry in entries] == ["open-1", "user-2"]
    assert entries[0].display_name == "Reviewer"
    assert entries[0].email == "REVIEWER@EXAMPLE.COM"
    assert str(entries[0].normalized_email) == "reviewer@example.com"
    assert entries[0].raw_payload.to_mapping() == {
        "display_name": "Reviewer",
        "email": "REVIEWER@EXAMPLE.COM",
        "provider_user_id": "open-1",
    }
    assert adapter._client.contact.v3.user.list.call_count == 2


def test_directory_read_accepts_empty_response_data() -> None:
    adapter = _adapter()
    adapter._client.contact.v3.user.list.return_value = SimpleNamespace(success=lambda: True, data=None)

    assert adapter.list_directory_entries() == ()


def test_department_read_pages_and_deduplicates_descendants() -> None:
    adapter = _adapter()
    adapter._client.contact.v3.department.list.side_effect = [
        SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(
                items=[
                    SimpleNamespace(open_department_id="department-1"),
                    SimpleNamespace(open_department_id="0"),
                    SimpleNamespace(open_department_id=" "),
                ],
                has_more=True,
                page_token="next-page",
            ),
        ),
        SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(
                items=[SimpleNamespace(open_department_id="department-2")],
                has_more=False,
                page_token=None,
            ),
        ),
    ]

    assert adapter._list_department_ids() == ("0", "department-1", "department-2")
    assert adapter._client.contact.v3.department.list.call_count == 2


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (SimpleNamespace(success=lambda: False, code=99991668), "does not have permission"),
        (SimpleNamespace(success=lambda: True, data=None), None),
        (
            SimpleNamespace(
                success=lambda: True,
                data=SimpleNamespace(items=[], has_more=True, page_token=None),
            ),
            "invalid directory page",
        ),
    ],
)
def test_department_read_handles_safe_terminal_responses(response: object, message: str | None) -> None:
    adapter = _adapter()
    adapter._client.contact.v3.department.list.return_value = response

    if message is None:
        assert adapter._list_department_ids() == ("0",)
    else:
        with pytest.raises(ProviderAdapterError, match=message):
            adapter._list_department_ids()


def test_department_read_sanitizes_sdk_exception_details() -> None:
    adapter = _adapter()
    adapter._client.contact.v3.department.list.side_effect = InvalidArgsException("secret=credential")

    with pytest.raises(ProviderAdapterError, match="Unable to read") as error:
        adapter._list_department_ids()

    assert "credential" not in str(error.value)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (SimpleNamespace(success=lambda: False, code=99991668), "does not have permission"),
        (
            SimpleNamespace(
                success=lambda: True,
                data=SimpleNamespace(items=[], has_more=True, page_token=None),
            ),
            "invalid directory page",
        ),
    ],
)
def test_directory_read_rejects_safe_provider_failures(response: object, message: str) -> None:
    adapter = _adapter()
    adapter._client.contact.v3.user.list.return_value = response

    with pytest.raises(ProviderAdapterError, match=message):
        adapter.list_directory_entries()


def test_directory_read_sanitizes_sdk_exception_details() -> None:
    adapter = _adapter()
    adapter._client.contact.v3.user.list.side_effect = InvalidArgsException("secret=credential")

    with pytest.raises(ProviderAdapterError, match="Unable to read") as error:
        adapter.list_directory_entries()

    assert "credential" not in str(error.value)


def test_normalization_uses_fallback_fields_and_requires_stable_identifier() -> None:
    entry = _normalize_user(
        SimpleNamespace(
            open_id=" ",
            user_id=None,
            union_id="union-1",
            name=" ",
            en_name=None,
            nickname="Nickname",
            enterprise_email=" ",
            email="user@example.com",
        )
    )

    assert entry.provider_user_id == "union-1"
    assert entry.display_name == "Nickname"
    assert entry.email == "user@example.com"
    with pytest.raises(ProviderAdapterError, match="stable identifier"):
        _normalize_user(SimpleNamespace())


def test_factory_returns_shared_adapter_and_rejects_unsupported_provider() -> None:
    credentials = create_provider_credentials(
        IMProvider.FEISHU,
        {"app_id": "app-id", "app_secret": "secret"},
    )
    with patch("services.human_input_v2.im_provider.FeishuLarkDirectoryAdapter") as adapter_type:
        client = create_provider_client(credentials)

    assert client is adapter_type.return_value
    with pytest.raises(UnsupportedProviderError, match="not supported"):
        create_provider_credentials(IMProvider.SLACK, {"bot_token": "secret"})


def test_credential_registry_normalizes_and_rejects_malformed_values() -> None:
    credentials = create_provider_credentials(
        IMProvider.LARK,
        {
            "app_id": " app-id ",
            "app_secret": "secret",
            "verification_token": "",
        },
    )

    assert credentials.to_mapping() == {
        "app_id": "app-id",
        "app_secret": "secret",
        "verification_token": None,
        "encrypt_key": None,
    }
    with pytest.raises(InvalidProviderCredentialsError):
        create_provider_credentials(
            IMProvider.LARK,
            {"app_id": "app-id", "app_secret": "secret", "unknown": "value"},
        )
    with pytest.raises(InvalidProviderCredentialsError):
        create_provider_credentials(IMProvider.LARK, {"app_id": "app-id"})
    with pytest.raises(InvalidProviderCredentialsError):
        create_provider_credentials(IMProvider.LARK, {"app_id": "app-id", "app_secret": 7})


def test_credential_registry_encrypts_and_decrypts_provider_fields() -> None:
    credentials = create_provider_credentials(
        IMProvider.FEISHU,
        {
            "app_id": "app-id",
            "app_secret": "secret",
            "verification_token": "verification",
            "encrypt_key": None,
        },
    )

    encrypted = encrypt_provider_credentials(credentials, lambda value: f"encrypted:{value}")
    decrypted = decrypt_provider_credentials(
        IMProvider.FEISHU,
        encrypted.to_mapping(),
        lambda value: value.removeprefix("encrypted:"),
    )

    assert encrypted.to_mapping() == {
        "app_id": "app-id",
        "encrypted_app_secret": "encrypted:secret",
        "encrypted_verification_token": "encrypted:verification",
        "encrypted_encrypt_key": None,
    }
    assert decrypted == credentials


def test_registry_addition_requires_no_provider_specific_factory_api(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client_factory = MagicMock(return_value=client)
    monkeypatch.setitem(
        _PROVIDER_REGISTRY,
        IMProvider.SLACK,
        _ProviderRegistration(
            credential_fields=(
                _CredentialField("workspace", "workspace", required=True, strip=True),
                _CredentialField("token", "encrypted_token", required=True),
            ),
            client_factory=client_factory,
        ),
    )

    credentials = create_provider_credentials(
        IMProvider.SLACK,
        {"workspace": " workspace-1 ", "token": "token"},
    )
    encrypted = encrypt_provider_credentials(credentials, lambda value: f"encrypted:{value}")
    decrypted = decrypt_provider_credentials(
        IMProvider.SLACK,
        encrypted.to_mapping(),
        lambda value: value.removeprefix("encrypted:"),
    )
    result = create_provider_client(decrypted)

    assert credentials.to_mapping() == {"workspace": "workspace-1", "token": "token"}
    assert encrypted.to_mapping() == {"workspace": "workspace-1", "encrypted_token": "encrypted:token"}
    assert decrypted == credentials
    assert result is client
    client_factory.assert_called_once_with(credentials)
