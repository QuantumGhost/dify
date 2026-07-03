from __future__ import annotations

from types import SimpleNamespace

from services.human_input_im.config_store import (
    HumanInputIMIngressMode,
    HumanInputIMProvider,
    HumanInputIMProviderConfig,
)
from services.human_input_im.dispatcher import HumanInputIMDispatcher
from services.human_input_im.entities import (
    FeishuCardBuildResult,
    HumanInputIMAction,
    HumanInputIMField,
    HumanInputIMNotificationJob,
    HumanInputIMRecipient,
)


def test_dispatcher_sends_feishu_card_to_open_id(monkeypatch):
    sent = []

    class _FakeChannel:
        async def send(self, to, message, opts=None):
            sent.append((to, message, opts))
            return SimpleNamespace(success=True, message_id="om_1", error=None)

    monkeypatch.setattr(
        "services.human_input_im.dispatcher.build_feishu_card_payload",
        lambda job: FeishuCardBuildResult(mode="inline_card", payload={"schema": "2.0", "body": {"elements": []}}),
    )
    monkeypatch.setattr(
        "services.human_input_im.dispatcher._build_feishu_channel",
        lambda config: _FakeChannel(),
    )

    dispatcher = HumanInputIMDispatcher()
    dispatcher.send_form_notification(
        config=HumanInputIMProviderConfig(
            provider=HumanInputIMProvider.FEISHU,
            ingress_mode=HumanInputIMIngressMode.WEBHOOK,
            app_id="app-id",
            app_secret="app-secret",
        ),
        job=HumanInputIMNotificationJob(
            form_id="form-1",
            node_id="node-1",
            node_title="Approval",
            rendered_content="Please review",
            fields=(HumanInputIMField(name="comment", label="Comment", field_type="paragraph", required=False),),
            actions=(HumanInputIMAction(id="approve", title="Approve"),),
            recipient=HumanInputIMRecipient(
                account_id="account-1",
                provider="feishu",
                open_id="open-1",
                user_id="user-1",
                form_token="token-1",
            ),
        ),
    )

    assert sent == [
        (
            "open-1",
            {"card": {"schema": "2.0", "body": {"elements": []}}},
            {"receive_id_type": "open_id"},
        )
    ]


def test_dispatcher_falls_back_to_user_id_when_open_id_missing(monkeypatch):
    sent = []

    class _FakeChannel:
        async def send(self, to, message, opts=None):
            sent.append((to, message, opts))
            return SimpleNamespace(success=True, message_id="om_1", error=None)

    monkeypatch.setattr(
        "services.human_input_im.dispatcher.build_feishu_card_payload",
        lambda job: FeishuCardBuildResult(mode="inline_card", payload={"schema": "2.0", "body": {"elements": []}}),
    )
    monkeypatch.setattr(
        "services.human_input_im.dispatcher._build_feishu_channel",
        lambda config: _FakeChannel(),
    )

    dispatcher = HumanInputIMDispatcher()
    dispatcher.send_form_notification(
        config=HumanInputIMProviderConfig(
            provider=HumanInputIMProvider.FEISHU,
            ingress_mode=HumanInputIMIngressMode.STREAM,
            app_id="app-id",
            app_secret="app-secret",
        ),
        job=HumanInputIMNotificationJob(
            form_id="form-1",
            node_id="node-1",
            node_title="Approval",
            rendered_content="Please review",
            fields=(HumanInputIMField(name="comment", label="Comment", field_type="paragraph", required=False),),
            actions=(HumanInputIMAction(id="approve", title="Approve"),),
            recipient=HumanInputIMRecipient(
                account_id="account-1",
                provider="feishu",
                open_id=None,
                user_id="user-1",
                form_token="token-1",
            ),
        ),
    )

    assert sent == [
        (
            "user-1",
            {"card": {"schema": "2.0", "body": {"elements": []}}},
            {"receive_id_type": "user_id"},
        )
    ]
