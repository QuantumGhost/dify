"""Provider-neutral IM DTOs and contracts for phase-1 HITL foundations.

Provider-specific implementations should prefer official SDKs when available.
This module only defines shared application-layer contracts and does not own
transport details.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from models.im_integration import IMProvider
from services.human_input_im.app_config_service import IMAppContext


class IMBindingCallbackCommand(BaseModel):
    provider: IMProvider
    event_id: str
    code: str | None = None
    state: str | None = None


class IMSendCommand(BaseModel):
    provider: IMProvider
    app_context: IMAppContext
    recipient_id: str
    form_id: str
    title: str
    content: str
    metadata: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


class IMSendResult(BaseModel):
    provider: IMProvider
    accepted: bool
    provider_message_id: str | None = None
    error: str | None = None

    model_config = ConfigDict(frozen=True)


class IMSubmissionEvent(BaseModel):
    provider: IMProvider
    event_id: str
    provider_user_id: str
    provider_workspace_id: str | None = None
    interaction_id: str | None = None
    payload: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


class IMCardUpdateCommand(BaseModel):
    provider: IMProvider
    app_context: IMAppContext
    provider_message_id: str
    target_status: str
    metadata: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


class HumanInputIMProvider(Protocol):
    """Provider-neutral IM provider contract.

    Implementations should prefer official provider SDKs whenever they exist.
    """

    provider: IMProvider

    def verify_signature(self, app_context: IMAppContext, payload: bytes, headers: dict[str, str]) -> None: ...

    def send_form(self, command: IMSendCommand) -> IMSendResult: ...

    def parse_submission(self, event: IMSubmissionEvent) -> dict[str, str]: ...

    def update_card(self, command: IMCardUpdateCommand) -> None: ...

    def build_challenge_response(self, challenge: str) -> dict[str, str]: ...
