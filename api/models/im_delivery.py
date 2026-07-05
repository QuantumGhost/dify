"""IM delivery persistence models for phase-1 HITL foundations."""

from __future__ import annotations

import enum
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import TypeBase, gen_uuidv7_string
from .im_integration import IMProvider
from .types import EnumText, StringUUID


class IMMessageDeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUBMITTED = "submitted"
    VALIDATION_ERROR = "validation_error"
    EXPIRED = "expired"
    ALREADY_HANDLED = "already_handled"


class IMMessageCardStatus(enum.StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    ERROR = "error"
    EXPIRED = "expired"
    ALREADY_HANDLED = "already_handled"


class IMMessageCorrelation(TypeBase):
    __tablename__ = "im_message_correlations"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="im_message_correlations_pkey"),
        sa.Index("im_message_correlations_form_id_idx", "form_id"),
        sa.Index("im_message_correlations_recipient_id_idx", "recipient_id"),
        sa.Index("im_message_correlations_provider_message_id_idx", "provider_message_id"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID,
        insert_default=gen_uuidv7_string,
        default_factory=gen_uuidv7_string,
        init=False,
    )
    form_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    recipient_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    provider: Mapped[IMProvider] = mapped_column(EnumText(IMProvider, length=20), nullable=False)
    interaction_mapping_snapshot: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider_workspace_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    last_provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    delivery_status: Mapped[IMMessageDeliveryStatus] = mapped_column(
        EnumText(IMMessageDeliveryStatus, length=32),
        nullable=False,
        server_default=sa.text("'pending'"),
        default=IMMessageDeliveryStatus.PENDING,
    )
    target_card_status: Mapped[IMMessageCardStatus] = mapped_column(
        EnumText(IMMessageCardStatus, length=32),
        nullable=False,
        server_default=sa.text("'pending'"),
        default=IMMessageCardStatus.PENDING,
    )
    error_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
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


class IMProcessedCallbackEvent(TypeBase):
    __tablename__ = "im_processed_callback_events"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="im_processed_callback_events_pkey"),
        sa.UniqueConstraint("provider", "event_id", name="im_processed_callback_events_provider_event_id_key"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID,
        insert_default=gen_uuidv7_string,
        default_factory=gen_uuidv7_string,
        init=False,
    )
    provider: Mapped[IMProvider] = mapped_column(EnumText(IMProvider, length=20), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        init=False,
    )
