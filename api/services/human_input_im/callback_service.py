"""Provider-neutral callback handling for phase-1 HITL foundations.

Transport-specific consumers (for example Feishu long-connection listeners) and
future HTTP callback adapters should normalize provider events into these
application-layer commands. Provider-specific integrations should prefer
official SDKs when available, especially when turning raw callback payloads
into provider-local action/component identifiers.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.repositories.human_input_repository import FormNotFoundError as RepositoryFormNotFoundError
from models.human_input import RecipientType
from models.im_delivery import IMProcessedCallbackEvent
from models.im_integration import IMProvider
from services.entities.im_binding_entities import IMBindingRecord
from services.errors.im_binding import IMBindingValidationError
from services.human_input_service import (
    FormExpiredError,
    FormSubmittedError,
    InvalidFormDataError,
    WebAppDeliveryNotEnabledError,
)
from services.human_input_im.orchestration_service import HumanInputIMOrchestrationService
from services.human_input_im.provider_types import IMSubmissionEvent
from services.human_input_im.submission_result_service import HumanInputIMSubmissionResultService


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


class IMBindingCompletionResult(BaseModel):
    """Normalized binding-completion outcome for provider-authenticated events.

    Transport adapters should authenticate provider callbacks before building an
    `IMBindingCompletionEvent`. This result keeps the post-authentication
    application-layer outcome explicit so HTTP routes and long-connection
    consumers can share one success/duplicate-event contract.
    """

    binding: IMBindingRecord | None = None
    duplicate_event: bool = False
    acknowledgement: dict[str, str]

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

    correlation_id: str
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


class IMFormSubmissionSubmitter(Protocol):
    """Abstract `HumanInputService.submit_form_by_token(...)` collaborator."""

    def submit_form_by_token(
        self,
        recipient_type: RecipientType,
        form_token: str,
        selected_action_id: str,
        form_data: dict[str, JsonValue],
        submission_end_user_id: str | None = None,
        submission_user_id: str | None = None,
    ) -> None: ...


class IMSubmissionCallbackResult(BaseModel):
    duplicate_event: bool = False
    acknowledgement: dict[str, str]

    model_config = ConfigDict(frozen=True)


class HumanInputIMCallbackService:
    _orchestration_service: HumanInputIMOrchestrationService
    _submission_result_service: HumanInputIMSubmissionResultService

    def __init__(
        self,
        orchestration_service: HumanInputIMOrchestrationService | None = None,
        submission_result_service: HumanInputIMSubmissionResultService | None = None,
    ) -> None:
        self._orchestration_service = orchestration_service or HumanInputIMOrchestrationService()
        self._submission_result_service = submission_result_service or HumanInputIMSubmissionResultService()

    def complete_binding(
        self,
        *,
        session: Session,
        event: IMBindingCompletionEvent,
    ) -> IMBindingCompletionResult:
        if not self.record_event_once(session=session, provider=event.provider, event_id=event.event_id):
            return IMBindingCompletionResult(
                binding=None,
                duplicate_event=True,
                acknowledgement=self.acknowledge_event(event_id=event.event_id),
            )

        binding = self._orchestration_service.complete_binding_session(
            session=session,
            token=event.binding_session_token,
            provider_workspace_id=event.provider_workspace_id,
            provider_user_id=event.provider_user_id,
            provider_union_id=event.provider_union_id,
            provider_user_display_name=event.provider_user_display_name,
            provider_user_avatar_url=event.provider_user_avatar_url,
        )
        return IMBindingCompletionResult(
            binding=binding,
            duplicate_event=False,
            acknowledgement=self.acknowledge_event(event_id=event.event_id),
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

    def handle_submission(
        self,
        *,
        session: Session,
        event: IMSubmissionEvent,
        context: IMSubmissionCallbackContext,
        parsed_payload: IMParsedSubmissionPayload,
        submitter: IMFormSubmissionSubmitter,
    ) -> IMSubmissionCallbackResult:
        """Run the provider-neutral submission callback orchestration slice.

        The real `HumanInputService` remains outside this module and is injected
        as a small submitter protocol so this layer only owns validation,
        idempotency, status persistence, and async-compensation enqueueing.
        """

        if not self.record_event_once(session=session, provider=event.provider, event_id=event.event_id):
            return IMSubmissionCallbackResult(
                duplicate_event=True,
                acknowledgement=self.acknowledge_event(event_id=event.event_id),
            )

        try:
            command = self.build_submission_command(
                event=event,
                context=context,
                parsed_payload=parsed_payload,
            )
            self._submit_command(submitter=submitter, command=command)
        except IMBindingValidationError as exc:
            self._submission_result_service.mark_validation_error(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except InvalidFormDataError as exc:
            self._submission_result_service.mark_validation_error(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except WebAppDeliveryNotEnabledError as exc:
            self._submission_result_service.mark_validation_error(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except FormExpiredError as exc:
            self._submission_result_service.mark_expired(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except FormSubmittedError as exc:
            self._submission_result_service.mark_already_handled(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except RepositoryFormNotFoundError as exc:
            self._mark_repository_submission_failure(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error=exc,
            )
        else:
            self._submission_result_service.mark_submitted(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
            )

        return IMSubmissionCallbackResult(
            duplicate_event=False,
            acknowledgement=self.acknowledge_event(event_id=event.event_id),
        )

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

    def _submit_command(
        self,
        *,
        submitter: IMFormSubmissionSubmitter,
        command: HumanInputIMSubmissionCommand,
    ) -> None:
        submitter.submit_form_by_token(
            recipient_type=command.recipient_type,
            form_token=command.form_token,
            selected_action_id=command.selected_action_id,
            form_data=command.form_data,
            submission_end_user_id=command.submission_end_user_id,
            submission_user_id=command.submission_user_id,
        )

    def _mark_repository_submission_failure(
        self,
        *,
        session: Session,
        correlation_id: str,
        provider_event_id: str,
        error: RepositoryFormNotFoundError,
    ) -> None:
        error_reason = self._describe_error(error)
        if "already submitted" in error_reason:
            self._submission_result_service.mark_already_handled(
                session=session,
                correlation_id=correlation_id,
                provider_event_id=provider_event_id,
                error_reason=error_reason,
            )
            return

        self._submission_result_service.mark_validation_error(
            session=session,
            correlation_id=correlation_id,
            provider_event_id=provider_event_id,
            error_reason=error_reason,
        )

    def _describe_error(self, error: BaseException) -> str:
        description = getattr(error, "description", None)
        if isinstance(description, str) and description:
            return description
        return str(error) or error.__class__.__name__
