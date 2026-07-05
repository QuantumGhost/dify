"""IM binding use cases for phase-1 HITL foundations.

This module owns current-account binding inspection, revoke, and binding session
creation. Provider-authenticated binding completion remains a later step and
should prefer official SDKs when provider-specific support is required.
"""

from __future__ import annotations

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


def get_active_binding(*, session: Session, account_id: str) -> IMBindingRecord | None:
    binding = get_active_binding_model(session=session, account_id=account_id)
    if binding is None:
        return None
    return IMBindingRecord.model_validate(binding, from_attributes=True)


def revoke_active_binding(*, session: Session, account_id: str) -> IMBindingRecord | None:
    binding = get_active_binding_model(session=session, account_id=account_id)
    if binding is None:
        return None
    binding.status = IMBindingStatus.REVOKED
    session.flush([binding])
    return IMBindingRecord.model_validate(binding, from_attributes=True)


def create_binding_session(
    *,
    session: Session,
    account_id: str,
    app_context: IMAppContext,
    expires_in: timedelta = timedelta(minutes=10),
) -> IMBindingSessionRecord:
    if app_context.status != IMAppConfigStatus.CONFIGURED:
        raise IMBindingValidationError("cannot create binding session without a configured IM app context")
    if get_active_binding_model(session=session, account_id=account_id) is not None:
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
    return IMBindingSessionRecord.model_validate(session_model, from_attributes=True)


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
        raise IMBindingValidationError("binding session is not pending")
    if binding_session.expires_at <= naive_utc_now():
        binding_session.status = IMBindingSessionStatus.EXPIRED
        session.flush([binding_session])
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
    return IMBindingRecord.model_validate(existing_binding, from_attributes=True)
