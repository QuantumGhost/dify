from pydantic import BaseModel, ConfigDict

from models.contact import Contact, ContactSource, ContactStatus, ContactType
from models.im_integration import IMProvider


class ContactDeliveryStatus(str):
    IM = "im"
    EMAIL = "email"
    NONE = "none"


class ContactRecord(BaseModel):
    """Storage-agnostic authoritative Contact row contract."""

    id: str
    tenant_id: str
    type: ContactType
    status: ContactStatus
    source: ContactSource
    account_id: str | None = None
    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_contact(cls, contact: Contact) -> "ContactRecord":
        return cls(
            id=contact.id,
            tenant_id=contact.tenant_id,
            type=contact.type,
            status=contact.status,
            source=contact.source,
            account_id=contact.account_id,
        )


class ResolvedContact(BaseModel):
    """Contact read model with profile fields resolved by contact type."""

    id: str
    tenant_id: str
    type: ContactType
    status: ContactStatus
    source: ContactSource
    account_id: str | None = None
    name: str
    email: str | None = None
    delivery_status: str
    delivery_provider: IMProvider | None = None

    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_external_contact(
        cls,
        contact: Contact,
    ) -> "ResolvedContact":
        return cls(
            id=contact.id,
            tenant_id=contact.tenant_id,
            type=contact.type,
            status=contact.status,
            source=contact.source,
            account_id=None,
            name=contact.name,
            email=contact.email,
            delivery_status=ContactDeliveryStatus.EMAIL if contact.email else ContactDeliveryStatus.NONE,
            delivery_provider=None,
        )

    @classmethod
    def from_member_contact(
        cls,
        *,
        contact: ContactRecord,
        account_name: str,
        account_email: str | None,
        delivery_status: str,
        delivery_provider: IMProvider | None,
    ) -> "ResolvedContact":
        return cls(
            id=contact.id,
            tenant_id=contact.tenant_id,
            type=contact.type,
            status=contact.status,
            source=contact.source,
            account_id=contact.account_id,
            name=account_name,
            email=account_email,
            delivery_status=delivery_status,
            delivery_provider=delivery_provider,
        )
