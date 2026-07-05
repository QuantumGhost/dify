from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from models.account import Account, AccountIntegrate, TenantAccountJoin
from models.member_contact import MemberContact, MemberContactBinding


@dataclass(frozen=True)
class MemberContactImportResult:
    created_count: int
    updated_count: int


class MemberContactService:
    @staticmethod
    def _row_to_binding(row: Sequence[str | None], *, tenant_id: str) -> MemberContactBinding:
        if len(row) == 5:
            account_id, name, email, contact_id, open_id = row
            return MemberContactBinding(
                contact_id=contact_id,
                tenant_id=tenant_id,
                account_id=account_id or "",
                name=name or "",
                email=email or "",
                feishu_open_id=open_id,
            )

        if len(row) == 2:
            account_id, email = row
            return MemberContactBinding(
                contact_id=None,
                tenant_id=tenant_id,
                account_id=account_id or "",
                name="",
                email=email or "",
                feishu_open_id=None,
            )

        raise ValueError(f"unexpected workspace member binding row shape: {len(row)}")

    def import_workspace_members(self, session: Session, tenant_id: str) -> MemberContactImportResult:
        member_rows = session.execute(
            select(Account.id, Account.name, Account.email)
            .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
            .where(TenantAccountJoin.tenant_id == tenant_id)
        ).all()

        existing_contacts = {
            contact.account_id: contact
            for contact in session.scalars(select(MemberContact).where(MemberContact.tenant_id == tenant_id)).all()
        }

        created_count = 0
        updated_count = 0
        for account_id, name, email in member_rows:
            existing_contact = existing_contacts.get(account_id)
            if existing_contact is None:
                session.add(
                    MemberContact(
                        tenant_id=tenant_id,
                        account_id=account_id,
                        source="workspace_member",
                        name=name or "",
                        email=email or "",
                    )
                )
                created_count += 1
                continue

            if existing_contact.name == (name or "") and existing_contact.email == (email or ""):
                continue

            existing_contact.name = name or ""
            existing_contact.email = email or ""
            updated_count += 1

        session.commit()
        return MemberContactImportResult(created_count=created_count, updated_count=updated_count)

    def import_all_workspace_members(self, session: Session) -> MemberContactImportResult:
        tenant_rows = session.execute(select(TenantAccountJoin.tenant_id).distinct()).all()
        created_count = 0
        updated_count = 0

        for (tenant_id,) in tenant_rows:
            if not tenant_id:
                continue
            result = self.import_workspace_members(session, tenant_id)
            created_count += result.created_count
            updated_count += result.updated_count

        return MemberContactImportResult(created_count=created_count, updated_count=updated_count)

    def list_workspace_member_bindings(
        self,
        session: Session,
        *,
        tenant_id: str,
        account_ids: Sequence[str] | None = None,
    ) -> list[MemberContactBinding]:
        stmt = (
            select(
                Account.id,
                Account.name,
                Account.email,
                MemberContact.id,
                AccountIntegrate.open_id,
            )
            .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
            .outerjoin(
                MemberContact,
                and_(
                    MemberContact.tenant_id == TenantAccountJoin.tenant_id,
                    MemberContact.account_id == Account.id,
                ),
            )
            .outerjoin(
                AccountIntegrate,
                and_(
                    AccountIntegrate.account_id == Account.id,
                    AccountIntegrate.provider == "feishu_im",
                ),
            )
            .where(TenantAccountJoin.tenant_id == tenant_id)
        )

        if account_ids is not None:
            unique_account_ids = {account_id for account_id in account_ids if account_id}
            if not unique_account_ids:
                return []
            stmt = stmt.where(Account.id.in_(unique_account_ids))

        rows = session.execute(stmt).all()
        return [self._row_to_binding(row, tenant_id=tenant_id) for row in rows]

    def resolve_workspace_member_binding(
        self,
        session: Session,
        *,
        tenant_id: str,
        account_id: str,
    ) -> MemberContactBinding | None:
        bindings = self.list_workspace_member_bindings(session, tenant_id=tenant_id, account_ids=[account_id])
        if not bindings:
            return None
        return bindings[0]
