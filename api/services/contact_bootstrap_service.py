"""Bootstrap helpers for backfilling authoritative member Contact rows.

These helpers read the current workspace membership and create missing member
Contact rows for setup/demo flows. They are not runtime projection, sync, or
reactivation paths.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.account import Account, TenantAccountJoin
from services.contact_service import ensure_member_contact
from services.entities.contact_entities import ContactRecord

logger = logging.getLogger(__name__)


def seed_member_contacts(
    *,
    session: Session,
    tenant_id: str,
    account_ids: Sequence[str] | None = None,
) -> list[ContactRecord]:
    """Backfill missing member Contacts for current workspace members."""

    if account_ids is not None and not account_ids:
        logger.info(
            "Skipped workspace Contact seed because the explicit account scope is empty",
            extra={"tenant_id": tenant_id, "requested_account_count": 0},
        )
        return []

    logger.info(
        "Starting workspace Contact seed",
        extra={
            "tenant_id": tenant_id,
            "requested_account_count": len(account_ids) if account_ids is not None else None,
        },
    )

    membership_stmt = (
        select(Account.id, Account.name, Account.email)
        .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
        .where(TenantAccountJoin.tenant_id == tenant_id)
        .order_by(Account.id)
    )
    if account_ids is not None:
        membership_stmt = membership_stmt.where(Account.id.in_(list(account_ids)))

    members = session.execute(membership_stmt).all()
    if not members:
        logger.warning(
            "Workspace Contact seed found no matching members",
            extra={
                "tenant_id": tenant_id,
                "requested_account_count": len(account_ids) if account_ids is not None else None,
            },
        )
        return []

    contacts: list[ContactRecord] = []
    for member in members:
        contacts.append(
            ensure_member_contact(
                session=session,
                tenant_id=tenant_id,
                account_id=member.id,
                name=member.name,
                email=member.email,
            )
        )

    logger.info(
        "Completed workspace Contact seed",
        extra={
            "tenant_id": tenant_id,
            "resolved_member_count": len(members),
            "resolved_contact_count": len(contacts),
            "member_account_ids": [member.id for member in members],
            "contact_ids": [contact.id for contact in contacts],
        },
    )
    return contacts
