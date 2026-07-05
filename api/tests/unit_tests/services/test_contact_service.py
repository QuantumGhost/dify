from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.account import Account, TenantAccountJoin
from models.base import TypeBase
from models.contact import Contact, ContactInvariantError, ContactSource, ContactStatus, ContactType
from models.im_integration import IMBinding, IMBindingStatus, IMInstallMode, IMProvider, IMScopeType
from services.contact_bootstrap_service import seed_member_contacts
from services.contact_resolution_service import resolve_contact_records
from services.contact_service import create_external_contact, ensure_member_contact, list_contact_records


def test_seed_member_contacts_is_idempotent() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(
        engine,
        tables=[Account.__table__, TenantAccountJoin.__table__, Contact.__table__],
    )

    account_1 = Account(name="Alpha", email="alpha@example.com")
    account_1.id = "account-1"
    account_2 = Account(name="Beta", email="beta@example.com")
    account_2.id = "account-2"
    join_1 = TenantAccountJoin(tenant_id="tenant-1", account_id="account-1")
    join_1.id = "join-1"
    join_2 = TenantAccountJoin(tenant_id="tenant-1", account_id="account-2")
    join_2.id = "join-2"

    with Session(engine) as session:
        session.add_all(
            [
                account_1,
                account_2,
                join_1,
                join_2,
            ]
        )
        session.commit()

        first_contacts = seed_member_contacts(session=session, tenant_id="tenant-1")
        session.commit()

        second_contacts = seed_member_contacts(session=session, tenant_id="tenant-1")
        session.commit()

        stored_contacts = session.scalars(select(Contact).order_by(Contact.account_id)).all()

    assert len(first_contacts) == 2
    assert len(second_contacts) == 2
    assert len(stored_contacts) == 2
    assert [contact.account_id for contact in first_contacts] == ["account-1", "account-2"]
    assert [contact.account_id for contact in stored_contacts] == ["account-1", "account-2"]
    assert all(contact.type == ContactType.MEMBER for contact in stored_contacts)
    assert all(contact.status == ContactStatus.ACTIVE for contact in stored_contacts)
    assert all(contact.source == ContactSource.WORKSPACE_MEMBER for contact in stored_contacts)


def test_create_external_contact_uses_fixed_phase_1_shape() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[Contact.__table__])

    with Session(engine) as session:
        contact = create_external_contact(
            session=session,
            tenant_id="tenant-1",
            name="Vendor",
            email="vendor@example.com",
        )
        session.commit()
        stored_contact = session.scalar(select(Contact).where(Contact.id == contact.id))

    assert stored_contact is not None
    assert contact.type == ContactType.EXTERNAL
    assert contact.account_id is None
    assert contact.source == ContactSource.MANUAL_EXTERNAL
    assert contact.status == ContactStatus.ACTIVE
    assert stored_contact.type == ContactType.EXTERNAL
    assert stored_contact.email == "vendor@example.com"


def test_create_external_contact_normalizes_name_and_email() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[Contact.__table__])

    with Session(engine) as session:
        contact = create_external_contact(
            session=session,
            tenant_id="tenant-1",
            name="  Vendor  ",
            email="  Vendor@Example.COM ",
        )
        session.commit()
        stored_contact = session.scalar(select(Contact).where(Contact.id == contact.id))

    assert stored_contact is not None
    assert stored_contact.name == "Vendor"
    assert stored_contact.email == "vendor@example.com"


def test_contact_rejects_invalid_phase_1_shapes() -> None:
    with pytest.raises(ContactInvariantError):
        Contact(
            tenant_id="tenant-1",
            type=ContactType.MEMBER,
            account_id=None,
            name="Member",
            email="member@example.com",
            status=ContactStatus.ACTIVE,
            source=ContactSource.WORKSPACE_MEMBER,
        )

    with pytest.raises(ContactInvariantError):
        Contact(
            tenant_id="tenant-1",
            type=ContactType.EXTERNAL,
            account_id=None,
            name="External",
            email="   ",
            status=ContactStatus.ACTIVE,
            source=ContactSource.MANUAL_EXTERNAL,
        )

    with pytest.raises(ContactInvariantError):
        Contact(
            tenant_id="tenant-1",
            type=ContactType.EXTERNAL,
            account_id="account-1",
            name="External",
            email="external@example.com",
            status=ContactStatus.ACTIVE,
            source=ContactSource.MANUAL_EXTERNAL,
        )


def test_seed_member_contacts_reuses_existing_disabled_member_contact() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(
        engine,
        tables=[Account.__table__, TenantAccountJoin.__table__, Contact.__table__],
    )

    account = Account(name="Alpha", email="alpha@example.com")
    account.id = "account-1"
    membership = TenantAccountJoin(tenant_id="tenant-1", account_id="account-1")
    membership.id = "join-1"
    disabled_contact = Contact(
        tenant_id="tenant-1",
        type=ContactType.MEMBER,
        account_id="account-1",
        name="Alpha",
        email="alpha@example.com",
        status=ContactStatus.DISABLED,
        source=ContactSource.WORKSPACE_MEMBER,
    )

    with Session(engine) as session:
        session.add_all([account, membership, disabled_contact])
        session.commit()

        seeded_contacts = seed_member_contacts(session=session, tenant_id="tenant-1")
        session.commit()
        stored_contacts = session.scalars(select(Contact).where(Contact.tenant_id == "tenant-1")).all()

    assert len(seeded_contacts) == 1
    assert seeded_contacts[0].id == disabled_contact.id
    assert seeded_contacts[0].account_id == "account-1"
    assert len(stored_contacts) == 1
    assert stored_contacts[0].status == ContactStatus.DISABLED


def test_list_contact_records_filters_type_and_disabled_rows() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[Account.__table__, Contact.__table__])

    member_account = Account(name="Alpha", email="alpha@example.com")
    member_account.id = "account-1"

    active_member = Contact(
        tenant_id="tenant-1",
        type=ContactType.MEMBER,
        account_id="account-1",
        name="Alpha",
        email="alpha@example.com",
        status=ContactStatus.ACTIVE,
        source=ContactSource.WORKSPACE_MEMBER,
    )
    disabled_external = Contact(
        tenant_id="tenant-1",
        type=ContactType.EXTERNAL,
        account_id=None,
        name="Vendor",
        email="vendor@example.com",
        status=ContactStatus.DISABLED,
        source=ContactSource.MANUAL_EXTERNAL,
    )
    other_tenant_contact = Contact(
        tenant_id="tenant-2",
        type=ContactType.EXTERNAL,
        account_id=None,
        name="Other",
        email="other@example.com",
        status=ContactStatus.ACTIVE,
        source=ContactSource.MANUAL_EXTERNAL,
    )

    with Session(engine) as session:
        session.add_all([member_account, active_member, disabled_external, other_tenant_contact])
        session.commit()

        active_contacts = list_contact_records(session=session, tenant_id="tenant-1", include_disabled=False)
        external_contacts = list_contact_records(
            session=session,
            tenant_id="tenant-1",
            contact_type=ContactType.EXTERNAL,
        )

    assert [contact.id for contact in active_contacts] == [active_member.id]
    assert [contact.id for contact in external_contacts] == [disabled_external.id]


def test_list_contacts_prefers_current_account_profile_for_member_contact() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[Account.__table__, Contact.__table__, IMBinding.__table__])

    member_account = Account(name="Current Name", email="current@example.com")
    member_account.id = "account-1"
    member_contact = Contact(
        tenant_id="tenant-1",
        type=ContactType.MEMBER,
        account_id="account-1",
        name="Seeded Name",
        email="seeded@example.com",
        status=ContactStatus.ACTIVE,
        source=ContactSource.WORKSPACE_MEMBER,
    )

    with Session(engine) as session:
        session.add_all([member_account, member_contact])
        session.commit()
        contact_records = list_contact_records(session=session, tenant_id="tenant-1")
        contacts = resolve_contact_records(session=session, contacts=contact_records)

    assert [contact.name for contact in contacts] == ["Current Name"]
    assert [contact.email for contact in contacts] == ["current@example.com"]
    assert [contact.delivery_status for contact in contacts] == ["email"]


def test_list_contacts_falls_back_to_contact_row_when_member_account_missing() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[Contact.__table__])

    member_contact = Contact(
        tenant_id="tenant-1",
        type=ContactType.MEMBER,
        account_id="account-1",
        name="Seeded Name",
        email="seeded@example.com",
        status=ContactStatus.ACTIVE,
        source=ContactSource.WORKSPACE_MEMBER,
    )

    with Session(engine) as session:
        session.add(member_contact)
        session.commit()
        contact_records = list_contact_records(session=session, tenant_id="tenant-1")
        contacts = resolve_contact_records(session=session, contacts=contact_records)

    assert [contact.name for contact in contacts] == ["Seeded Name"]
    assert [contact.email for contact in contacts] == ["seeded@example.com"]
    assert [contact.delivery_status for contact in contacts] == ["email"]


def test_list_contacts_marks_member_contact_as_im_when_active_binding_exists() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[Account.__table__, Contact.__table__, IMBinding.__table__])

    member_account = Account(name="Current Name", email="current@example.com")
    member_account.id = "account-1"
    member_contact = Contact(
        tenant_id="tenant-1",
        type=ContactType.MEMBER,
        account_id="account-1",
        name="Seeded Name",
        email="seeded@example.com",
        status=ContactStatus.ACTIVE,
        source=ContactSource.WORKSPACE_MEMBER,
    )
    active_binding = IMBinding(
        account_id="account-1",
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        provider_workspace_id="ws-1",
        provider_user_id="user-1",
        status=IMBindingStatus.ACTIVE,
    )

    with Session(engine) as session:
        session.add_all([member_account, member_contact, active_binding])
        session.commit()
        contact_records = list_contact_records(session=session, tenant_id="tenant-1")
        contacts = resolve_contact_records(session=session, contacts=contact_records)

    assert [contact.delivery_status for contact in contacts] == ["im"]
    assert [contact.delivery_provider for contact in contacts] == [IMProvider.FEISHU]


def test_list_contacts_marks_member_contact_as_none_when_email_and_binding_are_missing() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[Contact.__table__, IMBinding.__table__])

    member_contact = Contact(
        tenant_id="tenant-1",
        type=ContactType.MEMBER,
        account_id="account-1",
        name="Seeded Name",
        email=None,
        status=ContactStatus.ACTIVE,
        source=ContactSource.WORKSPACE_MEMBER,
    )

    with Session(engine) as session:
        session.add(member_contact)
        session.commit()
        contact_records = list_contact_records(session=session, tenant_id="tenant-1")
        contacts = resolve_contact_records(session=session, contacts=contact_records)

    assert [contact.delivery_status for contact in contacts] == ["none"]
    assert [contact.delivery_provider for contact in contacts] == [None]


def test_ensure_member_contact_returns_existing_authoritative_row() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[Contact.__table__])

    existing_contact = Contact(
        tenant_id="tenant-1",
        type=ContactType.MEMBER,
        account_id="account-1",
        name="Seeded Name",
        email="seeded@example.com",
        status=ContactStatus.DISABLED,
        source=ContactSource.WORKSPACE_MEMBER,
    )

    with Session(engine) as session:
        session.add(existing_contact)
        session.commit()
        contact = ensure_member_contact(
            session=session,
            tenant_id="tenant-1",
            account_id="account-1",
            name="Current Name",
            email="current@example.com",
        )

    assert contact.id == existing_contact.id
