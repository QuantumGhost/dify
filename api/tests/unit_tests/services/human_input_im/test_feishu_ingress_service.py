from __future__ import annotations

from types import SimpleNamespace

from services.human_input_im.config_store import (
    HumanInputIMIngressMode,
    HumanInputIMProvider,
    HumanInputIMProviderConfig,
)
from services.human_input_im.feishu_ingress_service import FeishuIngressService


def test_feishu_ingress_service_handles_webhook_requests(monkeypatch):
    seen = {"started": 0, "handlers": {}}

    class _FakeChannel:
        def on(self, name, handler):
            seen["handlers"][name] = handler

        def start(self):
            seen["started"] += 1

        async def handle_webhook_request(self, headers, body):
            return 200, b"ok"

    monkeypatch.setattr(
        "services.human_input_im.feishu_ingress_service.submit_im_card_action",
        lambda **kwargs: None,
    )

    def fake_build_channel(config, handler):
        channel = _FakeChannel()
        channel.on("cardAction", handler)
        return channel

    monkeypatch.setattr(
        "services.human_input_im.feishu_ingress_service._build_feishu_channel",
        fake_build_channel,
    )

    service = FeishuIngressService(
        config_store=SimpleNamespace(
            get_owner_tenant_id=lambda: None,
            get_active_config=lambda tenant_id: HumanInputIMProviderConfig(
                provider=HumanInputIMProvider.FEISHU,
                ingress_mode=HumanInputIMIngressMode.WEBHOOK,
                app_id="app-id",
                app_secret="app-secret",
            )
        )
    )

    status, body = service.handle_webhook_request(headers={"x": "1"}, body=b"{}")

    assert status == 200
    assert body == b"ok"
    assert seen["started"] == 1
    assert "cardAction" in seen["handlers"]


def test_feishu_ingress_service_translates_card_action_to_submit(monkeypatch):
    submitted = []

    monkeypatch.setattr(
        "services.human_input_im.feishu_ingress_service.submit_im_card_action",
        lambda **kwargs: submitted.append(kwargs),
    )
    monkeypatch.setattr(
        "services.human_input_im.feishu_ingress_service.db",
        SimpleNamespace(engine=object()),
    )

    service = FeishuIngressService(
        config_store=SimpleNamespace(get_owner_tenant_id=lambda: None, get_active_config=lambda tenant_id: None)
    )

    service._handle_card_action(
        SimpleNamespace(
            operator=SimpleNamespace(open_id="open-1", user_id="user-1"),
            action=SimpleNamespace(
                value={"form_token": "token-1", "action_id": "approve"},
                name="approve",
                form_value={"comment": "ok"},
            ),
        )
    )

    assert submitted == [
        {
            "session": submitted[0]["session"],
            "form_token": "token-1",
            "action_id": "approve",
            "form_data": {"comment": "ok"},
            "operator_open_id": "open-1",
            "operator_user_id": "user-1",
        }
    ]


def test_feishu_ingress_service_swallows_business_rejections(monkeypatch):
    monkeypatch.setattr(
        "services.human_input_im.feishu_ingress_service.submit_im_card_action",
        lambda **kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )
    monkeypatch.setattr(
        "services.human_input_im.feishu_ingress_service.db",
        SimpleNamespace(engine=object()),
    )

    service = FeishuIngressService(config_store=SimpleNamespace(get_active_config=lambda tenant_id: None))

    service._handle_card_action(
        SimpleNamespace(
            operator=SimpleNamespace(open_id="open-1", user_id="user-1"),
            action=SimpleNamespace(
                value={"form_token": "token-1", "action_id": "approve"},
                name="approve",
                form_value={"comment": "ok"},
            ),
        )
    )
