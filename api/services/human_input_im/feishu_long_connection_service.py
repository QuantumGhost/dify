"""Feishu long-connection event consumer skeleton for phase-1 HITL foundations.

This module intentionally does not start or manage the real Feishu SDK client
yet. Future transport integration should use the official SDK for long
connection event delivery, authenticate provider payloads there, then
normalize raw provider events into the shared application-layer callback
commands defined here.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.im_integration import IMProvider
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.app_config_service import IMAppContext, IMAppConfigStatus, IMEventMode
from services.human_input_im.callback_service import IMBindingCompletionEvent, IMBindingCompletionResult
from services.human_input_im.service import HumanInputIMService


class FeishuLongConnectionBindingConsumer:
    """Normalize authenticated Feishu long-connection events into phase-1 binding commands."""

    def __init__(self, im_service: HumanInputIMService | None = None) -> None:
        self._im_service = im_service or HumanInputIMService()

    def can_consume(self, *, app_context: IMAppContext) -> bool:
        return (
            app_context.provider == IMProvider.FEISHU
            and app_context.status == IMAppConfigStatus.CONFIGURED
            and app_context.event_mode == IMEventMode.LONG_CONNECTION
        )

    def build_binding_completion_event(
        self,
        *,
        app_context: IMAppContext,
        raw_event: dict[str, str],
    ) -> IMBindingCompletionEvent:
        if not self.can_consume(app_context=app_context):
            raise IMBindingValidationError("feishu long-connection consumer requires a configured long_connection app")

        try:
            return IMBindingCompletionEvent(
                provider=IMProvider.FEISHU,
                event_id=raw_event["event_id"],
                binding_session_token=raw_event["binding_session_token"],
                provider_workspace_id=raw_event["provider_workspace_id"],
                provider_user_id=raw_event["provider_user_id"],
                provider_union_id=raw_event.get("provider_union_id"),
                provider_user_display_name=raw_event.get("provider_user_display_name"),
                provider_user_avatar_url=raw_event.get("provider_user_avatar_url"),
            )
        except KeyError as exc:
            raise IMBindingValidationError(f"missing required feishu long-connection field: {exc.args[0]}") from exc

    def consume_binding_completion_event(
        self,
        *,
        session: Session,
        app_context: IMAppContext,
        raw_event: dict[str, str],
    ) -> IMBindingCompletionResult:
        event = self.build_binding_completion_event(app_context=app_context, raw_event=raw_event)
        return self._im_service.handle_binding_completion_callback(session=session, event=event)
