"""Provider-neutral callback handling for phase-1 HITL foundations.

Transport-specific consumers (for example Feishu long-connection listeners) and
future HTTP callback adapters should normalize provider events into these
application-layer commands. Provider-specific integrations should prefer
official SDKs when available.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.im_delivery import IMProcessedCallbackEvent
from models.im_integration import IMProvider
from services.entities.im_binding_entities import IMBindingRecord
from services.human_input_im.orchestration_service import HumanInputIMOrchestrationService


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
