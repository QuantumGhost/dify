from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.im_integration import (
    IMAppInstallation,
    IMInstallMode,
    IMInstallStatus,
    IMProvider,
    IMScopeType,
    IMSelfBuiltTenantConfig,
)
from services.human_input_im.app_config_service import IMTokenStatus


class UpsertIMSelfBuiltTenantConfig(BaseModel):
    """Normalized tenant self-built config payload used by console management flows."""

    provider_workspace_id: str | None = Field(default=None, max_length=255)
    app_id: str | None = Field(default=None, max_length=255)
    app_secret: str | None = None
    verification_token: str | None = None
    encrypt_key: str | None = None
    event_mode: str | None = Field(default=None, max_length=32)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator(
        "provider_workspace_id",
        "app_id",
        "app_secret",
        "verification_token",
        "encrypt_key",
        "event_mode",
        mode="before",
    )
    @classmethod
    def _normalize_optional_string(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value

        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    def has_any_value(self) -> bool:
        return any(
            value is not None
            for value in (
                self.provider_workspace_id,
                self.app_id,
                self.app_secret,
                self.verification_token,
                self.encrypt_key,
                self.event_mode,
            )
        )


class UpsertIMAppInstallation(BaseModel):
    """Normalized installation lifecycle payload used by management APIs."""

    provider_workspace_id: str | None = Field(default=None, max_length=255)
    install_status: IMInstallStatus | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    access_token_expires_at: datetime | None = None
    token_refreshed_at: datetime | None = None
    token_refresh_error: str | None = Field(default=None, max_length=1024)
    installed_at: datetime | None = None
    uninstalled_at: datetime | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator(
        "provider_workspace_id",
        "access_token",
        "refresh_token",
        "token_refresh_error",
        mode="before",
    )
    @classmethod
    def _normalize_optional_string(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value

        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    def has_any_value(self) -> bool:
        return any(
            value is not None
            for value in (
                self.provider_workspace_id,
                self.install_status,
                self.access_token,
                self.refresh_token,
                self.access_token_expires_at,
                self.token_refreshed_at,
                self.token_refresh_error,
                self.installed_at,
                self.uninstalled_at,
            )
        )


class IMSelfBuiltTenantConfigRecord(BaseModel):
    """Redacted self-built config read model for tenant-scoped management APIs."""

    id: str
    tenant_id: str
    provider: IMProvider
    scope_type: IMScopeType
    scope_id: str
    provider_workspace_id: str | None = None
    app_id: str | None = None
    app_secret_configured: bool
    verification_token_configured: bool
    encrypt_key_configured: bool
    event_mode: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_model(cls, config: IMSelfBuiltTenantConfig) -> IMSelfBuiltTenantConfigRecord:
        return cls(
            id=config.id,
            tenant_id=config.tenant_id,
            provider=config.provider,
            scope_type=IMScopeType.TENANT,
            scope_id=config.tenant_id,
            provider_workspace_id=config.provider_workspace_id,
            app_id=config.app_id,
            app_secret_configured=config.encrypted_app_secret is not None,
            verification_token_configured=config.encrypted_verification_token is not None,
            encrypt_key_configured=config.encrypted_encrypt_key is not None,
            event_mode=config.event_mode,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


class IMAppInstallationRecord(BaseModel):
    """Redacted lifecycle read model for install-backed provider management APIs."""

    id: str
    tenant_id: str
    provider: IMProvider
    install_mode: IMInstallMode
    scope_type: IMScopeType
    scope_id: str
    install_status: IMInstallStatus
    token_status: IMTokenStatus
    provider_workspace_id: str | None = None
    access_token_configured: bool
    refresh_token_configured: bool
    access_token_expires_at: datetime | None = None
    token_refreshed_at: datetime | None = None
    token_refresh_error: str | None = None
    installed_at: datetime | None = None
    uninstalled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_model(
        cls,
        config: IMAppInstallation,
        *,
        token_status: IMTokenStatus,
    ) -> IMAppInstallationRecord:
        return cls(
            id=config.id,
            tenant_id=config.tenant_id,
            provider=config.provider,
            install_mode=config.install_mode,
            scope_type=IMScopeType.TENANT,
            scope_id=config.tenant_id,
            install_status=config.install_status,
            token_status=token_status,
            provider_workspace_id=config.provider_workspace_id,
            access_token_configured=config.encrypted_access_token is not None,
            refresh_token_configured=config.encrypted_refresh_token is not None,
            access_token_expires_at=config.access_token_expires_at,
            token_refreshed_at=config.token_refreshed_at,
            token_refresh_error=config.token_refresh_error,
            installed_at=config.installed_at,
            uninstalled_at=config.uninstalled_at,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )
