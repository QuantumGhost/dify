from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.repositories.account_im_binding_repository import (
    AccountIMBindingSnapshot,
    list_account_im_bindings_by_account_ids,
)
from models.account import AccountIMBinding
from services.errors.account import AccountIMBindingConflictError


class AccountIMBindingService:
    @staticmethod
    def upsert_binding(
        *,
        session: Session,
        tenant_id: str,
        account_id: str,
        provider: str,
        open_id: str | None,
        user_id: str | None,
    ) -> AccountIMBinding:
        normalized_open_id, normalized_user_id = _normalize_im_identity(open_id=open_id, user_id=user_id)
        binding = session.scalar(
            select(AccountIMBinding)
            .where(
                AccountIMBinding.tenant_id == tenant_id,
                AccountIMBinding.account_id == account_id,
                AccountIMBinding.provider == provider,
            )
            .limit(1)
        )

        if binding is None:
            binding = AccountIMBinding(
                tenant_id=tenant_id,
                account_id=account_id,
                provider=provider,
                open_id=normalized_open_id,
                user_id=normalized_user_id,
            )
            session.add(binding)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise AccountIMBindingConflictError("IM identity is already bound to another account.") from exc
            return binding

        binding.open_id = normalized_open_id
        binding.user_id = normalized_user_id
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise AccountIMBindingConflictError("IM identity is already bound to another account.") from exc
        return binding

    @staticmethod
    def list_bindings_by_account_ids(
        *,
        session: Session,
        tenant_id: str,
        account_ids,
        provider: str,
    ) -> list[AccountIMBindingSnapshot]:
        return list_account_im_bindings_by_account_ids(
            session=session,
            tenant_id=tenant_id,
            account_ids=account_ids,
            provider=provider,
        )


def _normalize_im_identity(*, open_id: str | None, user_id: str | None) -> tuple[str | None, str | None]:
    normalized_open_id = open_id.strip() if open_id is not None else None
    normalized_user_id = user_id.strip() if user_id is not None else None
    normalized_open_id = normalized_open_id or None
    normalized_user_id = normalized_user_id or None
    if normalized_open_id is None and normalized_user_id is None:
        raise ValueError("open_id or user_id is required")
    return normalized_open_id, normalized_user_id
