"""IM app config resolution for phase-1 HITL foundations.

The current Feishu demo still defaults to deployment-global self-built config.
EE tenant overrides are stored separately from future install lifecycle rows so
runtime resolution does not couple self-built callback secrets to ISV token
refresh state.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta

from flask import current_app, has_app_context
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from configs import dify_config
from core.helper import encrypter
from extensions.ext_database import db
from libs.datetime_utils import naive_utc_now
from models.im_integration import (
    IMAppInstallation,
    IMInstallMode,
    IMInstallStatus,
    IMProvider,
    IMScopeType,
    IMSelfBuiltTenantConfig,
)


class IMAppConfigStatus(enum.StrEnum):
    CONFIGURED = "configured"
    MISSING = "missing"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


class IMTokenStatus(enum.StrEnum):
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"
    VALID = "valid"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    REFRESH_FAILED = "refresh_failed"


class IMEventMode(enum.StrEnum):
    LONG_CONNECTION = "long_connection"
    WEBHOOK = "webhook"


class _IMRuntimeEdition(enum.StrEnum):
    CE = "ce"
    EE = "ee"
    CLOUD = "cloud"


class IMAppContext(BaseModel):
    provider: IMProvider
    install_mode: IMInstallMode
    scope_type: IMScopeType
    scope_id: str
    status: IMAppConfigStatus
    token_status: IMTokenStatus
    install_status: IMInstallStatus = IMInstallStatus.NOT_APPLICABLE
    event_mode: IMEventMode | None = None
    app_id: str | None = None
    app_secret: str | None = None
    app_secret_configured: bool = False
    verification_token: str | None = None
    encrypt_key: str | None = None
    provider_workspace_id: str | None = None
    access_token_expires_at: datetime | None = None
    token_refreshed_at: datetime | None = None
    errors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)


@dataclass(frozen=True)
class _SelfBuiltCredentialField:
    config_key: str
    value: str | None


@dataclass(frozen=True)
class _SelfBuiltAppConfigSnapshot:
    app_id: str | None
    app_secret: str | None
    verification_token: str | None
    encrypt_key: str | None
    app_secret_configured: bool
    event_mode: IMEventMode | None
    errors: list[str]


@dataclass(frozen=True)
class _SelfBuiltProviderValidation:
    event_mode: IMEventMode | None
    errors: list[str]


class _TenantConfigLookupStatus(enum.StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    STORE_UNAVAILABLE = "store_unavailable"


@dataclass(frozen=True)
class _TenantSelfBuiltLookupResult:
    status: _TenantConfigLookupStatus
    config: IMSelfBuiltTenantConfig | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class _AppInstallationLookupResult:
    status: _TenantConfigLookupStatus
    config: IMAppInstallation | None = None
    unavailable_reason: str | None = None


def resolve_im_app_context(*, provider: IMProvider, tenant_id: str) -> IMAppContext:
    """Resolve the runtime IM app context for one provider and workspace.

    Resolution order is intentionally edition-aware:

    - CE: deployment-global config only;
    - EE: tenant override row first, then deployment-global fallback;
    - Cloud: return the provider/mode scope reserved for later lifecycle-backed
      implementations instead of pretending every provider is deployment-global.
    """

    runtime_edition = _resolve_runtime_edition()

    if provider == IMProvider.FEISHU:
        if runtime_edition == _IMRuntimeEdition.EE:
            tenant_override_context = _resolve_feishu_tenant_override_app_context(tenant_id=tenant_id)
            if tenant_override_context is not None:
                return tenant_override_context

        if runtime_edition == _IMRuntimeEdition.CLOUD:
            return _build_unsupported_context(
                provider=provider,
                install_mode=IMInstallMode.SELF_BUILT,
                scope_type=IMScopeType.DEPLOYMENT,
                scope_id="deployment",
                errors=["provider feishu is not supported for cloud edition in phase-1 resolver"],
            )

        app_config = _resolve_feishu_self_built_app_config()
        return IMAppContext(
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            status=_resolve_app_config_status(app_config.errors),
            token_status=IMTokenStatus.NOT_APPLICABLE,
            install_status=IMInstallStatus.NOT_APPLICABLE,
            event_mode=app_config.event_mode,
            app_id=app_config.app_id,
            app_secret=app_config.app_secret,
            app_secret_configured=app_config.app_secret_configured,
            verification_token=app_config.verification_token,
            encrypt_key=app_config.encrypt_key,
            errors=app_config.errors,
        )

    if provider == IMProvider.SLACK:
        if runtime_edition == _IMRuntimeEdition.CLOUD:
            return _resolve_slack_installation_app_context(tenant_id=tenant_id)
        return _build_unsupported_context(
            provider=provider,
            install_mode=IMInstallMode.ISV,
            scope_type=IMScopeType.TENANT,
            scope_id=tenant_id,
            errors=["provider slack is only supported for cloud tenant-scoped isv resolution in phase-1"],
        )

    if provider == IMProvider.DINGTALK:
        if runtime_edition == _IMRuntimeEdition.CLOUD:
            return _resolve_dingtalk_tenant_self_built_app_context(tenant_id=tenant_id)
        return _build_unsupported_context(
            provider=provider,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.TENANT,
            scope_id=tenant_id,
            errors=["provider dingtalk is only supported for cloud tenant-scoped self-built resolution in phase-1"],
        )

    return _build_unsupported_context(
        provider=provider,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        errors=[f"provider {provider.value} is not supported in phase-1 resolver"],
    )


def _resolve_runtime_edition() -> _IMRuntimeEdition:
    if dify_config.EDITION == "CLOUD":
        return _IMRuntimeEdition.CLOUD
    if dify_config.ENTERPRISE_ENABLED:
        return _IMRuntimeEdition.EE
    return _IMRuntimeEdition.CE


def _build_unsupported_context(
    *,
    provider: IMProvider,
    install_mode: IMInstallMode,
    scope_type: IMScopeType,
    scope_id: str,
    errors: list[str],
) -> IMAppContext:
    return IMAppContext(
        provider=provider,
        install_mode=install_mode,
        scope_type=scope_type,
        scope_id=scope_id,
        status=IMAppConfigStatus.UNSUPPORTED,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        install_status=IMInstallStatus.NOT_APPLICABLE,
        errors=errors,
    )


def _resolve_feishu_tenant_override_app_context(*, tenant_id: str) -> IMAppContext | None:
    lookup = _lookup_tenant_self_built_config(
        tenant_id=tenant_id,
        provider=IMProvider.FEISHU,
    )
    if lookup.status == _TenantConfigLookupStatus.NOT_FOUND:
        return None
    if lookup.status == _TenantConfigLookupStatus.STORE_UNAVAILABLE:
        return None

    config = lookup.config
    if config is None:
        return None

    app_id = _normalize_config_value(config.app_id)
    app_secret = _decrypt_optional_secret(tenant_id=tenant_id, value=config.encrypted_app_secret)
    verification_token = _decrypt_optional_secret(tenant_id=tenant_id, value=config.encrypted_verification_token)
    encrypt_key = _decrypt_optional_secret(tenant_id=tenant_id, value=config.encrypted_encrypt_key)
    raw_event_mode = _normalize_config_value(config.event_mode)
    validation = _validate_feishu_self_built_config(raw_event_mode=raw_event_mode)
    snapshot = _resolve_self_built_app_config(
        app_id=app_id,
        app_secret=app_secret,
        verification_token=verification_token,
        encrypt_key=encrypt_key,
        fields=(
            _SelfBuiltCredentialField(config_key="tenant app_id", value=app_id),
            _SelfBuiltCredentialField(config_key="tenant app_secret", value=app_secret),
            _SelfBuiltCredentialField(config_key="tenant event_mode", value=raw_event_mode),
        ),
        validation=validation,
    )
    errors = list(snapshot.errors)

    return IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.TENANT,
        scope_id=tenant_id,
        status=_resolve_app_config_status(errors),
        token_status=IMTokenStatus.NOT_APPLICABLE,
        install_status=IMInstallStatus.NOT_APPLICABLE,
        event_mode=snapshot.event_mode,
        app_id=snapshot.app_id,
        app_secret=snapshot.app_secret,
        app_secret_configured=snapshot.app_secret_configured,
        verification_token=snapshot.verification_token,
        encrypt_key=snapshot.encrypt_key,
        provider_workspace_id=config.provider_workspace_id,
        errors=errors,
    )


def _resolve_dingtalk_tenant_self_built_app_context(*, tenant_id: str) -> IMAppContext:
    lookup = _lookup_tenant_self_built_config(
        tenant_id=tenant_id,
        provider=IMProvider.DINGTALK,
    )
    if lookup.status != _TenantConfigLookupStatus.FOUND or lookup.config is None:
        return IMAppContext(
            provider=IMProvider.DINGTALK,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.TENANT,
            scope_id=tenant_id,
            status=IMAppConfigStatus.MISSING,
            token_status=IMTokenStatus.NOT_APPLICABLE,
            install_status=IMInstallStatus.NOT_APPLICABLE,
            errors=[_describe_lookup_failure("tenant self-built config", lookup)],
        )

    config = lookup.config
    snapshot = _resolve_self_built_app_config(
        app_id=_normalize_config_value(config.app_id),
        app_secret=_decrypt_optional_secret(tenant_id=tenant_id, value=config.encrypted_app_secret),
        verification_token=None,
        encrypt_key=None,
        fields=(
            _SelfBuiltCredentialField(config_key="tenant app_id", value=_normalize_config_value(config.app_id)),
            _SelfBuiltCredentialField(
                config_key="tenant app_secret",
                value=_decrypt_optional_secret(tenant_id=tenant_id, value=config.encrypted_app_secret),
            ),
        ),
        validation=_SelfBuiltProviderValidation(event_mode=None, errors=[]),
    )
    return IMAppContext(
        provider=IMProvider.DINGTALK,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.TENANT,
        scope_id=tenant_id,
        status=_resolve_app_config_status(snapshot.errors),
        token_status=IMTokenStatus.NOT_APPLICABLE,
        install_status=IMInstallStatus.NOT_APPLICABLE,
        app_id=snapshot.app_id,
        app_secret=snapshot.app_secret,
        app_secret_configured=snapshot.app_secret_configured,
        provider_workspace_id=config.provider_workspace_id,
        errors=snapshot.errors,
    )


def _resolve_slack_installation_app_context(*, tenant_id: str) -> IMAppContext:
    lookup = _lookup_app_installation(
        tenant_id=tenant_id,
        provider=IMProvider.SLACK,
        install_mode=IMInstallMode.ISV,
    )
    if lookup.status != _TenantConfigLookupStatus.FOUND or lookup.config is None:
        return IMAppContext(
            provider=IMProvider.SLACK,
            install_mode=IMInstallMode.ISV,
            scope_type=IMScopeType.TENANT,
            scope_id=tenant_id,
            status=IMAppConfigStatus.MISSING,
            token_status=IMTokenStatus.UNKNOWN,
            install_status=IMInstallStatus.PENDING,
            errors=[_describe_lookup_failure("app installation", lookup)],
        )

    installation = lookup.config
    token_status = resolve_token_status_for_install(installation)
    return IMAppContext(
        provider=IMProvider.SLACK,
        install_mode=IMInstallMode.ISV,
        scope_type=IMScopeType.TENANT,
        scope_id=tenant_id,
        status=_resolve_install_context_status(installation.install_status, token_status),
        token_status=token_status,
        install_status=installation.install_status,
        provider_workspace_id=installation.provider_workspace_id,
        access_token_expires_at=installation.access_token_expires_at,
        token_refreshed_at=installation.token_refreshed_at,
        errors=_build_install_context_errors(installation.install_status, token_status),
    )


def _resolve_feishu_self_built_app_config() -> _SelfBuiltAppConfigSnapshot:
    """Resolve deployment-global Feishu self-built credentials and demo constraints."""

    app_id = _normalize_config_value(dify_config.LARK_APP_ID)
    app_secret = _normalize_config_value(dify_config.LARK_APP_SECRET)
    verification_token = _normalize_config_value(dify_config.LARK_VERIFICATION_TOKEN)
    encrypt_key = _normalize_config_value(dify_config.LARK_ENCRYPT_KEY)
    raw_event_mode = _normalize_config_value(dify_config.LARK_EVENT_MODE)
    validation = _validate_feishu_self_built_config(raw_event_mode=raw_event_mode)

    return _resolve_self_built_app_config(
        app_id=app_id,
        app_secret=app_secret,
        verification_token=verification_token,
        encrypt_key=encrypt_key,
        fields=(
            _SelfBuiltCredentialField(config_key="LARK_APP_ID", value=app_id),
            _SelfBuiltCredentialField(config_key="LARK_APP_SECRET", value=app_secret),
            _SelfBuiltCredentialField(config_key="LARK_EVENT_MODE", value=raw_event_mode),
        ),
        validation=validation,
    )


def _resolve_self_built_app_config(
    *,
    app_id: str | None,
    app_secret: str | None,
    verification_token: str | None,
    encrypt_key: str | None,
    fields: tuple[_SelfBuiltCredentialField, ...],
    validation: _SelfBuiltProviderValidation,
) -> _SelfBuiltAppConfigSnapshot:
    errors = _collect_missing_self_built_fields(fields=fields)
    errors.extend(validation.errors)

    return _SelfBuiltAppConfigSnapshot(
        app_id=app_id,
        app_secret=app_secret,
        verification_token=verification_token,
        encrypt_key=encrypt_key,
        app_secret_configured=app_secret is not None,
        event_mode=validation.event_mode,
        errors=errors,
    )


def _lookup_tenant_self_built_config(
    *,
    tenant_id: str,
    provider: IMProvider,
) -> _TenantSelfBuiltLookupResult:
    if not has_app_context():
        return _TenantSelfBuiltLookupResult(
            status=_TenantConfigLookupStatus.STORE_UNAVAILABLE,
            unavailable_reason="flask_app_context_unavailable",
        )

    app = current_app._get_current_object()
    if app not in db._app_engines:
        return _TenantSelfBuiltLookupResult(
            status=_TenantConfigLookupStatus.STORE_UNAVAILABLE,
            unavailable_reason="sqlalchemy_extension_unbound",
        )

    with Session(db.engine, expire_on_commit=False) as session:
        stmt = (
            select(IMSelfBuiltTenantConfig)
            .where(
                IMSelfBuiltTenantConfig.tenant_id == tenant_id,
                IMSelfBuiltTenantConfig.provider == provider,
            )
            .limit(1)
        )
        config = session.execute(stmt).scalar_one_or_none()

    if config is None:
        return _TenantSelfBuiltLookupResult(status=_TenantConfigLookupStatus.NOT_FOUND)
    return _TenantSelfBuiltLookupResult(status=_TenantConfigLookupStatus.FOUND, config=config)


def _lookup_app_installation(
    *,
    tenant_id: str,
    provider: IMProvider,
    install_mode: IMInstallMode,
) -> _AppInstallationLookupResult:
    if not has_app_context():
        return _AppInstallationLookupResult(
            status=_TenantConfigLookupStatus.STORE_UNAVAILABLE,
            unavailable_reason="flask_app_context_unavailable",
        )

    app = current_app._get_current_object()
    if app not in db._app_engines:
        return _AppInstallationLookupResult(
            status=_TenantConfigLookupStatus.STORE_UNAVAILABLE,
            unavailable_reason="sqlalchemy_extension_unbound",
        )

    with Session(db.engine, expire_on_commit=False) as session:
        stmt = (
            select(IMAppInstallation)
            .where(
                IMAppInstallation.tenant_id == tenant_id,
                IMAppInstallation.provider == provider,
                IMAppInstallation.install_mode == install_mode,
            )
            .limit(1)
        )
        config = session.execute(stmt).scalar_one_or_none()

    if config is None:
        return _AppInstallationLookupResult(status=_TenantConfigLookupStatus.NOT_FOUND)
    return _AppInstallationLookupResult(status=_TenantConfigLookupStatus.FOUND, config=config)


def _decrypt_optional_secret(*, tenant_id: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_config_value(encrypter.decrypt_token(tenant_id, value))


def _validate_feishu_self_built_config(*, raw_event_mode: str | None) -> _SelfBuiltProviderValidation:
    if raw_event_mode is None:
        return _SelfBuiltProviderValidation(event_mode=None, errors=[])

    try:
        event_mode = IMEventMode(raw_event_mode)
    except ValueError:
        return _SelfBuiltProviderValidation(
            event_mode=None,
            errors=[f"invalid LARK_EVENT_MODE: {raw_event_mode}"],
        )

    if event_mode != IMEventMode.LONG_CONNECTION:
        return _SelfBuiltProviderValidation(
            event_mode=event_mode,
            errors=["phase-1 demo requires LARK_EVENT_MODE=long_connection"],
        )

    return _SelfBuiltProviderValidation(event_mode=event_mode, errors=[])


def _collect_missing_self_built_fields(*, fields: tuple[_SelfBuiltCredentialField, ...]) -> list[str]:
    return [f"missing {field.config_key}" for field in fields if field.value is None]


def _normalize_config_value(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return normalized


def resolve_token_status_for_install(config: IMAppInstallation) -> IMTokenStatus:
    """Expose lifecycle token state for install-backed providers without sending secrets."""

    if config.install_mode == IMInstallMode.SELF_BUILT:
        return IMTokenStatus.NOT_APPLICABLE
    if config.install_status != IMInstallStatus.INSTALLED:
        return IMTokenStatus.UNKNOWN
    if config.token_refresh_error:
        return IMTokenStatus.REFRESH_FAILED
    if not config.encrypted_access_token or config.access_token_expires_at is None:
        return IMTokenStatus.UNKNOWN

    now = naive_utc_now()
    if config.access_token_expires_at <= now:
        return IMTokenStatus.EXPIRED
    if config.access_token_expires_at <= now + timedelta(minutes=10):
        return IMTokenStatus.EXPIRING
    return IMTokenStatus.VALID


def _resolve_install_context_status(
    install_status: IMInstallStatus,
    token_status: IMTokenStatus,
) -> IMAppConfigStatus:
    if install_status != IMInstallStatus.INSTALLED:
        return IMAppConfigStatus.MISSING
    if token_status in {IMTokenStatus.REFRESH_FAILED, IMTokenStatus.EXPIRED}:
        return IMAppConfigStatus.INVALID
    if token_status == IMTokenStatus.UNKNOWN:
        return IMAppConfigStatus.MISSING
    return IMAppConfigStatus.CONFIGURED


def _build_install_context_errors(
    install_status: IMInstallStatus,
    token_status: IMTokenStatus,
) -> list[str]:
    if install_status == IMInstallStatus.UNINSTALLED:
        return ["app installation is uninstalled"]
    if install_status == IMInstallStatus.PENDING:
        return ["app installation is pending"]
    if token_status == IMTokenStatus.REFRESH_FAILED:
        return ["app installation token refresh failed"]
    if token_status == IMTokenStatus.EXPIRED:
        return ["app installation access token is expired"]
    if token_status == IMTokenStatus.UNKNOWN:
        return ["app installation is missing token state"]
    return []


def _describe_lookup_failure(label: str, lookup: _TenantSelfBuiltLookupResult | _AppInstallationLookupResult) -> str:
    if lookup.status == _TenantConfigLookupStatus.NOT_FOUND:
        return f"missing {label}"
    if lookup.unavailable_reason:
        return f"{label} store unavailable: {lookup.unavailable_reason}"
    return f"{label} store unavailable"


def _resolve_app_config_status(errors: list[str]) -> IMAppConfigStatus:
    if any(error.startswith("missing ") for error in errors):
        return IMAppConfigStatus.MISSING
    if errors:
        return IMAppConfigStatus.INVALID
    return IMAppConfigStatus.CONFIGURED
