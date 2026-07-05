"""Provider-neutral IM service facade for phase-1 HITL foundations.

This facade composes the existing orchestration and callback services into one
stable application-layer entry point. Provider-specific transport should still
prefer official SDKs when available. The facade only coordinates provider
lookup, app-context resolution, and delegation into the existing binding and
callback slices; it does not own transport, persistence, or SDK lifecycles.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.im_integration import IMProvider
from services.entities.im_binding_entities import IMBindingRecord
from services.human_input_im.app_config_service import IMAppContext
from services.human_input_im.callback_service import (
    HumanInputIMCallbackService,
    IMBindingCompletionEvent,
    IMBindingCompletionResult,
    IMFormSubmissionSubmitter,
    IMParsedSubmissionPayload,
    IMSubmissionCallbackContext,
    IMSubmissionCallbackResult,
)
from services.human_input_im.orchestration_service import HumanInputIMOrchestrationService
from services.human_input_im.provider_types import (
    IMCardUpdateCommand,
    IMSendCommand,
    IMSendResult,
    IMSubmissionEvent,
    HumanInputIMProvider,
)


BindingCompletionCallbackResult = IMBindingCompletionResult


class HumanInputIMService:
    def __init__(
        self,
        orchestration_service: HumanInputIMOrchestrationService | None = None,
        callback_service: HumanInputIMCallbackService | None = None,
    ) -> None:
        self._orchestration_service = orchestration_service or HumanInputIMOrchestrationService()
        self._callback_service = callback_service or HumanInputIMCallbackService(
            orchestration_service=self._orchestration_service
        )

    def resolve_app_context(self, *, provider: IMProvider, tenant_id: str) -> IMAppContext:
        return self._orchestration_service.resolve_app_context(provider=provider, tenant_id=tenant_id)

    def get_provider_or_raise(self, provider: IMProvider):
        return self._orchestration_service.get_provider_or_raise(provider)

    def start_binding_session(
        self,
        *,
        session: Session,
        account_id: str,
        tenant_id: str,
        provider: IMProvider,
    ):
        return self._orchestration_service.start_binding_session(
            session=session,
            account_id=account_id,
            tenant_id=tenant_id,
            provider=provider,
        )

    def inspect_active_binding(self, *, session: Session, account_id: str) -> IMBindingRecord | None:
        return self._orchestration_service.inspect_active_binding(session=session, account_id=account_id)

    def revoke_active_binding(self, *, session: Session, account_id: str) -> IMBindingRecord | None:
        return self._orchestration_service.revoke_active_binding(session=session, account_id=account_id)

    def send_form(
        self,
        *,
        provider: IMProvider,
        tenant_id: str,
        recipient_id: str,
        form_id: str,
        title: str,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> IMSendResult:
        resolved_provider, app_context = self._resolve_provider_command_context(
            provider=provider,
            tenant_id=tenant_id,
        )
        return resolved_provider.send_form(
            IMSendCommand(
                provider=provider,
                app_context=app_context,
                recipient_id=recipient_id,
                form_id=form_id,
                title=title,
                content=content,
                metadata=dict(metadata or {}),
            )
        )

    def update_card(
        self,
        *,
        provider: IMProvider,
        tenant_id: str,
        provider_message_id: str,
        target_status: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        resolved_provider, app_context = self._resolve_provider_command_context(
            provider=provider,
            tenant_id=tenant_id,
        )
        resolved_provider.update_card(
            IMCardUpdateCommand(
                provider=provider,
                app_context=app_context,
                provider_message_id=provider_message_id,
                target_status=target_status,
                metadata=dict(metadata or {}),
            )
        )

    def handle_binding_completion_callback(
        self,
        *,
        session: Session,
        event: IMBindingCompletionEvent,
    ) -> BindingCompletionCallbackResult:
        return self._callback_service.complete_binding(session=session, event=event)

    def handle_submission_callback(
        self,
        *,
        session: Session,
        event: IMSubmissionEvent,
        context: IMSubmissionCallbackContext,
        parsed_payload: IMParsedSubmissionPayload,
        submitter: IMFormSubmissionSubmitter,
    ) -> IMSubmissionCallbackResult:
        return self._callback_service.handle_submission(
            session=session,
            event=event,
            context=context,
            parsed_payload=parsed_payload,
            submitter=submitter,
        )

    def _resolve_provider_command_context(
        self,
        *,
        provider: IMProvider,
        tenant_id: str,
    ) -> tuple[HumanInputIMProvider, IMAppContext]:
        """Resolve the provider implementation before app context for stable failures."""

        resolved_provider = self.get_provider_or_raise(provider)
        app_context = self.resolve_app_context(provider=provider, tenant_id=tenant_id)
        return resolved_provider, app_context
