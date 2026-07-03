from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from extensions.ext_database import db
from services.human_input_im.callback_service import submit_im_card_action
from services.human_input_im.config_store import (
    EnvBackedProviderConfigStore,
    HumanInputIMIngressMode,
    HumanInputIMProviderConfig,
    ProviderConfigStore,
)
from services.human_input_service import HumanInputError


class FeishuLongConnectionService:
    def __init__(self, *, config_store: ProviderConfigStore | None = None) -> None:
        self._config_store = config_store or EnvBackedProviderConfigStore()
        self._channel: Any | None = None
        self._channel_config: HumanInputIMProviderConfig | None = None

    def start(self) -> bool:
        config = self._config_store.get_active_config(tenant_id=self._resolve_owner_tenant_id())
        if config is None:
            return False
        if config.ingress_mode != HumanInputIMIngressMode.STREAM:
            return False

        if self._channel is not None and self._channel_config == config:
            return True

        channel = _build_feishu_channel(config, self._handle_card_action, "ws")
        channel.start()
        self._channel = channel
        self._channel_config = config
        return True

    def stop(self) -> None:
        if self._channel is None:
            return
        stop = getattr(self._channel, "stop", None)
        if callable(stop):
            stop()
        self._channel = None
        self._channel_config = None

    def _resolve_owner_tenant_id(self) -> str:
        owner_tenant_id = self._config_store.get_owner_tenant_id()
        return owner_tenant_id or ""

    def _handle_card_action(self, event: Any) -> None:
        try:
            action_value = getattr(event.action, "value", None) or {}
            form_token = action_value.get("form_token")
            action_id = action_value.get("action_id") or getattr(event.action, "name", None)
            if not form_token or not action_id:
                raise ValueError("Missing form_token or action_id in card action callback")

            with Session(bind=db.engine, expire_on_commit=False) as session:
                submit_im_card_action(
                    session=session,
                    form_token=form_token,
                    action_id=action_id,
                    form_data=getattr(event.action, "form_value", None) or {},
                    operator_open_id=getattr(event.operator, "open_id", None),
                    operator_user_id=getattr(event.operator, "user_id", None),
                )
        except (HumanInputError, PermissionError, ValueError):
            return


def _build_feishu_channel(config: HumanInputIMProviderConfig, card_action_handler, transport_kind: str):
    from lark_channel import FeishuChannel

    channel = FeishuChannel(
        app_id=config.app_id,
        app_secret=config.app_secret,
        verification_token=config.verification_token,
        encrypt_key=config.encrypt_key,
        transport=transport_kind,
    )
    channel.on("cardAction", card_action_handler)
    return channel
