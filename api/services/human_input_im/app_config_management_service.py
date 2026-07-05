"""Console-side IM app config management seams.

This module intentionally keeps tenant self-built config writes separate from
install lifecycle reads. The runtime resolver can compose both sources later,
but the management API should not blur credential material with token refresh
state or pretend Slack OAuth is already implemented.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.helper import encrypter
from libs.datetime_utils import naive_utc_now
from models.im_integration import IMAppInstallation, IMInstallMode, IMInstallStatus, IMProvider, IMSelfBuiltTenantConfig
from services.entities.im_app_entities import (
    IMAppInstallationRecord,
    IMSelfBuiltTenantConfigRecord,
    UpsertIMAppInstallation,
    UpsertIMSelfBuiltTenantConfig,
)
from services.errors.im_app_config import IMAppConfigValidationError
from services.human_input_im.app_config_service import resolve_token_status_for_install
from services.human_input_observability import build_human_input_log_context

logger = logging.getLogger(__name__)


def get_tenant_self_built_config(
    *,
    session: Session,
    tenant_id: str,
    provider: IMProvider,
) -> IMSelfBuiltTenantConfigRecord | None:
    config = _get_tenant_self_built_config_model(
        session=session,
        tenant_id=tenant_id,
        provider=provider,
    )
    if config is None:
        return None
    return IMSelfBuiltTenantConfigRecord.from_model(config)


def upsert_tenant_self_built_config(
    *,
    session: Session,
    tenant_id: str,
    provider: IMProvider,
    request: UpsertIMSelfBuiltTenantConfig,
) -> IMSelfBuiltTenantConfigRecord:
    # NOTE(QuantumGhost): a fully blank override row changes EE resolution from
    # deployment fallback to tenant-scoped missing config, so callers must use
    # the explicit delete endpoint when they want to remove an override.
    if not request.has_any_value():
        raise IMAppConfigValidationError("self-built tenant config payload must include at least one non-empty field")

    config = _get_tenant_self_built_config_model(
        session=session,
        tenant_id=tenant_id,
        provider=provider,
    )
    if config is None:
        config = IMSelfBuiltTenantConfig(
            tenant_id=tenant_id,
            provider=provider,
        )
        session.add(config)

    config.provider_workspace_id = request.provider_workspace_id
    config.app_id = request.app_id
    config.encrypted_app_secret = _encrypt_optional_secret(tenant_id=tenant_id, value=request.app_secret)
    config.encrypted_verification_token = _encrypt_optional_secret(
        tenant_id=tenant_id,
        value=request.verification_token,
    )
    config.encrypted_encrypt_key = _encrypt_optional_secret(tenant_id=tenant_id, value=request.encrypt_key)
    config.event_mode = request.event_mode

    session.flush([config])
    logger.info(
        "Upserted IM self-built tenant config",
        extra=build_human_input_log_context(
            tenant_id=tenant_id,
            provider=provider,
            provider_workspace_id=request.provider_workspace_id,
            extra={
                "im_scope_type": "tenant",
                "im_scope_id": tenant_id,
                "im_install_mode": IMInstallMode.SELF_BUILT,
            },
        ),
    )
    return IMSelfBuiltTenantConfigRecord.from_model(config)


def delete_tenant_self_built_config(
    *,
    session: Session,
    tenant_id: str,
    provider: IMProvider,
) -> bool:
    config = _get_tenant_self_built_config_model(
        session=session,
        tenant_id=tenant_id,
        provider=provider,
    )
    if config is None:
        logger.info(
            "Skipped IM self-built tenant config delete because no row exists",
            extra=build_human_input_log_context(
                tenant_id=tenant_id,
                provider=provider,
                extra={
                    "im_scope_type": "tenant",
                    "im_scope_id": tenant_id,
                    "im_install_mode": IMInstallMode.SELF_BUILT,
                },
            ),
        )
        return False

    session.delete(config)
    logger.info(
        "Deleted IM self-built tenant config",
        extra=build_human_input_log_context(
            tenant_id=tenant_id,
            provider=provider,
            provider_workspace_id=config.provider_workspace_id,
            extra={
                "im_scope_type": "tenant",
                "im_scope_id": tenant_id,
                "im_install_mode": IMInstallMode.SELF_BUILT,
            },
        ),
    )
    return True


def get_app_installation(
    *,
    session: Session,
    tenant_id: str,
    provider: IMProvider,
    install_mode: IMInstallMode,
) -> IMAppInstallationRecord | None:
    installation = _get_app_installation_model(
        session=session,
        tenant_id=tenant_id,
        provider=provider,
        install_mode=install_mode,
    )
    if installation is None:
        return None

    return IMAppInstallationRecord.from_model(
        installation,
        token_status=resolve_token_status_for_install(installation),
    )


def upsert_app_installation(
    *,
    session: Session,
    tenant_id: str,
    provider: IMProvider,
    install_mode: IMInstallMode,
    request: UpsertIMAppInstallation,
) -> IMAppInstallationRecord:
    if not request.has_any_value():
        raise IMAppConfigValidationError("app installation payload must include at least one non-empty field")

    installation = _get_app_installation_model(
        session=session,
        tenant_id=tenant_id,
        provider=provider,
        install_mode=install_mode,
    )
    if installation is None:
        installation = IMAppInstallation(
            tenant_id=tenant_id,
            provider=provider,
            install_mode=install_mode,
        )
        session.add(installation)

    if request.install_status is not None:
        installation.install_status = request.install_status
    installation.provider_workspace_id = request.provider_workspace_id
    installation.encrypted_access_token = _encrypt_optional_secret(tenant_id=tenant_id, value=request.access_token)
    installation.encrypted_refresh_token = _encrypt_optional_secret(tenant_id=tenant_id, value=request.refresh_token)
    installation.access_token_expires_at = request.access_token_expires_at
    installation.token_refreshed_at = request.token_refreshed_at
    installation.token_refresh_error = request.token_refresh_error
    installation.installed_at = request.installed_at
    installation.uninstalled_at = request.uninstalled_at

    session.flush([installation])
    logger.info(
        "Upserted IM app installation",
        extra=build_human_input_log_context(
            tenant_id=tenant_id,
            provider=provider,
            provider_workspace_id=request.provider_workspace_id,
            extra={
                "im_scope_type": "tenant",
                "im_scope_id": tenant_id,
                "im_install_mode": install_mode,
                "im_install_status": installation.install_status,
            },
        ),
    )
    return IMAppInstallationRecord.from_model(
        installation,
        token_status=resolve_token_status_for_install(installation),
    )


def uninstall_app_installation(
    *,
    session: Session,
    tenant_id: str,
    provider: IMProvider,
    install_mode: IMInstallMode,
) -> bool:
    installation = _get_app_installation_model(
        session=session,
        tenant_id=tenant_id,
        provider=provider,
        install_mode=install_mode,
    )
    if installation is None:
        logger.info(
            "Skipped IM app installation uninstall because no row exists",
            extra=build_human_input_log_context(
                tenant_id=tenant_id,
                provider=provider,
                extra={
                    "im_scope_type": "tenant",
                    "im_scope_id": tenant_id,
                    "im_install_mode": install_mode,
                },
            ),
        )
        return False

    installation.install_status = IMInstallStatus.UNINSTALLED
    installation.encrypted_access_token = None
    installation.encrypted_refresh_token = None
    installation.access_token_expires_at = None
    installation.token_refresh_error = None
    installation.uninstalled_at = installation.uninstalled_at or naive_utc_now()

    session.flush([installation])
    logger.info(
        "Marked IM app installation uninstalled",
        extra=build_human_input_log_context(
            tenant_id=tenant_id,
            provider=provider,
            provider_workspace_id=installation.provider_workspace_id,
            extra={
                "im_scope_type": "tenant",
                "im_scope_id": tenant_id,
                "im_install_mode": install_mode,
                "im_install_status": installation.install_status,
            },
        ),
    )
    return True


def _get_tenant_self_built_config_model(
    *,
    session: Session,
    tenant_id: str,
    provider: IMProvider,
) -> IMSelfBuiltTenantConfig | None:
    stmt = (
        select(IMSelfBuiltTenantConfig)
        .where(
            IMSelfBuiltTenantConfig.tenant_id == tenant_id,
            IMSelfBuiltTenantConfig.provider == provider,
        )
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _get_app_installation_model(
    *,
    session: Session,
    tenant_id: str,
    provider: IMProvider,
    install_mode: IMInstallMode,
) -> IMAppInstallation | None:
    stmt = (
        select(IMAppInstallation)
        .where(
            IMAppInstallation.tenant_id == tenant_id,
            IMAppInstallation.provider == provider,
            IMAppInstallation.install_mode == install_mode,
        )
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _encrypt_optional_secret(*, tenant_id: str, value: str | None) -> str | None:
    if value is None:
        return None
    return encrypter.encrypt_token(tenant_id, value)
