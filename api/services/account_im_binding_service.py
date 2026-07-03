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
                open_id=open_id,
                user_id=user_id,
            )
            session.add(binding)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise AccountIMBindingConflictError("IM identity is already bound to another account.") from exc
            return binding

        binding.open_id = open_id
        binding.user_id = user_id
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
