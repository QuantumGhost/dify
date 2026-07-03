from __future__ import annotations

from types import SimpleNamespace

from services.human_input_im.config_store import (
    HumanInputIMIngressMode,
    HumanInputIMProvider,
    HumanInputIMProviderConfig,
)
from services.human_input_im.feishu_long_connection_service import FeishuLongConnectionService


def test_feishu_long_connection_service_starts_ws_channel(monkeypatch):
    seen = {"started": 0, "handlers": {}}

    class _FakeChannel:
        def on(self, name, handler):
            seen["handlers"][name] = handler

        def start(self):
            seen["started"] += 1

        def stop(self):
            seen["stopped"] = True

    monkeypatch.setattr(
        "services.human_input_im.feishu_long_connection_service.submit_im_card_action",
        lambda **kwargs: None,
    )

    def fake_build_channel(config, handler, transport_kind):
        channel = _FakeChannel()
        channel.on("cardAction", handler)
        return channel

    monkeypatch.setattr(
        "services.human_input_im.feishu_long_connection_service._build_feishu_channel",
        fake_build_channel,
    )

    service = FeishuLongConnectionService(
        config_store=SimpleNamespace(
            get_owner_tenant_id=lambda: None,
            get_active_config=lambda tenant_id: HumanInputIMProviderConfig(
                provider=HumanInputIMProvider.FEISHU,
                ingress_mode=HumanInputIMIngressMode.STREAM,
                app_id="app-id",
                app_secret="app-secret",
            )
        )
    )

    assert service.start() is True
    assert seen["started"] == 1
    assert "cardAction" in seen["handlers"]
