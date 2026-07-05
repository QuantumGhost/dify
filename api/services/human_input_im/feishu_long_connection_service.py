"""Feishu long-connection transport-facing helpers for phase-1 HITL foundations.

The actual long-connection lifecycle still belongs to the surrounding runtime,
but this module now owns the transport seam that turns raw Feishu callback
payloads into application-layer commands. Parsing uses the official
``lark_oapi`` event dispatcher so provider-local callback ids are extracted the
same way in long-connection and webhook-compatible flows.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.im_integration import IMProvider
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.app_config_service import IMAppContext, IMAppConfigStatus, IMEventMode
from services.human_input_im.callback_service import IMBindingCompletionEvent, IMBindingCompletionResult
from services.human_input_im.feishu_provider import FeishuHumanInputIMProvider
from services.human_input_im.provider_types import IMParsedProviderSubmission, IMParsedSubmissionPayload, IMSubmissionEvent
from services.human_input_im.service import HumanInputIMService


class FeishuLongConnectionBindingConsumer:
    """Normalize Feishu long-connection payloads into shared callback commands."""

    def __init__(
        self,
        im_service: HumanInputIMService | None = None,
        provider: FeishuHumanInputIMProvider | None = None,
    ) -> None:
        self._im_service = im_service or HumanInputIMService()
        self._provider = provider or FeishuHumanInputIMProvider()

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

    def parse_submission_callback(
        self,
        *,
        app_context: IMAppContext,
        raw_payload: bytes | str,
    ) -> IMParsedProviderSubmission:
        if not self.can_consume(app_context=app_context):
            raise IMBindingValidationError("feishu long-connection consumer requires a configured long_connection app")

        payload_bytes = raw_payload.encode("utf-8") if isinstance(raw_payload, str) else raw_payload
        return self._provider.parse_submission_callback(
            app_context=app_context,
            payload=payload_bytes,
            assume_verified=True,
        )

    def build_submission_event(
        self,
        *,
        app_context: IMAppContext,
        raw_payload: bytes | str,
    ) -> IMSubmissionEvent:
        return self.parse_submission_callback(app_context=app_context, raw_payload=raw_payload).event

    def parse_submission_payload(
        self,
        *,
        app_context: IMAppContext,
        raw_payload: bytes | str,
    ) -> tuple[IMSubmissionEvent, IMParsedSubmissionPayload]:
        parsed_submission = self.parse_submission_callback(app_context=app_context, raw_payload=raw_payload)
        return parsed_submission.event, parsed_submission.parsed_payload
