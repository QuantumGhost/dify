"""Provider-neutral IM service facade for phase-1 HITL foundations.

This facade composes the existing orchestration and callback services into one
stable application-layer entry point. Provider-specific transport should still
prefer official SDKs when available.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from models.im_integration import IMProvider
from services.entities.im_binding_entities import IMBindingRecord
from services.human_input_im.callback_service import HumanInputIMCallbackService, IMBindingCompletionEvent
from services.human_input_im.orchestration_service import HumanInputIMOrchestrationService


class BindingCompletionCallbackResult(BaseModel):
    binding: IMBindingRecord | None = None
    duplicate_event: bool = False
    acknowledgement: dict[str, str]

    model_config = ConfigDict(frozen=True)


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

    def get_provider_or_raise(self, provider: IMProvider):
        return self._orchestration_service.get_provider_or_raise(provider)

    def handle_binding_completion_callback(
        self,
        *,
        session: Session,
        event: IMBindingCompletionEvent,
    ) -> BindingCompletionCallbackResult:
        binding = self._callback_service.complete_binding(session=session, event=event)
        if binding is None:
            return BindingCompletionCallbackResult(
                binding=None,
                duplicate_event=True,
                acknowledgement=self._callback_service.acknowledge_event(event_id=event.event_id),
            )
        return BindingCompletionCallbackResult(
            binding=binding,
            duplicate_event=False,
            acknowledgement=self._callback_service.acknowledge_event(event_id=event.event_id),
        )
