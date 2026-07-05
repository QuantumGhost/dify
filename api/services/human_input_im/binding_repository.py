"""Persistence helpers for IM binding/session lookups.

The phase-1 binding service keeps write orchestration in ``binding_service``,
but the uniqueness-sensitive lookups live here so tests can exercise the
underlying persistence rules directly. These helpers intentionally return ORM
models because callers still own the surrounding transaction and state changes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.im_integration import (
    IMBinding,
    IMBindingSession,
    IMBindingSessionStatus,
    IMBindingStatus,
    IMInstallMode,
    IMProvider,
    IMScopeType,
)
from services.errors.im_binding import IMBindingValidationError


def get_active_binding_model(*, session: Session, account_id: str) -> IMBinding | None:
    """Return the only active binding for one account.

    Phase-1 only supports one active IM binding per account. If persistence
    ever violates that invariant, raise immediately instead of letting service
    code continue with ambiguous state.
    """

    bindings = session.scalars(
        select(IMBinding).where(
            IMBinding.account_id == account_id,
            IMBinding.status == IMBindingStatus.ACTIVE,
        )
    ).all()
    if not bindings:
        return None
    if len(bindings) > 1:
        raise IMBindingValidationError("phase-1 supports at most one active IM binding per account")
    return bindings[0]


def get_pending_binding_session(*, session: Session, token: str) -> IMBindingSession | None:
    """Return a pending binding session by token."""

    return session.scalar(
        select(IMBindingSession).where(
            IMBindingSession.token == token,
            IMBindingSession.status == IMBindingSessionStatus.PENDING,
        )
    )


def get_binding_by_provider_identity(
    *,
    session: Session,
    provider: IMProvider,
    install_mode: IMInstallMode,
    scope_type: IMScopeType,
    scope_id: str,
    provider_workspace_id: str,
    provider_user_id: str,
) -> IMBinding | None:
    """Return the unique binding row for one provider identity inside one scope.

    The query intentionally ignores binding status so revoked rows can be reused
    during rebind flows instead of creating duplicate records for the same
    provider identity.
    """

    bindings = session.scalars(
        select(IMBinding).where(
            IMBinding.provider == provider,
            IMBinding.install_mode == install_mode,
            IMBinding.scope_type == scope_type,
            IMBinding.scope_id == scope_id,
            IMBinding.provider_workspace_id == provider_workspace_id,
            IMBinding.provider_user_id == provider_user_id,
        )
    ).all()
    if not bindings:
        return None
    if len(bindings) > 1:
        raise IMBindingValidationError("phase-1 expects at most one IM binding per provider identity scope")
    return bindings[0]
