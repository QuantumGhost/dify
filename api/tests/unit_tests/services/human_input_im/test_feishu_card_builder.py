from __future__ import annotations

from services.human_input_im.entities import (
    HumanInputIMAction,
    HumanInputIMField,
    HumanInputIMNotificationJob,
    HumanInputIMRecipient,
    HumanInputIMSelectOption,
)
from services.human_input_im.providers.feishu_card_builder import build_feishu_card_payload


def test_build_feishu_card_payload_renders_inline_form_for_supported_fields():
    job = HumanInputIMNotificationJob(
        form_id="form-1",
        node_id="node-1",
        node_title="Approval",
        rendered_content="**Please review**",
        fields=[
            HumanInputIMField(
                name="comment",
                label="Comment",
                field_type="paragraph",
                required=False,
                default_value="prefill",
            ),
            HumanInputIMField(
                name="decision",
                label="Decision",
                field_type="select",
                required=True,
                options=(
                    HumanInputIMSelectOption(label="approve", value="approve"),
                    HumanInputIMSelectOption(label="reject", value="reject"),
                ),
                default_value="approve",
            ),
        ],
        actions=[
            HumanInputIMAction(id="approve", title="Approve"),
            HumanInputIMAction(id="reject", title="Reject"),
        ],
        recipient=HumanInputIMRecipient(
            account_id="account-1",
            provider="feishu",
            open_id="open-1",
            user_id="user-1",
            form_token="token-1",
        ),
    )

    result = build_feishu_card_payload(job)

    assert result.mode == "inline_card"
    assert result.payload["schema"] == "2.0"
    elements = result.payload["body"]["elements"]
    assert elements[0]["tag"] == "markdown"
    assert elements[1]["tag"] == "form"
    form_elements = elements[1]["elements"]
    assert form_elements[0]["tag"] == "input"
    assert form_elements[0]["input_type"] == "multiline_text"
    assert form_elements[1]["tag"] == "select_static"
    buttons = [element for element in form_elements if element.get("tag") == "button"]
    assert [button["name"] for button in buttons] == ["approve", "reject"]
    assert buttons[0]["behaviors"][0]["value"]["form_token"] == "token-1"


def test_build_feishu_card_payload_falls_back_to_link_for_unsupported_fields():
    job = HumanInputIMNotificationJob(
        form_id="form-1",
        node_id="node-1",
        node_title="Approval",
        rendered_content="Please upload evidence",
        fields=[
            HumanInputIMField(
                name="attachment",
                label="Attachment",
                field_type="file",
                required=True,
            ),
        ],
        actions=[HumanInputIMAction(id="approve", title="Approve")],
        recipient=HumanInputIMRecipient(
            account_id="account-1",
            provider="feishu",
            open_id="open-1",
            user_id="user-1",
            form_token="token-1",
        ),
    )

    result = build_feishu_card_payload(job)

    assert result.mode == "summary_card_with_link"
    elements = result.payload["body"]["elements"]
    assert elements[0]["tag"] == "markdown"
    assert elements[1]["tag"] == "button"
    assert elements[1]["behaviors"][0]["type"] == "open_url"
    assert "token-1" in elements[1]["behaviors"][0]["default_url"]
