"""IM integration persistence models for phase-1 HITL foundations.

This module keeps account-facing bindings separate from app-config persistence.
Tenant self-built overrides and future install lifecycle rows intentionally live
in different tables so provider-neutral ownership is not mixed with
provider-specific callback secrets or refresh-token state.
"""

from __future__ import annotations

import enum
import secrets
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from .base import TypeBase, gen_uuidv7_string
from .types import EnumText, LongText, StringUUID


class IMProvider(enum.StrEnum):
    FEISHU = "feishu"
    SLACK = "slack"
    DINGTALK = "dingtalk"


class IMInstallMode(enum.StrEnum):
    SELF_BUILT = "self_built"
    ISV = "isv"


class IMScopeType(enum.StrEnum):
    DEPLOYMENT = "deployment"
    TENANT = "tenant"


class IMInstallStatus(enum.StrEnum):
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    INSTALLED = "installed"
    UNINSTALLED = "uninstalled"


class IMBindingStatus(enum.StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class IMBindingSessionStatus(enum.StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REVOKED = "revoked"


def _generate_binding_session_token() -> str:
    return "imbs_" + secrets.token_urlsafe(18)


class IMSelfBuiltTenantConfig(TypeBase):
    """Tenant-scoped self-built override credentials.

    This row only owns self-built transport credentials and callback material.
    It does not track install / uninstall / token refresh lifecycle.
    """

    __tablename__ = "im_self_built_tenant_configs"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="im_self_built_tenant_configs_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            name="im_self_built_tenant_configs_tenant_provider_key",
        ),
        sa.Index(
            "im_self_built_tenant_configs_tenant_provider_idx",
            "tenant_id",
            "provider",
        ),
    )

    id: Mapped[str] = mapped_column(
        StringUUID,
        insert_default=gen_uuidv7_string,
        default_factory=gen_uuidv7_string,
        init=False,
    )
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    provider: Mapped[IMProvider] = mapped_column(EnumText(IMProvider, length=20), nullable=False)
    provider_workspace_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    app_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    encrypted_app_secret: Mapped[str | None] = mapped_column(LongText, nullable=True, default=None)
    encrypted_verification_token: Mapped[str | None] = mapped_column(LongText, nullable=True, default=None)
    encrypted_encrypt_key: Mapped[str | None] = mapped_column(LongText, nullable=True, default=None)
    event_mode: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
        onupdate=func.current_timestamp(),
    )


class IMAppInstallation(TypeBase):
    """Tenant-scoped install lifecycle row for providers that rotate tokens.

    Lifecycle-managed installs own token refresh state and install status only.
    Self-built callback secrets stay in ``IMSelfBuiltTenantConfig`` instead of
    being mixed into this generic install row.
    """

    __tablename__ = "im_app_installations"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="im_app_installations_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "install_mode",
            name="im_app_installations_tenant_provider_install_mode_key",
        ),
        sa.Index(
            "im_app_installations_tenant_provider_status_idx",
            "tenant_id",
            "provider",
            "install_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        StringUUID,
        insert_default=gen_uuidv7_string,
        default_factory=gen_uuidv7_string,
        init=False,
    )
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    provider: Mapped[IMProvider] = mapped_column(EnumText(IMProvider, length=20), nullable=False)
    install_mode: Mapped[IMInstallMode] = mapped_column(EnumText(IMInstallMode, length=20), nullable=False)
    install_status: Mapped[IMInstallStatus] = mapped_column(
        EnumText(IMInstallStatus, length=20),
        nullable=False,
        server_default=sa.text("'pending'"),
        default=IMInstallStatus.PENDING,
    )
    provider_workspace_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    encrypted_access_token: Mapped[str | None] = mapped_column(LongText, nullable=True, default=None)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(LongText, nullable=True, default=None)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    token_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    token_refresh_error: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    installed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    uninstalled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
        onupdate=func.current_timestamp(),
    )


# Backward-compatible import alias for the pre-refactor tenant override name.
IMAppTenantConfig = IMSelfBuiltTenantConfig


class IMBinding(TypeBase):
    __tablename__ = "im_bindings"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="im_bindings_pkey"),
        sa.Index("im_bindings_account_id_status_idx", "account_id", "status"),
        sa.UniqueConstraint("active_account_id", name="im_bindings_active_account_id_key"),
        sa.UniqueConstraint(
            "provider",
            "install_mode",
            "scope_type",
            "scope_id",
            "provider_workspace_id",
            "provider_user_id",
            name="im_bindings_scope_user_key",
        ),
    )

    id: Mapped[str] = mapped_column(
        StringUUID,
        insert_default=gen_uuidv7_string,
        default_factory=gen_uuidv7_string,
        init=False,
    )
    account_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    provider: Mapped[IMProvider] = mapped_column(EnumText(IMProvider, length=20), nullable=False)
    install_mode: Mapped[IMInstallMode] = mapped_column(EnumText(IMInstallMode, length=20), nullable=False)
    scope_type: Mapped[IMScopeType] = mapped_column(EnumText(IMScopeType, length=20), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Phase-1 uses a nullable mirror column to keep the singleton active-binding
    # rule enforceable on MySQL-compatible schemas without partial unique indexes.
    active_account_id: Mapped[str | None] = mapped_column(StringUUID, nullable=True, default=None)
    provider_union_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    provider_user_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    provider_user_avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    status: Mapped[IMBindingStatus] = mapped_column(
        EnumText(IMBindingStatus, length=20),
        nullable=False,
        server_default=sa.text("'active'"),
        default=IMBindingStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
        onupdate=func.current_timestamp(),
    )

    def __post_init__(self) -> None:
        self.normalize_phase_1_shape()

    def normalize_phase_1_shape(self) -> None:
        self.active_account_id = self.account_id if self.status == IMBindingStatus.ACTIVE else None


class IMBindingSession(TypeBase):
    __tablename__ = "im_binding_sessions"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="im_binding_sessions_pkey"),
        sa.UniqueConstraint("token", name="im_binding_sessions_token_key"),
        sa.Index("im_binding_sessions_account_id_status_idx", "account_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID,
        insert_default=gen_uuidv7_string,
        default_factory=gen_uuidv7_string,
        init=False,
    )
    account_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    provider: Mapped[IMProvider] = mapped_column(EnumText(IMProvider, length=20), nullable=False)
    install_mode: Mapped[IMInstallMode] = mapped_column(EnumText(IMInstallMode, length=20), nullable=False)
    scope_type: Mapped[IMScopeType] = mapped_column(EnumText(IMScopeType, length=20), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[IMBindingSessionStatus] = mapped_column(
        EnumText(IMBindingSessionStatus, length=20),
        nullable=False,
        server_default=sa.text("'pending'"),
        default=IMBindingSessionStatus.PENDING,
    )
    token: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        insert_default=_generate_binding_session_token,
        default_factory=_generate_binding_session_token,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
        onupdate=func.current_timestamp(),
    )


@sa.event.listens_for(IMBinding, "before_insert")
@sa.event.listens_for(IMBinding, "before_update")
def _normalize_im_binding_before_persist(
    _mapper: Mapper[IMBinding],
    _connection: sa.Connection,
    target: IMBinding,
) -> None:
    target.normalize_phase_1_shape()
