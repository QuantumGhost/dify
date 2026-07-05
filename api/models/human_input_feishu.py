import enum
from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import TypeBase
from .types import EnumText, StringUUID


class HumanInputFeishuDeliveryMode(enum.StrEnum):
    INTERACTIVE_CARD = "interactive_card"
    LINK_FALLBACK = "link_fallback"


class HumanInputFeishuDeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    COMPLETED = "completed"


class HumanInputFeishuDelivery(TypeBase):
    __tablename__ = "human_input_feishu_deliveries"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="human_input_feishu_delivery_pkey"),
        sa.UniqueConstraint("form_id", "recipient_id", name="unique_form_recipient_feishu_delivery"),
        sa.Index("human_input_feishu_deliveries_form_id_idx", "form_id"),
        sa.Index("human_input_feishu_deliveries_message_id_idx", "message_id"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    form_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    recipient_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    account_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    delivery_mode: Mapped[HumanInputFeishuDeliveryMode] = mapped_column(
        EnumText(HumanInputFeishuDeliveryMode, length=32),
        nullable=False,
    )
    member_contact_id: Mapped[str | None] = mapped_column(StringUUID, nullable=True, default=None)
    open_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    status: Mapped[HumanInputFeishuDeliveryStatus] = mapped_column(
        EnumText(HumanInputFeishuDeliveryStatus, length=16),
        nullable=False,
        default=HumanInputFeishuDeliveryStatus.PENDING,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    card_payload: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False, onupdate=func.current_timestamp()
    )
