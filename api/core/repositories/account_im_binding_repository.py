from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.account import AccountIMBinding


@dataclass(frozen=True)
class AccountIMBindingSnapshot:
    binding_id: str
    tenant_id: str
    account_id: str
    provider: str
    open_id: str | None
    user_id: str | None


def list_account_im_bindings_by_account_ids(
    *,
    session: Session,
    tenant_id: str,
    account_ids: Sequence[str],
    provider: str,
) -> list[AccountIMBindingSnapshot]:
    unique_account_ids = [account_id for account_id in dict.fromkeys(account_ids) if account_id]
    if not unique_account_ids:
        return []

    bindings = session.scalars(
        select(AccountIMBinding).where(
            AccountIMBinding.tenant_id == tenant_id,
            AccountIMBinding.provider == provider,
            AccountIMBinding.account_id.in_(unique_account_ids),
        )
    ).all()
    return [_to_snapshot(binding) for binding in bindings]


def get_account_im_binding_by_id(
    *,
    session: Session,
    binding_id: str,
) -> AccountIMBindingSnapshot | None:
    binding = session.scalar(select(AccountIMBinding).where(AccountIMBinding.id == binding_id).limit(1))
    if binding is None:
        return None
    return _to_snapshot(binding)


def _to_snapshot(binding: AccountIMBinding) -> AccountIMBindingSnapshot:
    return AccountIMBindingSnapshot(
        binding_id=binding.id,
        tenant_id=binding.tenant_id,
        account_id=binding.account_id,
        provider=binding.provider,
        open_id=binding.open_id,
        user_id=binding.user_id,
    )
