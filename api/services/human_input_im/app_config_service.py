"""IM app config resolution for phase-1 HITL foundations.

This module resolves runtime app context from deployment configuration without
requiring a persisted installation row. The current production slice only ships
the Feishu self-built demo path, but the internal self-built config seam keeps
credential loading and provider-specific validation separate so later providers
can reuse the same resolver shape without parallel code paths.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from configs import dify_config
from models.im_integration import IMInstallMode, IMProvider, IMScopeType


class IMAppConfigStatus(enum.StrEnum):
    CONFIGURED = "configured"
    MISSING = "missing"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


class IMTokenStatus(enum.StrEnum):
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


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
    event_mode: IMEventMode | None = None
    app_id: str | None = None
    app_secret: str | None = None
    app_secret_configured: bool = False
    verification_token: str | None = None
    encrypt_key: str | None = None
    provider_workspace_id: str | None = None
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


def resolve_im_app_context(*, provider: IMProvider, tenant_id: str) -> IMAppContext:
    """Resolve the runtime IM app context for one provider and workspace."""

    _ = tenant_id
    runtime_edition = _resolve_runtime_edition()

    if runtime_edition == _IMRuntimeEdition.CLOUD:
        return _build_unsupported_context(
            provider=provider,
            errors=[f"provider {provider.value} is not supported for cloud edition in phase-1 resolver"],
        )

    if provider != IMProvider.FEISHU:
        return _build_unsupported_context(
            provider=provider,
            errors=[f"provider {provider.value} is not supported in phase-1 resolver"],
        )

    app_config = _resolve_feishu_self_built_app_config()
    return IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=_resolve_app_config_status(app_config.errors),
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=app_config.event_mode,
        app_id=app_config.app_id,
        app_secret=app_config.app_secret,
        app_secret_configured=app_config.app_secret_configured,
        verification_token=app_config.verification_token,
        encrypt_key=app_config.encrypt_key,
        errors=app_config.errors,
    )


def _resolve_runtime_edition() -> _IMRuntimeEdition:
    if dify_config.EDITION == "CLOUD":
        return _IMRuntimeEdition.CLOUD
    if dify_config.ENTERPRISE_ENABLED:
        return _IMRuntimeEdition.EE
    return _IMRuntimeEdition.CE


def _build_unsupported_context(*, provider: IMProvider, errors: list[str]) -> IMAppContext:
    return IMAppContext(
        provider=provider,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=IMAppConfigStatus.UNSUPPORTED,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        errors=errors,
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


def _resolve_app_config_status(errors: list[str]) -> IMAppConfigStatus:
    if any(error.startswith("missing ") for error in errors):
        return IMAppConfigStatus.MISSING
    if errors:
        return IMAppConfigStatus.INVALID
    return IMAppConfigStatus.CONFIGURED
