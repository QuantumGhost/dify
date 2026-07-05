from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from libs.datetime_utils import naive_utc_now
from models.im_integration import IMAppInstallation, IMSelfBuiltTenantConfig
from services.human_input_im.app_config_service import (
    IMAppConfigStatus,
    IMEventMode,
    IMInstallMode,
    IMInstallStatus,
    IMProvider,
    IMScopeType,
    IMTokenStatus,
    _TenantConfigLookupStatus,
    resolve_im_app_context,
    resolve_token_status_for_install,
)


def test_resolve_im_app_context_reports_missing_credentials(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", None)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", None)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", None)

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.MISSING
    assert context.install_mode == IMInstallMode.SELF_BUILT
    assert context.scope_type == IMScopeType.DEPLOYMENT
    assert context.token_status == IMTokenStatus.NOT_APPLICABLE
    assert "missing LARK_APP_ID" in context.errors
    assert "missing LARK_APP_SECRET" in context.errors
    assert "missing LARK_EVENT_MODE" in context.errors


def test_resolve_im_app_context_requires_long_connection_for_phase_1(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "webhook")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.INVALID
    assert context.event_mode == IMEventMode.WEBHOOK
    assert context.errors == ["phase-1 demo requires LARK_EVENT_MODE=long_connection"]


def test_resolve_im_app_context_reports_partially_missing_credentials(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", None)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.MISSING
    assert context.event_mode == IMEventMode.LONG_CONNECTION
    assert context.app_id == "cli_a"
    assert context.app_secret_configured is False
    assert context.errors == ["missing LARK_APP_SECRET"]


def test_resolve_im_app_context_reports_invalid_unsupported_event_mode(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "socket_mode")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.INVALID
    assert context.event_mode is None
    assert context.errors == ["invalid LARK_EVENT_MODE: socket_mode"]


def test_resolve_im_app_context_reports_unsupported_cloud_edition(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "CLOUD")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", False)

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.UNSUPPORTED
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.event_mode is None
    assert context.errors == ["provider feishu is not supported for cloud edition in phase-1 resolver"]


def test_resolve_im_app_context_returns_configured_self_built_feishu(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.CONFIGURED
    assert context.event_mode == IMEventMode.LONG_CONNECTION
    assert context.app_id == "cli_a"
    assert context.app_secret_configured is True
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.errors == []


def test_resolve_im_app_context_ee_prefers_tenant_override_when_row_is_available(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "SELF_HOSTED")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", True)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")
    monkeypatch.setattr(
        "services.human_input_im.app_config_service._lookup_tenant_self_built_config",
        lambda **_: SimpleNamespace(
            status=_TenantConfigLookupStatus.FOUND,
            config=IMSelfBuiltTenantConfig(
                tenant_id="tenant-override-1",
                provider=IMProvider.FEISHU,
                provider_workspace_id="feishu-workspace-1",
                app_id="tenant-cli_a",
                encrypted_app_secret="tenant-secret",
                encrypted_verification_token="tenant-verification-token",
                encrypted_encrypt_key="tenant-encrypt-key",
                event_mode="long_connection",
            ),
        ),
    )
    monkeypatch.setattr(
        "services.human_input_im.app_config_service._decrypt_optional_secret",
        lambda *, tenant_id, value: {
            "tenant-secret": "tenant-secret-plain",
            "tenant-verification-token": "tenant-verification-token-plain",
            "tenant-encrypt-key": "tenant-encrypt-key-plain",
        }[value],
    )

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-override-1")

    assert context.status == IMAppConfigStatus.CONFIGURED
    assert context.scope_type == IMScopeType.TENANT
    assert context.scope_id == "tenant-override-1"
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.provider_workspace_id == "feishu-workspace-1"
    assert context.app_id == "tenant-cli_a"
    assert context.app_secret == "tenant-secret-plain"
    assert context.verification_token == "tenant-verification-token-plain"
    assert context.encrypt_key == "tenant-encrypt-key-plain"
    assert context.event_mode == IMEventMode.LONG_CONNECTION
    assert context.token_status == IMTokenStatus.NOT_APPLICABLE
    assert context.errors == []


def test_resolve_im_app_context_ee_falls_back_when_tenant_config_store_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "SELF_HOSTED")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", True)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")
    monkeypatch.setattr(
        "services.human_input_im.app_config_service._lookup_tenant_self_built_config",
        lambda **_: SimpleNamespace(
            status=_TenantConfigLookupStatus.STORE_UNAVAILABLE,
            config=None,
            unavailable_reason="flask_app_context_unavailable",
        ),
    )

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.CONFIGURED
    assert context.install_mode == IMInstallMode.SELF_BUILT
    assert context.scope_type == IMScopeType.DEPLOYMENT
    assert context.scope_id == "deployment"
    assert context.token_status == IMTokenStatus.NOT_APPLICABLE
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.event_mode == IMEventMode.LONG_CONNECTION


def test_resolve_im_app_context_ee_falls_back_when_flask_app_context_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "SELF_HOSTED")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", True)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")
    monkeypatch.setattr("services.human_input_im.app_config_service.has_app_context", lambda: False)

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.CONFIGURED
    assert context.install_mode == IMInstallMode.SELF_BUILT
    assert context.scope_type == IMScopeType.DEPLOYMENT
    assert context.scope_id == "deployment"
    assert context.token_status == IMTokenStatus.NOT_APPLICABLE
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.event_mode == IMEventMode.LONG_CONNECTION


def test_resolve_im_app_context_ee_falls_back_when_sqlalchemy_extension_is_unbound(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "SELF_HOSTED")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", True)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")

    app_token = object()
    monkeypatch.setattr("services.human_input_im.app_config_service.has_app_context", lambda: True)
    monkeypatch.setattr(
        "services.human_input_im.app_config_service.current_app",
        SimpleNamespace(_get_current_object=lambda: app_token),
    )
    monkeypatch.setattr(
        "services.human_input_im.app_config_service.db",
        SimpleNamespace(_app_engines={}, engine=object()),
    )

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.CONFIGURED
    assert context.install_mode == IMInstallMode.SELF_BUILT
    assert context.scope_type == IMScopeType.DEPLOYMENT
    assert context.scope_id == "deployment"
    assert context.token_status == IMTokenStatus.NOT_APPLICABLE
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.event_mode == IMEventMode.LONG_CONNECTION


def test_resolve_im_app_context_ee_propagates_unexpected_store_errors(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "SELF_HOSTED")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", True)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")

    app_token = object()
    monkeypatch.setattr("services.human_input_im.app_config_service.has_app_context", lambda: True)
    monkeypatch.setattr(
        "services.human_input_im.app_config_service.current_app",
        SimpleNamespace(_get_current_object=lambda: app_token),
    )
    monkeypatch.setattr(
        "services.human_input_im.app_config_service.db",
        SimpleNamespace(_app_engines={app_token: object()}, engine=object()),
    )

    class _BrokenSession:
        def __enter__(self):
            raise OperationalError("select tenant self-built config", {}, Exception("boom"))

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "services.human_input_im.app_config_service.Session",
        lambda *args, **kwargs: _BrokenSession(),
    )

    with pytest.raises(OperationalError):
        resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")


def test_resolve_im_app_context_ee_reports_missing_tenant_override_credentials(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "SELF_HOSTED")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", True)
    monkeypatch.setattr(
        "services.human_input_im.app_config_service._lookup_tenant_self_built_config",
        lambda **_: SimpleNamespace(
            status=_TenantConfigLookupStatus.FOUND,
            config=IMSelfBuiltTenantConfig(
                tenant_id="tenant-1",
                provider=IMProvider.FEISHU,
                provider_workspace_id="feishu-workspace-1",
                app_id="tenant-cli_a",
                encrypted_app_secret=None,
                event_mode="long_connection",
            ),
        ),
    )

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.scope_type == IMScopeType.TENANT
    assert context.scope_id == "tenant-1"
    assert context.status == IMAppConfigStatus.MISSING
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.errors == ["missing tenant app_secret"]


def test_resolve_im_app_context_ee_uses_deployment_global_self_built_scope(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "SELF_HOSTED")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", True)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")
    monkeypatch.setattr(
        "services.human_input_im.app_config_service._lookup_tenant_self_built_config",
        lambda **_: SimpleNamespace(
            status=_TenantConfigLookupStatus.NOT_FOUND,
            config=None,
        ),
    )

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.CONFIGURED
    assert context.install_mode == IMInstallMode.SELF_BUILT
    assert context.scope_type == IMScopeType.DEPLOYMENT
    assert context.scope_id == "deployment"
    assert context.token_status == IMTokenStatus.NOT_APPLICABLE
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.event_mode == IMEventMode.LONG_CONNECTION


def test_resolve_im_app_context_normalizes_blank_self_built_credentials_to_missing(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "  ")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "\t")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "\n")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.MISSING
    assert context.event_mode is None
    assert context.app_id is None
    assert context.app_secret is None
    assert context.app_secret_configured is False
    assert context.errors == [
        "missing LARK_APP_ID",
        "missing LARK_APP_SECRET",
        "missing LARK_EVENT_MODE",
    ]


def test_resolve_im_app_context_cloud_unsupported_precedes_valid_self_built_config(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "CLOUD")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", False)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.UNSUPPORTED
    assert context.install_mode == IMInstallMode.SELF_BUILT
    assert context.scope_type == IMScopeType.DEPLOYMENT
    assert context.scope_id == "deployment"
    assert context.token_status == IMTokenStatus.NOT_APPLICABLE
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.event_mode is None
    assert context.app_id is None
    assert context.app_secret is None
    assert context.errors == ["provider feishu is not supported for cloud edition in phase-1 resolver"]


@pytest.mark.parametrize(
    ("provider", "install_mode", "expected_scope_type", "expected_error_fragment"),
    [
        (IMProvider.SLACK, IMInstallMode.ISV, IMScopeType.TENANT, "cloud tenant-scoped isv lifecycle"),
        (IMProvider.DINGTALK, IMInstallMode.SELF_BUILT, IMScopeType.TENANT, "cloud tenant-scoped self-built lifecycle"),
    ],
)
def test_resolve_im_app_context_returns_reserved_cloud_context_for_future_providers(
    monkeypatch,
    provider: IMProvider,
    install_mode: IMInstallMode,
    expected_scope_type: IMScopeType,
    expected_error_fragment: str,
) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.EDITION", "CLOUD")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.ENTERPRISE_ENABLED", False)

    context = resolve_im_app_context(provider=provider, tenant_id="tenant-1")

    assert context.provider == provider
    assert context.install_mode == install_mode
    assert context.scope_type == expected_scope_type
    assert context.scope_id == "tenant-1"
    assert context.status == IMAppConfigStatus.UNSUPPORTED
    assert context.install_status == IMInstallStatus.NOT_APPLICABLE
    assert context.token_status == IMTokenStatus.NOT_APPLICABLE
    assert expected_error_fragment in context.errors[0]


@pytest.mark.parametrize(
    ("install_status", "encrypted_access_token", "expires_in", "refresh_error", "expected"),
    [
        (IMInstallStatus.PENDING, "token", timedelta(minutes=30), None, IMTokenStatus.UNKNOWN),
        (IMInstallStatus.UNINSTALLED, "token", timedelta(minutes=30), None, IMTokenStatus.UNKNOWN),
        (IMInstallStatus.INSTALLED, None, timedelta(minutes=30), None, IMTokenStatus.UNKNOWN),
        (IMInstallStatus.INSTALLED, "token", timedelta(minutes=30), "boom", IMTokenStatus.REFRESH_FAILED),
        (IMInstallStatus.INSTALLED, "token", timedelta(minutes=-1), None, IMTokenStatus.EXPIRED),
        (IMInstallStatus.INSTALLED, "token", timedelta(minutes=5), None, IMTokenStatus.EXPIRING),
        (IMInstallStatus.INSTALLED, "token", timedelta(minutes=30), None, IMTokenStatus.VALID),
    ],
)
def test_resolve_token_status_for_install_reports_install_lifecycle_state(
    install_status: IMInstallStatus,
    encrypted_access_token: str | None,
    expires_in: timedelta,
    refresh_error: str | None,
    expected: IMTokenStatus,
) -> None:
    config = IMAppInstallation(
        tenant_id="tenant-1",
        provider=IMProvider.SLACK,
        install_mode=IMInstallMode.ISV,
        install_status=install_status,
        encrypted_access_token=encrypted_access_token,
        access_token_expires_at=naive_utc_now() + expires_in,
        token_refresh_error=refresh_error,
    )

    assert resolve_token_status_for_install(config) == expected
