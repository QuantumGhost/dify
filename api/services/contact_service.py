"""Workspace-scoped Contact aggregate helpers for phase-1 foundations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from libs.helper import email as email_validate
from models.contact import Contact, ContactSource, ContactStatus, ContactType
from services.entities.contact_entities import ContactRecord
from services.errors.contact import ContactValidationError


def list_contact_records(
    *,
    session: Session,
    tenant_id: str,
    contact_type: ContactType | None = None,
    include_disabled: bool = True,
) -> list[ContactRecord]:
    """List authoritative Contact rows for the requested tenant."""

    stmt = select(Contact).where(Contact.tenant_id == tenant_id).order_by(Contact.created_at, Contact.id)
    if contact_type is not None:
        stmt = stmt.where(Contact.type == contact_type)
    if not include_disabled:
        stmt = stmt.where(Contact.status == ContactStatus.ACTIVE)
    contacts = list(session.scalars(stmt).all())
    return [ContactRecord.from_contact(contact) for contact in contacts]


def create_external_contact(
    *,
    session: Session,
    tenant_id: str,
    name: str,
    email: str,
) -> ContactRecord:
    """Create an explicit external Contact for a workspace."""

    normalized_name = name.strip()
    if not normalized_name:
        raise ContactValidationError("external contacts must define a non-empty name")
    normalized_email = email_validate(email.strip().lower())

    contact = Contact(
        tenant_id=tenant_id,
        type=ContactType.EXTERNAL,
        account_id=None,
        name=normalized_name,
        email=normalized_email,
        status=ContactStatus.ACTIVE,
        source=ContactSource.MANUAL_EXTERNAL,
    )
    session.add(contact)
    return ContactRecord.from_contact(contact)


def ensure_member_contact(
    *,
    session: Session,
    tenant_id: str,
    account_id: str,
    name: str,
    email: str | None,
) -> ContactRecord:
    """Get or create the authoritative member Contact row for one workspace member."""

    existing_contact = session.scalar(
        select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.type == ContactType.MEMBER,
            Contact.account_id == account_id,
        )
    )
    if existing_contact is not None:
        return ContactRecord.from_contact(existing_contact)

    contact = Contact(
        tenant_id=tenant_id,
        type=ContactType.MEMBER,
        account_id=account_id,
        name=name,
        email=email,
        status=ContactStatus.ACTIVE,
        source=ContactSource.WORKSPACE_MEMBER,
    )
    try:
        _insert_member_contact(session=session, contact=contact)
    except IntegrityError as exc:
        if not _is_duplicate_member_contact_error(exc):
            raise
        existing_contact = session.scalar(
            select(Contact).where(
                Contact.tenant_id == tenant_id,
                Contact.type == ContactType.MEMBER,
                Contact.account_id == account_id,
            )
        )
        if existing_contact is None:
            raise
        return ContactRecord.from_contact(existing_contact)

    return ContactRecord.from_contact(contact)


def _insert_member_contact(*, session: Session, contact: Contact) -> None:
    """Persist one member Contact with savepoint-backed conflict recovery."""

    with session.begin_nested():
        session.add(contact)
        session.flush([contact])


def _is_duplicate_member_contact_error(exc: IntegrityError) -> bool:
    """Return whether an IntegrityError came from the member Contact unique key."""

    message = str(getattr(exc, "orig", exc)).lower()
    return "contacts_tenant_type_account_id_key" in message or (
        "unique constraint failed" in message
        and "contacts.tenant_id" in message
        and "contacts.type" in message
        and "contacts.account_id" in message
    )
