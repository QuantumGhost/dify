"""Workspace-scoped Contact records for phase-1 HITL foundations.

This model stores authoritative workspace recipient rows created by explicit
phase-1 setup flows. Bootstrap utilities may backfill a missing member row from
current workspace membership, but Contacts are not auto-synced or lazily
materialized on read in this foundation patch.
"""

from __future__ import annotations

import enum
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapper
from sqlalchemy.orm import Mapped, mapped_column

from .base import TypeBase, gen_uuidv7_string
from .types import EnumText, StringUUID


class ContactType(enum.StrEnum):
    MEMBER = "member"
    EXTERNAL = "external"


class ContactStatus(enum.StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ContactSource(enum.StrEnum):
    WORKSPACE_MEMBER = "workspace_member"
    MANUAL_EXTERNAL = "manual_external"


class ContactInvariantError(ValueError):
    """Raised when a Contact row violates the phase-1 shape contract."""


class Contact(TypeBase):
    __tablename__ = "contacts"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="contacts_pkey"),
        sa.Index("contacts_tenant_created_at_id_idx", "tenant_id", "created_at", "id"),
        sa.UniqueConstraint("tenant_id", "type", "account_id", name="contacts_tenant_type_account_id_key"),
        sa.CheckConstraint(
            "(type != 'member') OR (account_id IS NOT NULL AND source = 'workspace_member')",
            name="contacts_member_shape_ck",
        ),
        sa.CheckConstraint(
            "(type != 'external') OR (account_id IS NULL AND trim(name) <> '' "
            "AND email IS NOT NULL AND trim(email) <> '' AND source = 'manual_external')",
            name="contacts_external_shape_ck",
        ),
    )

    id: Mapped[str] = mapped_column(
        StringUUID,
        insert_default=gen_uuidv7_string,
        default_factory=gen_uuidv7_string,
        init=False,
    )
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    type: Mapped[ContactType] = mapped_column(EnumText(ContactType, length=20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[ContactSource] = mapped_column(EnumText(ContactSource, length=40), nullable=False)
    account_id: Mapped[str | None] = mapped_column(StringUUID, nullable=True, default=None)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    status: Mapped[ContactStatus] = mapped_column(
        EnumText(ContactStatus, length=20),
        nullable=False,
        server_default=sa.text("'active'"),
        default=ContactStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
        onupdate=func.current_timestamp(),
    )

    def __post_init__(self) -> None:
        self.normalize_phase_1_shape()

    def normalize_phase_1_shape(self) -> None:
        """Validate and normalize the phase-1 Contact row shape."""
        if self.type == ContactType.MEMBER:
            if self.account_id is None:
                raise ContactInvariantError("member contacts must reference an account")
            if self.source != ContactSource.WORKSPACE_MEMBER:
                raise ContactInvariantError("member contacts must use workspace_member source")
            return

        if self.type == ContactType.EXTERNAL:
            if self.account_id is not None:
                raise ContactInvariantError("external contacts cannot reference an account")
            if not self.name.strip():
                raise ContactInvariantError("external contacts must define a non-empty name")
            if self.email is None or not self.email.strip():
                raise ContactInvariantError("external contacts must define a delivery email")
            if self.source != ContactSource.MANUAL_EXTERNAL:
                raise ContactInvariantError("external contacts must use manual_external source")
            return

        raise ContactInvariantError(f"unsupported contact type: {self.type}")


@sa.event.listens_for(Contact, "before_insert")
@sa.event.listens_for(Contact, "before_update")
def _normalize_contact_before_persist(_mapper: Mapper[Contact], _connection: sa.Connection, target: Contact) -> None:
    target.normalize_phase_1_shape()
