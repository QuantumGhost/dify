from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import TypeBase
from .types import StringUUID


@dataclass(frozen=True)
class MemberContactBinding:
    contact_id: str | None
    tenant_id: str
    account_id: str
    name: str
    email: str
    feishu_open_id: str | None

    @property
    def is_feishu_bound(self) -> bool:
        return bool(self.feishu_open_id)


class MemberContact(TypeBase):
    __tablename__ = "member_contacts"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="member_contact_pkey"),
        sa.UniqueConstraint("tenant_id", "account_id", name="unique_member_contact_tenant_account"),
        sa.Index("member_contacts_tenant_id_idx", "tenant_id"),
        sa.Index("member_contacts_account_id_idx", "account_id"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    account_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="workspace_member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False, onupdate=func.current_timestamp()
    )
