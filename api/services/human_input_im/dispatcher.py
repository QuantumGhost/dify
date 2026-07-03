from __future__ import annotations

import asyncio
from collections.abc import Hashable
from typing import Any

from services.human_input_im.config_store import (
    HumanInputIMIngressMode,
    HumanInputIMProvider,
    HumanInputIMProviderConfig,
)
from services.human_input_im.entities import HumanInputIMNotificationJob
from services.human_input_im.providers.feishu_card_builder import build_feishu_card_payload


class HumanInputIMDispatcher:
    def __init__(self) -> None:
        self._channels: dict[tuple[Hashable, ...], Any] = {}

    def send_form_notification(
        self,
        *,
        config: HumanInputIMProviderConfig,
        job: HumanInputIMNotificationJob,
    ) -> None:
        if config.provider != HumanInputIMProvider.FEISHU:
            raise ValueError(f"Unsupported IM provider: {config.provider}")

        receive_id, receive_id_type = _resolve_recipient_identity(job)
        card_payload = build_feishu_card_payload(job).payload
        channel = self._get_channel(config)
        result = asyncio.run(
            channel.send(
                receive_id,
                {"card": card_payload},
                {"receive_id_type": receive_id_type},
            )
        )
        if not getattr(result, "success", False):
            raise RuntimeError(f"Failed to send IM card notification for form {job.form_id}")

    def _get_channel(self, config: HumanInputIMProviderConfig):
        cache_key = (
            config.provider,
            config.ingress_mode,
            config.app_id,
        )
        channel = self._channels.get(cache_key)
        if channel is not None:
            return channel

        channel = _build_feishu_channel(config)
        self._channels[cache_key] = channel
        return channel


def _resolve_recipient_identity(job: HumanInputIMNotificationJob) -> tuple[str, str]:
    if job.recipient.open_id:
        return job.recipient.open_id, "open_id"
    if job.recipient.user_id:
        return job.recipient.user_id, "user_id"
    raise ValueError(f"Recipient has neither open_id nor user_id, account_id={job.recipient.account_id}")


def _build_feishu_channel(config: HumanInputIMProviderConfig):
    from lark_channel import FeishuChannel

    transport_kind = "webhook"
    if config.ingress_mode == HumanInputIMIngressMode.STREAM:
        transport_kind = "ws"

    return FeishuChannel(
        app_id=config.app_id,
        app_secret=config.app_secret,
        transport=transport_kind,
    )
