"""Legacy placeholder IM provider implementation.

The runtime registry now uses the real Feishu adapter from
``feishu_provider.py``. This placeholder remains only for isolated tests and
manual debugging paths that still want a no-op provider object.
"""

from __future__ import annotations

import logging

from models.im_integration import IMProvider
from services.human_input_im.app_config_service import IMAppContext
from services.human_input_im.provider_types import (
    IMCardUpdateCommand,
    IMParsedSubmissionPayload,
    IMSendCommand,
    IMSendResult,
    IMSubmissionEvent,
)

logger = logging.getLogger(__name__)


class LoggingHumanInputIMProvider:
    provider = IMProvider.FEISHU

    def verify_signature(self, app_context: IMAppContext, payload: bytes, headers: dict[str, str]) -> None:
        _ = app_context, payload, headers
        logger.info("Phase-1 IM signature verification placeholder invoked for provider=%s", self.provider.value)

    def send_form(self, command: IMSendCommand) -> IMSendResult:
        logger.info(
            "Phase-1 IM delivery placeholder invoked, provider=%s, recipient_id=%s, form_id=%s",
            command.provider.value,
            command.recipient_id,
            command.form_id,
        )
        return IMSendResult(
            provider=command.provider,
            accepted=False,
            provider_message_id=None,
            error="phase-1 provider transport adapter not implemented",
        )

    def parse_submission(self, event: IMSubmissionEvent) -> IMParsedSubmissionPayload:
        _ = event
        raise NotImplementedError("phase-1 provider submission parsing is not implemented")

    def update_card(self, command: IMCardUpdateCommand) -> None:
        logger.info(
            "Phase-1 IM card update placeholder invoked, provider=%s, provider_message_id=%s, target_status=%s",
            command.provider.value,
            command.provider_message_id,
            command.target_status,
        )

    def build_challenge_response(self, challenge: str) -> dict[str, str]:
        return {"challenge": challenge}
