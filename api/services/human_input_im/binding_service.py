"""IM binding use cases for phase-1 HITL foundations.

This module owns current-account binding inspection, revoke, and binding session
creation. Provider-authenticated binding completion remains a later step and
should prefer official SDKs when provider-specific support is required.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from libs.datetime_utils import naive_utc_now
from models.im_integration import IMBinding, IMBindingSession, IMBindingStatus, IMBindingSessionStatus
from services.entities.im_binding_entities import IMBindingRecord, IMBindingSessionRecord
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.app_config_service import IMAppConfigStatus, IMAppContext
from services.human_input_im.binding_repository import (
    get_active_binding_model,
    get_binding_by_provider_identity,
    get_pending_binding_session,
)
from services.human_input_observability import build_human_input_log_context

logger = logging.getLogger(__name__)


def get_active_binding(*, session: Session, account_id: str) -> IMBindingRecord | None:
    binding = get_active_binding_model(session=session, account_id=account_id)
    if binding is None:
        return None
    return IMBindingRecord.model_validate(binding, from_attributes=True)


def revoke_active_binding(*, session: Session, account_id: str) -> IMBindingRecord | None:
    binding = get_active_binding_model(session=session, account_id=account_id)
    if binding is None:
        logger.info(
            "Skipped IM binding revoke because no active binding exists",
            extra={"binding_account_id": account_id},
        )
        return None
    binding.status = IMBindingStatus.REVOKED
    session.flush([binding])
    binding_record = IMBindingRecord.model_validate(binding, from_attributes=True)
    logger.info(
        "Revoked active IM binding",
        extra=build_human_input_log_context(binding=binding_record),
    )
    return binding_record


def create_binding_session(
    *,
    session: Session,
    account_id: str,
    app_context: IMAppContext,
    expires_in: timedelta = timedelta(minutes=10),
) -> IMBindingSessionRecord:
    if app_context.status != IMAppConfigStatus.CONFIGURED:
        logger.warning(
            "Rejected IM binding session creation because the app context is not configured",
            extra=build_human_input_log_context(
                provider=app_context.provider,
                extra={
                    "binding_account_id": account_id,
                    "binding_scope_type": app_context.scope_type,
                    "binding_scope_id": app_context.scope_id,
                    "app_context_status": app_context.status,
                },
            ),
        )
        raise IMBindingValidationError("cannot create binding session without a configured IM app context")
    if get_active_binding_model(session=session, account_id=account_id) is not None:
        logger.warning(
            "Rejected IM binding session creation because the account already has an active binding",
            extra=build_human_input_log_context(
                provider=app_context.provider,
                extra={
                    "binding_account_id": account_id,
                    "binding_scope_type": app_context.scope_type,
                    "binding_scope_id": app_context.scope_id,
                },
            ),
        )
        raise IMBindingValidationError("account already has an active IM binding")

    session_model = IMBindingSession(
        account_id=account_id,
        provider=app_context.provider,
        install_mode=app_context.install_mode,
        scope_type=app_context.scope_type,
        scope_id=app_context.scope_id,
        status=IMBindingSessionStatus.PENDING,
        expires_at=naive_utc_now() + expires_in,
    )
    session.add(session_model)
    session.flush([session_model])
    session_record = IMBindingSessionRecord.model_validate(session_model, from_attributes=True)
    logger.info(
        "Created IM binding session",
        extra=build_human_input_log_context(
            provider=app_context.provider,
            extra={
                "binding_account_id": account_id,
                "binding_session_id": session_record.id,
                "binding_session_status": session_record.status,
                "binding_scope_type": session_record.scope_type,
                "binding_scope_id": session_record.scope_id,
                "binding_install_mode": session_record.install_mode,
                "binding_session_expires_at": session_record.expires_at.isoformat(),
            },
        ),
    )
    return session_record


def complete_binding_session(
    *,
    session: Session,
    token: str,
    provider_workspace_id: str,
    provider_user_id: str,
    provider_union_id: str | None = None,
    provider_user_display_name: str | None = None,
    provider_user_avatar_url: str | None = None,
) -> IMBindingRecord:
    binding_session = get_pending_binding_session(session=session, token=token)
    if binding_session is None:
        logger.warning("Rejected IM binding completion because the session is not pending")
        raise IMBindingValidationError("binding session is not pending")
    if binding_session.expires_at <= naive_utc_now():
        binding_session.status = IMBindingSessionStatus.EXPIRED
        session.flush([binding_session])
        logger.warning(
            "Rejected IM binding completion because the binding session expired",
            extra=build_human_input_log_context(
                provider=binding_session.provider,
                extra={
                    "binding_account_id": binding_session.account_id,
                    "binding_session_id": binding_session.id,
                    "binding_scope_type": binding_session.scope_type,
                    "binding_scope_id": binding_session.scope_id,
                    "binding_install_mode": binding_session.install_mode,
                },
            ),
        )
        raise IMBindingValidationError("binding session expired")

    identity_binding = get_binding_by_provider_identity(
        session=session,
        provider=binding_session.provider,
        install_mode=binding_session.install_mode,
        scope_type=binding_session.scope_type,
        scope_id=binding_session.scope_id,
        provider_workspace_id=provider_workspace_id,
        provider_user_id=provider_user_id,
    )
    existing_binding = get_active_binding_model(session=session, account_id=binding_session.account_id)
    if existing_binding is not None and (
        existing_binding.provider != binding_session.provider
        or existing_binding.install_mode != binding_session.install_mode
        or existing_binding.scope_type != binding_session.scope_type
        or existing_binding.scope_id != binding_session.scope_id
        or existing_binding.provider_workspace_id != provider_workspace_id
        or existing_binding.provider_user_id != provider_user_id
    ):
        logger.warning(
            "Rejected IM binding completion because the account already owns a different active binding",
            extra=build_human_input_log_context(
                provider=binding_session.provider,
                provider_workspace_id=provider_workspace_id,
                provider_user_id=provider_user_id,
                extra={
                    "binding_account_id": binding_session.account_id,
                    "binding_session_id": binding_session.id,
                    "binding_scope_type": binding_session.scope_type,
                    "binding_scope_id": binding_session.scope_id,
                    "binding_install_mode": binding_session.install_mode,
                },
            ),
        )
        raise IMBindingValidationError("phase-1 supports at most one active IM binding per account")

    if identity_binding is not None:
        existing_binding = identity_binding
    else:
        if existing_binding is None:
            existing_binding = IMBinding(
                account_id=binding_session.account_id,
                provider=binding_session.provider,
                install_mode=binding_session.install_mode,
                scope_type=binding_session.scope_type,
                scope_id=binding_session.scope_id,
                provider_workspace_id=provider_workspace_id,
                provider_user_id=provider_user_id,
                provider_union_id=provider_union_id,
                provider_user_display_name=provider_user_display_name,
                provider_user_avatar_url=provider_user_avatar_url,
                status=IMBindingStatus.ACTIVE,
            )
            session.add(existing_binding)

    existing_binding.account_id = binding_session.account_id
    existing_binding.status = IMBindingStatus.ACTIVE
    existing_binding.provider_workspace_id = provider_workspace_id
    existing_binding.provider_user_id = provider_user_id
    existing_binding.provider_union_id = provider_union_id
    existing_binding.provider_user_display_name = provider_user_display_name
    existing_binding.provider_user_avatar_url = provider_user_avatar_url

    binding_session.status = IMBindingSessionStatus.CONSUMED
    session.flush([binding_session, existing_binding])
    binding_record = IMBindingRecord.model_validate(existing_binding, from_attributes=True)
    logger.info(
        "Completed IM binding session",
        extra=build_human_input_log_context(
            binding=binding_record,
            extra={
                "binding_session_id": binding_session.id,
                "binding_session_status": binding_session.status,
                "binding_install_mode": binding_session.install_mode,
            },
        ),
    )
    return binding_record
