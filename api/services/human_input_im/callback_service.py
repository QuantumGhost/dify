"""Provider-neutral callback handling for phase-1 HITL foundations.

Transport-specific consumers (for example Feishu long-connection listeners) and
future HTTP callback adapters should normalize provider events into these
application-layer commands. Provider-specific integrations should prefer
official SDKs when available, especially when turning raw callback payloads
into provider-local action/component identifiers.
"""

from __future__ import annotations

import logging
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
from services.human_input_observability import build_human_input_log_context, stringify_log_context
from services.human_input_im.orchestration_service import HumanInputIMOrchestrationService
from services.human_input_im.provider_types import IMParsedSubmissionPayload, IMSubmissionEvent
from services.human_input_im.submission_result_service import HumanInputIMSubmissionResultService

logger = logging.getLogger(__name__)


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
    tenant_id: str | None = None
    app_id: str | None = None
    workflow_run_id: str | None = None
    conversation_id: str | None = None
    form_id: str | None = None
    node_id: str | None = None
    recipient_id: str | None = None
    contact_id: str | None = None
    contact_tenant_id: str | None = None
    contact_type: str | None = None
    contact_source: str | None = None
    contact_status: str | None = None
    contact_account_id: str | None = None
    provider_message_id: str | None = None
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
            logger.info(
                "Ignored duplicate IM binding completion callback event",
                extra=build_human_input_log_context(
                    provider=event.provider,
                    provider_event_id=event.event_id,
                    provider_workspace_id=event.provider_workspace_id,
                    provider_user_id=event.provider_user_id,
                ),
            )
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
        logger.info(
            "Completed IM binding callback event",
            extra=build_human_input_log_context(
                binding=binding,
                provider_event_id=event.event_id,
                provider_workspace_id=event.provider_workspace_id,
                provider_user_id=event.provider_user_id,
            ),
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

        callback_log_context = self._build_callback_log_context(event=event, context=context)
        logger.info("Handling IM submission callback event", extra=callback_log_context)

        if not self.record_event_once(session=session, provider=event.provider, event_id=event.event_id):
            logger.info("Ignored duplicate IM submission callback event", extra=callback_log_context)
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
            logger.warning(
                "Rejected IM submission callback during binding or interaction validation",
                extra=build_human_input_log_context(
                    extra=callback_log_context | {"error_reason": self._describe_error(exc)}
                ),
            )
            self._submission_result_service.mark_validation_error(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except InvalidFormDataError as exc:
            logger.warning(
                "Rejected IM submission callback because the submitted form payload is invalid",
                extra=build_human_input_log_context(
                    extra=callback_log_context | {"error_reason": self._describe_error(exc)}
                ),
            )
            self._submission_result_service.mark_validation_error(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except WebAppDeliveryNotEnabledError as exc:
            logger.warning(
                "Rejected IM submission callback because the form token does not match the recipient delivery channel",
                extra=build_human_input_log_context(
                    extra=callback_log_context | {"error_reason": self._describe_error(exc)}
                ),
            )
            self._submission_result_service.mark_validation_error(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except FormExpiredError as exc:
            logger.warning(
                "Rejected IM submission callback because the Human Input form is expired",
                extra=build_human_input_log_context(
                    extra=callback_log_context | {"error_reason": self._describe_error(exc)}
                ),
            )
            self._submission_result_service.mark_expired(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except FormSubmittedError as exc:
            logger.info(
                "Ignored IM submission callback because the Human Input form was already handled",
                extra=build_human_input_log_context(
                    extra=callback_log_context | {"error_reason": self._describe_error(exc)}
                ),
            )
            self._submission_result_service.mark_already_handled(
                session=session,
                correlation_id=context.correlation_id,
                provider_event_id=event.event_id,
                error_reason=self._describe_error(exc),
            )
        except RepositoryFormNotFoundError as exc:
            logger.warning(
                "Rejected IM submission callback because the underlying Human Input form state is not available",
                extra=build_human_input_log_context(
                    extra=callback_log_context | {"error_reason": self._describe_error(exc)}
                ),
            )
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
                compensation_metadata=self._build_compensation_metadata(
                    event=event,
                    context=context,
                ),
            )
            logger.info("Submitted Human Input form from IM callback", extra=callback_log_context)

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

    def _build_callback_log_context(
        self,
        *,
        event: IMSubmissionEvent,
        context: IMSubmissionCallbackContext,
    ) -> dict[str, object]:
        return build_human_input_log_context(
            tenant_id=context.tenant_id,
            app_id=context.app_id,
            workflow_run_id=context.workflow_run_id,
            conversation_id=context.conversation_id,
            form_id=context.form_id,
            node_id=context.node_id,
            recipient_id=context.recipient_id,
            recipient_type=context.recipient_type,
            provider=event.provider,
            provider_workspace_id=event.provider_workspace_id,
            provider_user_id=event.provider_user_id,
            provider_message_id=context.provider_message_id,
            provider_event_id=event.event_id,
            interaction_id=event.interaction_id,
            extra={
                "correlation_id": context.correlation_id,
                "contact_id": context.contact_id,
                "contact_tenant_id": context.contact_tenant_id,
                "contact_type": context.contact_type,
                "contact_source": context.contact_source,
                "contact_status": context.contact_status,
                "contact_account_id": context.contact_account_id,
            },
        )

    def _build_compensation_metadata(
        self,
        *,
        event: IMSubmissionEvent,
        context: IMSubmissionCallbackContext,
    ) -> dict[str, str]:
        return stringify_log_context(self._build_callback_log_context(event=event, context=context))
