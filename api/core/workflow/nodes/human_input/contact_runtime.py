"""Contact-oriented Human Input runtime contract for the phase-1 seam.

This module owns the v2 runtime-only DTOs used after the workflow layer adapts
the persisted v1 Human Input payload. The adapter may translate into these
types, but it should not define the runtime contract itself.
"""

from __future__ import annotations

import enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .entities import HumanInputNodeData

CONTACT_HUMAN_INPUT_NODE_TYPE = "human-input-contact"


class ContactRecipientType(enum.StrEnum):
    MEMBER = enum.auto()
    EXTERNAL = enum.auto()
    WORKSPACE_MEMBERS = "workspace_members"


class MemberContactRecipient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ContactRecipientType.MEMBER] = ContactRecipientType.MEMBER
    account_id: str


class ExternalContactRecipient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ContactRecipientType.EXTERNAL] = ContactRecipientType.EXTERNAL
    email: str


class WorkspaceMembersContactRecipient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ContactRecipientType.WORKSPACE_MEMBERS] = ContactRecipientType.WORKSPACE_MEMBERS


ContactRecipientConfig = Annotated[
    MemberContactRecipient | ExternalContactRecipient | WorkspaceMembersContactRecipient,
    Field(discriminator="type"),
]


class ContactHumanInputNodeData(HumanInputNodeData):
    """Transitional v2 runtime-facing Human Input config.

    NOTE(QuantumGhost): this is intentionally a runtime-only seam for the demo
    migration path. Do not treat it as the long-term persisted frontend schema.
    """

    type: Literal[CONTACT_HUMAN_INPUT_NODE_TYPE] = CONTACT_HUMAN_INPUT_NODE_TYPE
    version: Literal["2"] = "2"
    # Keep legacy delivery methods on the runtime DTO so the phase-1 backend can
    # still reuse existing delivery/seeding paths while the frontend emits only
    # the old v1 Human Input payload shape.
    delivery_methods: list[Any] = Field(default_factory=list)
    recipients: list[ContactRecipientConfig] = Field(default_factory=list[ContactRecipientConfig])
    allow_current_initiator_to_approve: bool = False


class ContactRecipientSeedType(enum.StrEnum):
    EMAIL_MEMBER = "email_member"
    EMAIL_EXTERNAL = "email_external"


class HumanInputRecipientSeed(BaseModel):
    """Authoritative v2 recipient identity resolved before repository writes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recipient_type: ContactRecipientSeedType
    email: str
    user_id: str | None = None
    contact_id: str
    contact_tenant_id: str
    contact_type: str
    contact_source: str
    contact_status: str
    contact_name: str
    contact_account_id: str | None = None
    contact_email: str | None = None


__all__ = [
    "CONTACT_HUMAN_INPUT_NODE_TYPE",
    "ContactHumanInputNodeData",
    "ContactRecipientConfig",
    "ContactRecipientSeedType",
    "ContactRecipientType",
    "ExternalContactRecipient",
    "HumanInputRecipientSeed",
    "MemberContactRecipient",
    "WorkspaceMembersContactRecipient",
]
