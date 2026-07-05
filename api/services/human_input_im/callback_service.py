"""Provider-neutral callback handling for phase-1 HITL foundations.

Transport-specific consumers (for example Feishu long-connection listeners) and
future HTTP callback adapters should normalize provider events into these
application-layer commands. Provider-specific integrations should prefer
official SDKs when available, especially when turning raw callback payloads
into provider-local action/component identifiers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.human_input import RecipientType
from models.im_delivery import IMProcessedCallbackEvent
from models.im_integration import IMProvider
from services.entities.im_binding_entities import IMBindingRecord
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.orchestration_service import HumanInputIMOrchestrationService
from services.human_input_im.provider_types import IMSubmissionEvent


class IMBindingCompletionEvent(BaseModel):
    provider: IMProvider
    event_id: str
    binding_session_token: str
    provider_workspace_id: str
    provider_user_id: str
    provider_union_id: str | None = None
    provider_user_display_name: str | None = None
    provider_user_avatar_url: str | None = None

    model_config = ConfigDict(frozen=True)


class IMInteractionInputMapping(BaseModel):
    output_variable_name: str
    type: str | None = None

    model_config = ConfigDict(frozen=True)


class IMInteractionActionMapping(BaseModel):
    action_id: str

    model_config = ConfigDict(frozen=True)


class IMInteractionMappingSnapshot(BaseModel):
    """Trusted server-side snapshot used to interpret provider-local callback ids."""

    schema_version: int = 1
    interaction_id: str
    inputs: dict[str, IMInteractionInputMapping] = Field(default_factory=dict)
    actions: dict[str, IMInteractionActionMapping] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


class IMParsedSubmissionPayload(BaseModel):
    """Provider-local callback payload after SDK-backed transport parsing.

    Provider adapters should parse raw callback JSON into this structure. The
    provider-neutral callback service does not inspect raw webhook payloads.
    """

    provider_action_id: str
    provider_inputs: dict[str, JsonValue] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


class IMSubmissionCallbackContext(BaseModel):
    """Minimal callback context loaded from server-side binding/recipient state."""

    provider: IMProvider
    form_token: str
    recipient_type: RecipientType
    binding_provider_workspace_id: str
    binding_provider_user_id: str
    recipient_provider_workspace_id: str
    recipient_provider_user_id: str
    interaction_mapping: IMInteractionMappingSnapshot
    submission_user_id: str | None = None
    submission_end_user_id: str | None = None

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def validate_submission_actor(self) -> "IMSubmissionCallbackContext":
        if (self.submission_user_id is None) == (self.submission_end_user_id is None):
            raise ValueError("exactly one submission actor id must be set")
        return self


class HumanInputIMSubmissionCommand(BaseModel):
    """Arguments shaped for `HumanInputService.submit_form_by_token(...)`."""

    recipient_type: RecipientType
    form_token: str
    selected_action_id: str
    form_data: dict[str, JsonValue]
    submission_user_id: str | None = None
    submission_end_user_id: str | None = None

    model_config = ConfigDict(frozen=True)


class HumanInputIMCallbackService:
    def __init__(self, orchestration_service: HumanInputIMOrchestrationService | None = None) -> None:
        self._orchestration_service = orchestration_service or HumanInputIMOrchestrationService()

    def complete_binding(
        self,
        *,
        session: Session,
        event: IMBindingCompletionEvent,
    ) -> IMBindingRecord | None:
        if not self.record_event_once(session=session, provider=event.provider, event_id=event.event_id):
            return None
        return self._orchestration_service.complete_binding_session(
            session=session,
            token=event.binding_session_token,
            provider_workspace_id=event.provider_workspace_id,
            provider_user_id=event.provider_user_id,
            provider_union_id=event.provider_union_id,
            provider_user_display_name=event.provider_user_display_name,
            provider_user_avatar_url=event.provider_user_avatar_url,
        )

    def record_event_once(
        self,
        *,
        session: Session,
        provider: IMProvider,
        event_id: str,
    ) -> bool:
        event_model = IMProcessedCallbackEvent(provider=provider, event_id=event_id)
        session.add(event_model)
        try:
            session.flush([event_model])
        except IntegrityError:
            return False
        return True

    def acknowledge_event(self, *, event_id: str) -> dict[str, str]:
        return {"result": "accepted", "event_id": event_id}

    def build_submission_command(
        self,
        *,
        event: IMSubmissionEvent,
        context: IMSubmissionCallbackContext,
        parsed_payload: IMParsedSubmissionPayload,
    ) -> HumanInputIMSubmissionCommand:
        """Validate callback identity and map provider-local ids to Dify submission args."""

        self._validate_submission_context(event=event, context=context)

        action_mapping = context.interaction_mapping.actions.get(parsed_payload.provider_action_id)
        if action_mapping is None:
            raise IMBindingValidationError(f"unknown IM callback action id: {parsed_payload.provider_action_id}")

        form_data: dict[str, JsonValue] = {}
        for provider_component_id, value in parsed_payload.provider_inputs.items():
            input_mapping = context.interaction_mapping.inputs.get(provider_component_id)
            if input_mapping is None:
                raise IMBindingValidationError(f"unknown IM callback input component id: {provider_component_id}")
            form_data[input_mapping.output_variable_name] = value

        return HumanInputIMSubmissionCommand(
            recipient_type=context.recipient_type,
            form_token=context.form_token,
            selected_action_id=action_mapping.action_id,
            form_data=form_data,
            submission_user_id=context.submission_user_id,
            submission_end_user_id=context.submission_end_user_id,
        )

    def _validate_submission_context(
        self,
        *,
        event: IMSubmissionEvent,
        context: IMSubmissionCallbackContext,
    ) -> None:
        if event.provider != context.provider:
            raise IMBindingValidationError("callback provider does not match submission context")
        if event.provider_workspace_id != context.binding_provider_workspace_id:
            raise IMBindingValidationError("provider workspace does not match active binding")
        if event.provider_user_id != context.binding_provider_user_id:
            raise IMBindingValidationError("provider user does not match active binding")
        if event.provider_workspace_id != context.recipient_provider_workspace_id:
            raise IMBindingValidationError("provider workspace does not match original recipient")
        if event.provider_user_id != context.recipient_provider_user_id:
            raise IMBindingValidationError("provider user does not match original recipient")
        if event.interaction_id != context.interaction_mapping.interaction_id:
            raise IMBindingValidationError("unknown IM callback interaction mapping")
