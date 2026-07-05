from models.contact import Contact, ContactSource, ContactStatus, ContactType
from models.enums import CreatorUserRole
from models.human_input import (
    EmailMemberRecipientPayload,
    HumanInputContactSnapshot,
    HumanInputForm,
    HumanInputFormRecipient,
    HumanInputInitiatorApprovalSnapshot,
)
from models.types import JSONModelColumn


def test_contact_snapshot_copies_durable_contact_fields() -> None:
    contact = Contact(
        tenant_id="tenant-1",
        type=ContactType.MEMBER,
        name="Approver",
        source=ContactSource.WORKSPACE_MEMBER,
        account_id="account-1",
        email="approver@example.com",
        status=ContactStatus.ACTIVE,
    )

    snapshot = HumanInputContactSnapshot.from_contact(contact)

    assert snapshot.schema_version == 1
    assert snapshot.contact_id == contact.id
    assert snapshot.tenant_id == contact.tenant_id
    assert snapshot.type == ContactType.MEMBER
    assert snapshot.source == ContactSource.WORKSPACE_MEMBER
    assert snapshot.status == ContactStatus.ACTIVE
    assert snapshot.account_id == "account-1"
    assert snapshot.email == "approver@example.com"


def test_form_recipient_new_can_store_contact_snapshot() -> None:
    snapshot = HumanInputContactSnapshot(
        contact_id="contact-1",
        tenant_id="tenant-1",
        type=ContactType.EXTERNAL,
        source=ContactSource.MANUAL_EXTERNAL,
        status=ContactStatus.ACTIVE,
        name="Vendor",
        email="vendor@example.com",
    )

    recipient = HumanInputFormRecipient.new(
        form_id="form-1",
        delivery_id="delivery-1",
        payload=EmailMemberRecipientPayload(user_id="account-1", email="member@example.com"),
        contact_snapshot=snapshot,
    )

    contact_snapshot_column = HumanInputFormRecipient.__table__.c.contact_snapshot
    assert isinstance(contact_snapshot_column.type, JSONModelColumn)
    assert contact_snapshot_column.server_default is None
    assert recipient.contact_snapshot_dict == snapshot.model_dump(mode="json")


def test_form_can_store_initiator_approval_snapshot() -> None:
    snapshot = HumanInputInitiatorApprovalSnapshot(actor_type=CreatorUserRole.END_USER, actor_id="end-user-1")
    form = HumanInputForm(
        tenant_id="tenant-1",
        app_id="app-1",
        workflow_run_id="run-1",
        conversation_id=None,
        node_id="node-1",
        form_definition="{}",
        rendered_content="{}",
        expiration_time=__import__("datetime").datetime(2026, 7, 5, 0, 0, 0),
        initiator_approval_snapshot=snapshot,
    )

    initiator_snapshot_column = HumanInputForm.__table__.c.initiator_approval_snapshot
    assert isinstance(initiator_snapshot_column.type, JSONModelColumn)
    assert initiator_snapshot_column.server_default is None
    assert form.initiator_approval_snapshot_dict == snapshot.model_dump(mode="json")
