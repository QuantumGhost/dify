from __future__ import annotations

from services.human_input_im.entities import (
    FeishuCardBuildResult,
    HumanInputIMField,
    HumanInputIMNotificationJob,
)


def build_feishu_card_payload(job: HumanInputIMNotificationJob) -> FeishuCardBuildResult:
    if _requires_link_fallback(job.fields):
        return FeishuCardBuildResult(
            mode="summary_card_with_link",
            payload={
                "schema": "2.0",
                "body": {
                    "direction": "vertical",
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": job.rendered_content,
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "Open Form"},
                            "type": "primary",
                            "behaviors": [
                                {
                                    "type": "open_url",
                                    "default_url": f"{_app_web_url()}/form/{job.recipient.form_token}",
                                }
                            ],
                        },
                    ],
                },
            },
        )

    form_elements: list[dict] = []
    for field in job.fields:
        form_elements.append(_build_form_element(field))
    for action in job.actions:
        form_elements.append(
            {
                "tag": "button",
                "name": action.id,
                "text": {"tag": "plain_text", "content": action.title},
                "type": "primary",
                "form_action_type": "submit",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {
                            "form_token": job.recipient.form_token,
                            "action_id": action.id,
                        },
                    }
                ],
            }
        )

    return FeishuCardBuildResult(
        mode="inline_card",
        payload={
            "schema": "2.0",
            "body": {
                "direction": "vertical",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": job.rendered_content,
                    },
                    {
                        "tag": "form",
                        "name": f"hitl_form_{job.form_id}",
                        "elements": form_elements,
                    },
                ],
            },
        },
    )


def _requires_link_fallback(fields: tuple[HumanInputIMField, ...]) -> bool:
    return any(field.field_type in {"file", "file_list"} for field in fields)


def _build_form_element(field: HumanInputIMField) -> dict:
    if field.field_type == "paragraph":
        return {
            "tag": "input",
            "name": field.name,
            "label": {"tag": "plain_text", "content": field.label},
            "placeholder": {"tag": "plain_text", "content": field.label},
            "required": field.required,
            "default_value": field.default_value or "",
            "input_type": "multiline_text",
            "rows": 5,
            "auto_resize": True,
        }

    if field.field_type == "select":
        return {
            "tag": "select_static",
            "name": field.name,
            "placeholder": {"tag": "plain_text", "content": field.label},
            "required": field.required,
            "initial_option": field.default_value or "",
            "options": [
                {
                    "text": {"tag": "plain_text", "content": option.label},
                    "value": option.value,
                }
                for option in field.options
            ],
        }

    return {
        "tag": "input",
        "name": field.name,
        "label": {"tag": "plain_text", "content": field.label},
        "placeholder": {"tag": "plain_text", "content": field.label},
        "required": field.required,
        "default_value": field.default_value or "",
    }


def _app_web_url() -> str:
    from configs import dify_config

    return dify_config.APP_WEB_URL.rstrip("/")
