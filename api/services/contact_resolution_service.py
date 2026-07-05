"""Read-model helpers for resolving Contact profiles by contact type."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from models.account import Account
from models.contact import Contact
from services.entities.contact_entities import ContactRecord, ResolvedContact


def resolve_contact_records(
    *,
    session: Session,
    contacts: list[ContactRecord],
) -> list[ResolvedContact]:
    if not contacts:
        return []

    member_account_ids = sorted({contact.account_id for contact in contacts if contact.account_id is not None})
    member_profiles: dict[str, tuple[str, str | None]] = {}
    if member_account_ids:
        profile_stmt = select(Account.id, Account.name, Account.email).where(Account.id.in_(member_account_ids))
        try:
            member_profiles = {
                row.id: (row.name, row.email)
                for row in session.execute(profile_stmt).all()
            }
        except OperationalError:
            member_profiles = {}

    records: list[ResolvedContact] = []
    for contact in contacts:
        contact_model = session.get(Contact, contact.id)
        if contact_model is None:
            msg = f"contact row not found, contact_id={contact.id}"
            raise AssertionError(msg)

        if contact.account_id is None:
            records.append(ResolvedContact.from_external_contact(contact_model))
            continue

        account_name = contact_model.name
        account_email = contact_model.email
        account_profile = member_profiles.get(contact.account_id)
        if account_profile is not None:
            account_name, account_email = account_profile

        records.append(
            ResolvedContact.from_member_contact(
                contact=contact,
                account_name=account_name,
                account_email=account_email,
            )
        )

    return records
