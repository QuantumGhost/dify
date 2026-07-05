from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import lark_oapi as lark  # type: ignore[import-untyped]
from lark_oapi.api.authen.v1.model.get_user_info_request import GetUserInfoRequest  # type: ignore[import-untyped]
from lark_oapi.api.im.v1.model.create_message_request import CreateMessageRequest  # type: ignore[import-untyped]
from lark_oapi.api.im.v1.model.create_message_request_body import (  # type: ignore[import-untyped]
    CreateMessageRequestBody,
)
from lark_oapi.api.im.v1.model.patch_message_request import PatchMessageRequest  # type: ignore[import-untyped]
from lark_oapi.api.im.v1.model.patch_message_request_body import PatchMessageRequestBody  # type: ignore[import-untyped]
from lark_oapi.core.model import RequestOption  # type: ignore[import-untyped]
from lark_oapi.event.callback.model.p2_card_action_trigger import (  # type: ignore[import-untyped]
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from configs import dify_config
from core.workflow.human_input_policy import resolve_variable_select_input_options
from core.workflow.nodes.human_input.entities import (
    FileInputConfig,
    FileListInputConfig,
    FormDefinition,
    FormInputConfig,
    ParagraphInputConfig,
    SelectInputConfig,
)
from libs.datetime_utils import naive_utc_now
from models.human_input import EmailMemberRecipientPayload, HumanInputForm, HumanInputFormRecipient, RecipientType
from models.human_input_feishu import (
    HumanInputFeishuDelivery,
    HumanInputFeishuDeliveryMode,
    HumanInputFeishuDeliveryStatus,
)
from services.member_contact_service import MemberContactService

if TYPE_CHECKING:
    from services.human_input_service import HumanInputService

logger = logging.getLogger(__name__)
OUTPUT_PLACEHOLDER_PATTERN = re.compile(r"{{#\$output\.([^#{}]+)#}}")
TEMPLATE_VARIABLE_PATTERN = re.compile(r"{{#([^#{}]+)#}}")
FILE_PLACEHOLDER_PROMPT = "[file]"
FILE_LIST_PLACEHOLDER_PROMPT = "[files]"


@dataclass(frozen=True)
class FeishuCardRenderResult:
    mode: HumanInputFeishuDeliveryMode
    content: dict[str, Any]


def build_feishu_client() -> lark.Client | None:
    if not dify_config.FEISHU_APP_ID or not dify_config.FEISHU_APP_SECRET:
        return None
    return lark.Client.builder().app_id(dify_config.FEISHU_APP_ID).app_secret(dify_config.FEISHU_APP_SECRET).build()


class HumanInputFeishuService:
    def __init__(
        self,
        *,
        client: lark.Client | None = None,
        session_factory: sessionmaker[Session] | None = None,
        human_input_service: HumanInputService | None = None,
    ) -> None:
        self._client = client
        self._session_factory = session_factory
        self._human_input_service = human_input_service

    def is_configured(self) -> bool:
        return bool(dify_config.FEISHU_APP_ID and dify_config.FEISHU_APP_SECRET)

    def dispatch_form_notifications(
        self,
        *,
        session: Session,
        form: HumanInputForm,
        variable_pool=None,
    ) -> None:
        if not self.is_configured():
            return

        definition = self._load_form_definition(form)
        resolved_inputs = resolve_variable_select_input_options(definition.inputs, variable_pool=variable_pool)
        definition = definition.model_copy(
            update={
                "inputs": resolved_inputs,
                "form_content": self._render_form_body_template(
                    definition.form_content,
                    variable_pool=variable_pool,
                ),
                "rendered_content": self._render_form_body_template(
                    definition.rendered_content,
                    variable_pool=variable_pool,
                ),
            }
        )

        recipients = session.scalars(
            select(HumanInputFormRecipient).where(
                HumanInputFormRecipient.form_id == form.id,
                HumanInputFormRecipient.recipient_type == RecipientType.EMAIL_MEMBER,
            )
        ).all()
        for recipient in recipients:
            self._send_to_member_recipient(
                session=session,
                form=form,
                definition=definition,
                recipient=recipient,
            )

        session.commit()

    def handle_card_action(self, payload: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        event = payload.event
        if event is None or event.action is None or event.operator is None:
            return self._toast_response("error", "Invalid card payload.")

        action_value = event.action.value or {}
        form_id = action_value.get("form_id")
        action_id = action_value.get("action_id")
        if not isinstance(form_id, str) or not isinstance(action_id, str):
            return self._toast_response("error", "Invalid card payload.")

        operator_open_id = event.operator.open_id or ""
        session_factory = self._session_factory
        if session_factory is None:
            raise RuntimeError("session_factory is required for callback handling")

        with session_factory() as session:
            from services.human_input_service import FormExpiredError, FormSubmittedError, InvalidFormDataError

            delivery = session.scalar(
                select(HumanInputFeishuDelivery).where(
                    HumanInputFeishuDelivery.form_id == form_id,
                    HumanInputFeishuDelivery.open_id == operator_open_id,
                )
            )
            if delivery is None:
                return self._toast_response("error", "You are not allowed to submit this task.")

            recipient = session.get(HumanInputFormRecipient, delivery.recipient_id)
            if recipient is None or recipient.access_token is None:
                return self._toast_response("error", "This task is unavailable.")

            record = self._human_input_form_service()._form_repository.get_by_token(recipient.access_token)
            if record is None:
                return self._toast_response("error", "This task is unavailable.")

            if delivery.status == HumanInputFeishuDeliveryStatus.COMPLETED or record.submitted:
                self._sync_completed_delivery_cards(
                    session=session,
                    form_id=form_id,
                    current_message_id=getattr(delivery, "message_id", None),
                    record=record,
                )
                return self._result_response(record)

            try:
                self._human_input_form_service().submit_form_by_token(
                    RecipientType.EMAIL_MEMBER,
                    recipient.access_token,
                    action_id,
                    event.action.form_value or {},
                    submission_user_id=delivery.account_id,
                )
            except FormSubmittedError:
                updated_record = self._human_input_form_service()._form_repository.get_by_token(recipient.access_token)
                if updated_record is None:
                    return self._toast_response("info", "This task has already been completed.")
                self._sync_completed_delivery_cards(
                    session=session,
                    form_id=form_id,
                    current_message_id=getattr(delivery, "message_id", None),
                    record=updated_record,
                )
                return self._result_response(updated_record)
            except FormExpiredError:
                return self._toast_response("error", "This task has expired.")
            except InvalidFormDataError as exc:
                return self._toast_response("error", exc.description or "Invalid form data.")

            updated_record = self._human_input_form_service()._form_repository.get_by_token(recipient.access_token)
            if updated_record is None:
                return self._toast_response("success", "Submitted.")
            self._sync_completed_delivery_cards(
                session=session,
                form_id=form_id,
                current_message_id=getattr(delivery, "message_id", None),
                record=updated_record,
            )
            return self._result_response(updated_record)

    def get_user_info(self, user_access_token: str):
        client = self._require_client()
        authen_api = client.authen
        assert authen_api is not None

        response = authen_api.v1.user_info.get(
            GetUserInfoRequest.builder().build(),
            RequestOption.builder().user_access_token(user_access_token).build(),
        )
        return response.data

    def render_form_card(
        self,
        *,
        form_id: str,
        recipient_id: str,
        form_link: str,
        definition: FormDefinition,
    ) -> FeishuCardRenderResult:
        if not self._supports_interactive_card(definition):
            return FeishuCardRenderResult(
                mode=HumanInputFeishuDeliveryMode.LINK_FALLBACK,
                content=self._build_link_fallback_card(form_link=form_link, definition=definition),
            )

        return FeishuCardRenderResult(
            mode=HumanInputFeishuDeliveryMode.INTERACTIVE_CARD,
            content=self._build_interactive_card(
                form_id=form_id,
                recipient_id=recipient_id,
                definition=definition,
            ),
        )

    @staticmethod
    def mark_delivery_completed(session: Session, *, form_id: str, recipient_id: str) -> None:
        delivery = session.scalar(
            select(HumanInputFeishuDelivery).where(
                HumanInputFeishuDelivery.form_id == form_id,
                HumanInputFeishuDelivery.recipient_id == recipient_id,
            )
        )
        if delivery is None:
            return

        delivery.status = HumanInputFeishuDeliveryStatus.COMPLETED
        delivery.completed_at = naive_utc_now()

    def _send_to_member_recipient(
        self,
        *,
        session: Session,
        form: HumanInputForm,
        definition: FormDefinition,
        recipient: HumanInputFormRecipient,
    ) -> None:
        payload = EmailMemberRecipientPayload.model_validate_json(recipient.recipient_payload)
        binding = MemberContactService().resolve_workspace_member_binding(
            session,
            tenant_id=form.tenant_id,
            account_id=payload.user_id,
        )
        if binding is None or not binding.feishu_open_id or not recipient.access_token:
            return

        render_result = self.render_form_card(
            form_id=form.id,
            recipient_id=recipient.id,
            form_link=self._build_form_link(recipient.access_token),
            definition=definition,
        )
        delivery = self._get_or_create_delivery(
            session=session,
            form=form,
            recipient=recipient,
            binding=binding,
            delivery_mode=render_result.mode,
        )
        delivery.card_payload = json.dumps(render_result.content, ensure_ascii=False)
        delivery.status = HumanInputFeishuDeliveryStatus.PENDING
        delivery.failure_reason = None

        try:
            client = self._require_client()
            im_api = client.im
            assert im_api is not None

            response = im_api.v1.message.create(
                CreateMessageRequest.builder()
                .receive_id_type("open_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(binding.feishu_open_id)
                    .msg_type("interactive")
                    .content(json.dumps(render_result.content, ensure_ascii=False))
                    .uuid(self._build_message_uuid(form_id=form.id, recipient_id=recipient.id))
                    .build()
                )
                .build()
            )
        except Exception as exc:
            logger.exception(
                "Feishu message send raised exception, form_id=%s recipient_id=%s account_id=%s open_id=%s",
                form.id,
                recipient.id,
                binding.account_id,
                binding.feishu_open_id,
            )
            delivery.status = HumanInputFeishuDeliveryStatus.FAILED
            delivery.failure_reason = str(exc)
            return

        message_id = response.data.message_id if response.data is not None else None
        if response.code != 0 or not message_id:
            error_summary = self._summarize_send_failure(response)
            delivery.status = HumanInputFeishuDeliveryStatus.FAILED
            delivery.failure_reason = json.dumps(error_summary, ensure_ascii=False, default=str)
            logger.error(
                "Feishu message send failed, form_id=%s recipient_id=%s account_id=%s open_id=%s error=%s",
                form.id,
                recipient.id,
                binding.account_id,
                binding.feishu_open_id,
                delivery.failure_reason,
            )
            return

        delivery.message_id = message_id
        delivery.status = HumanInputFeishuDeliveryStatus.SENT

    def _get_or_create_delivery(
        self,
        *,
        session: Session,
        form: HumanInputForm,
        recipient: HumanInputFormRecipient,
        binding,
        delivery_mode: HumanInputFeishuDeliveryMode,
    ) -> HumanInputFeishuDelivery:
        delivery = session.scalar(
            select(HumanInputFeishuDelivery).where(
                HumanInputFeishuDelivery.form_id == form.id,
                HumanInputFeishuDelivery.recipient_id == recipient.id,
            )
        )
        if delivery is None:
            delivery = HumanInputFeishuDelivery(
                tenant_id=form.tenant_id,
                form_id=form.id,
                recipient_id=recipient.id,
                member_contact_id=binding.contact_id,
                account_id=binding.account_id,
                open_id=binding.feishu_open_id,
                delivery_mode=delivery_mode,
                status=HumanInputFeishuDeliveryStatus.PENDING,
            )
            session.add(delivery)
        else:
            delivery.member_contact_id = binding.contact_id
            delivery.account_id = binding.account_id
            delivery.open_id = binding.feishu_open_id
            delivery.delivery_mode = delivery_mode
        return delivery

    def _require_client(self) -> lark.Client:
        client = self._client or build_feishu_client()
        if client is None:
            raise RuntimeError("Feishu is not configured")
        return client

    def _human_input_form_service(self):
        from services.human_input_service import HumanInputService

        if self._human_input_service is not None:
            return self._human_input_service
        if self._session_factory is None:
            raise RuntimeError("session_factory is required for callback handling")
        return HumanInputService(self._session_factory)

    @staticmethod
    def _load_form_definition(form: HumanInputForm) -> FormDefinition:
        return FormDefinition.model_validate(json.loads(form.form_definition))

    @staticmethod
    def _build_form_link(token: str) -> str:
        base_url = dify_config.APP_WEB_URL.rstrip("/")
        return f"{base_url}/form/{token}"

    @staticmethod
    def _build_message_uuid(*, form_id: str, recipient_id: str) -> str:
        digest = hashlib.blake2s(f"{form_id}:{recipient_id}".encode(), digest_size=16).hexdigest()
        return f"hitl:{digest}"

    @staticmethod
    def _render_form_body_template(body: str, *, variable_pool) -> str:
        if variable_pool is None:
            return body
        return variable_pool.convert_template(body).text

    @classmethod
    def _summarize_send_failure(cls, response: Any) -> dict[str, Any]:
        error = cls._to_loggable_payload(getattr(response, "error", None))
        log_id = cls._extract_log_id(response, error)
        troubleshooter = cls._extract_troubleshooter(response, error)
        summary = {
            "code": getattr(response, "code", None),
            "msg": getattr(response, "msg", None),
            "log_id": log_id,
            "troubleshooter": troubleshooter,
            "error": error,
            "data": cls._to_loggable_payload(getattr(response, "data", None)),
            "raw_content": cls._decode_raw_content(getattr(getattr(response, "raw", None), "content", None)),
        }
        return {key: value for key, value in summary.items() if value not in (None, "", [], {})}

    @classmethod
    def _extract_log_id(cls, response: Any, error: Any) -> str | None:
        response_log_id = getattr(response, "get_log_id", None)
        if callable(response_log_id):
            try:
                log_id = response_log_id()
            except Exception:
                log_id = None
            if log_id:
                return str(log_id)

        if isinstance(error, dict):
            log_id = error.get("log_id")
            return str(log_id) if log_id else None

        log_id = getattr(error, "log_id", None)
        return str(log_id) if log_id else None

    @classmethod
    def _extract_troubleshooter(cls, response: Any, error: Any) -> str | None:
        response_troubleshooter = getattr(response, "get_troubleshooter", None)
        if callable(response_troubleshooter):
            try:
                troubleshooter = response_troubleshooter()
            except Exception:
                troubleshooter = None
            if troubleshooter:
                return str(troubleshooter)

        if isinstance(error, dict):
            troubleshooter = error.get("troubleshooter")
            return str(troubleshooter) if troubleshooter else None

        troubleshooter = getattr(error, "troubleshooter", None)
        return str(troubleshooter) if troubleshooter else None

    @classmethod
    def _to_loggable_payload(cls, value: Any) -> Any:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, bytes):
            return cls._decode_raw_content(value)
        if isinstance(value, list | tuple):
            return [cls._to_loggable_payload(item) for item in value]
        if isinstance(value, dict):
            return {str(key): cls._to_loggable_payload(item) for key, item in value.items()}

        payload = {
            key: cls._to_loggable_payload(item)
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }
        return payload or str(value)

    @staticmethod
    def _decode_raw_content(raw_content: bytes | None) -> str | None:
        if raw_content is None:
            return None
        return raw_content.decode("utf-8", errors="replace")

    @staticmethod
    def _supports_interactive_card(definition: FormDefinition) -> bool:
        if not definition.user_actions or len(definition.user_actions) > 2:
            return False
        for form_input in definition.inputs:
            if isinstance(form_input, FileInputConfig | FileListInputConfig):
                return False
            if not isinstance(form_input, ParagraphInputConfig | SelectInputConfig):
                return False
        return True

    def _build_interactive_card(
        self,
        *,
        form_id: str,
        recipient_id: str,
        definition: FormDefinition,
    ) -> dict[str, Any]:
        form_elements = self._build_interactive_form_elements(definition)
        form_elements.append(
            self._build_action_buttons(
                form_id=form_id,
                recipient_id=recipient_id,
                definition=definition,
            )
        )

        return {
            "schema": "2.0",
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": definition.node_title or "Human Input",
                },
                "template": "blue",
            },
            "body": {
                "elements": [
                    {
                        "tag": "form",
                        "name": f"form_{form_id}",
                        "elements": form_elements,
                    },
                ]
            },
        }

    @classmethod
    def _build_interactive_form_elements(cls, definition: FormDefinition) -> list[dict[str, Any]]:
        template = cls._resolve_interactive_form_template(definition)
        input_elements = {
            form_input.output_variable_name: cls._build_input_element(form_input) for form_input in definition.inputs
        }
        used_inputs: set[str] = set()
        form_elements: list[dict[str, Any]] = []
        cursor = 0

        for match in OUTPUT_PLACEHOLDER_PATTERN.finditer(template):
            output_variable_name = match.group(1)
            markdown_segment = template[cursor : match.start()]
            if markdown_segment:
                form_elements.append(cls._build_markdown_element(markdown_segment))

            cursor = match.end()
            if output_variable_name in used_inputs or output_variable_name not in input_elements:
                continue

            form_elements.append(input_elements[output_variable_name])
            used_inputs.add(output_variable_name)

        tail_segment = template[cursor:]
        if tail_segment:
            form_elements.append(cls._build_markdown_element(tail_segment))

        for form_input in definition.inputs:
            if form_input.output_variable_name in used_inputs:
                continue
            form_elements.append(input_elements[form_input.output_variable_name])

        return form_elements

    @staticmethod
    def _resolve_interactive_form_template(definition: FormDefinition) -> str:
        template = definition.rendered_content or definition.form_content
        if OUTPUT_PLACEHOLDER_PATTERN.search(template):
            return template
        if definition.form_content and OUTPUT_PLACEHOLDER_PATTERN.search(definition.form_content):
            projected_template = HumanInputFeishuService._project_output_placeholders(
                rendered_content=template,
                form_content=definition.form_content,
            )
            # Keep rendered text on projection failure so Feishu cards never leak raw workflow templates.
            return projected_template or template
        return template

    @staticmethod
    def _project_output_placeholders(*, rendered_content: str, form_content: str) -> str | None:
        pattern_parts: list[str] = []
        output_placeholders: list[tuple[str, str]] = []
        matches = list(TEMPLATE_VARIABLE_PATTERN.finditer(form_content))
        cursor = 0

        for match_index, match in enumerate(matches):
            left_literal = form_content[cursor : match.start()]
            pattern_parts.append(re.escape(left_literal))
            placeholder = match.group(0)
            if OUTPUT_PLACEHOLDER_PATTERN.fullmatch(placeholder):
                next_match = matches[match_index + 1] if match_index + 1 < len(matches) else None
                right_literal = form_content[match.end() : next_match.start()] if next_match is not None else ""
                is_adjacent_to_previous_placeholder = match_index > 0 and left_literal == ""
                is_adjacent_to_next_placeholder = next_match is not None and right_literal == ""

                if is_adjacent_to_previous_placeholder or is_adjacent_to_next_placeholder:
                    pattern_parts.append(".*?")
                else:
                    group_name = f"output_{match_index}"
                    pattern_parts.append(f"(?P<{group_name}>.*?)")
                    output_placeholders.append((group_name, placeholder))
            else:
                pattern_parts.append(".*?")
            cursor = match.end()

        pattern_parts.append(re.escape(form_content[cursor:]))
        rendered_match = re.fullmatch("".join(pattern_parts), rendered_content, flags=re.DOTALL)
        if rendered_match is None:
            return None

        projected_parts: list[str] = []
        cursor = 0
        for group_name, placeholder in output_placeholders:
            start, end = rendered_match.span(group_name)
            projected_parts.append(rendered_content[cursor:start])
            projected_parts.append(placeholder)
            cursor = end

        projected_parts.append(rendered_content[cursor:])
        return "".join(projected_parts)

    @staticmethod
    def _build_markdown_element(content: str) -> dict[str, Any]:
        return {
            "tag": "markdown",
            "content": content,
        }

    @staticmethod
    def _build_input_element(form_input: FormInputConfig) -> dict[str, Any]:
        if isinstance(form_input, ParagraphInputConfig):
            default_value = ""
            if form_input.default and form_input.default.type.value == "constant":
                default_value = form_input.default.value
            return {
                "tag": "input",
                "name": form_input.output_variable_name,
                "label": {
                    "tag": "plain_text",
                    "content": form_input.output_variable_name,
                },
                "input_type": "multiline_text",
                "rows": 3,
                "default_value": default_value,
                "width": "fill",
            }

        if isinstance(form_input, SelectInputConfig):
            options = [
                {
                    "text": {
                        "tag": "plain_text",
                        "content": option,
                    },
                    "value": option,
                }
                for option in form_input.option_source.value
            ]
            return {
                "tag": "select_static",
                "name": form_input.output_variable_name,
                "placeholder": {
                    "tag": "plain_text",
                    "content": form_input.output_variable_name,
                },
                "width": "fill",
                "options": options,
            }

        raise TypeError(f"Unsupported form input type: {type(form_input).__name__}")

    @staticmethod
    def _build_action_buttons(
        *,
        form_id: str,
        recipient_id: str,
        definition: FormDefinition,
    ) -> dict[str, Any]:
        columns = []
        for index, action in enumerate(definition.user_actions):
            columns.append(
                {
                    "tag": "column",
                    "width": "auto",
                    "elements": [
                        {
                            "tag": "button",
                            "name": f"action_{action.id}",
                            "text": {
                                "tag": "plain_text",
                                "content": action.title,
                            },
                            "type": "primary_filled" if index == 0 else "default",
                            "form_action_type": "submit",
                            "behaviors": [
                                {
                                    "type": "callback",
                                    "value": {
                                        "form_id": form_id,
                                        "recipient_id": recipient_id,
                                        "action_id": action.id,
                                    },
                                }
                            ],
                        }
                    ],
                }
            )
        return {
            "tag": "column_set",
            "horizontal_align": "right",
            "columns": columns,
        }

    def _build_link_fallback_card(self, *, form_link: str, definition: FormDefinition) -> dict[str, Any]:
        content = self._render_form_content_with_placeholder_prompts(definition)
        return {
            "schema": "2.0",
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": definition.node_title or "Human Input",
                },
                "template": "orange",
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "Open approval form",
                        },
                        "type": "primary_filled",
                        "behaviors": [
                            {
                                "type": "open_url",
                                "default_url": form_link,
                                "pc_url": form_link,
                                "ios_url": form_link,
                                "android_url": form_link,
                            }
                        ],
                    },
                ]
            },
        }

    @classmethod
    def _render_form_content_with_placeholder_prompts(cls, definition: FormDefinition) -> str:
        rendered_content = definition.rendered_content or definition.form_content
        for form_input in definition.inputs:
            prompt = cls._get_output_placeholder_prompt(form_input)
            if prompt is None:
                continue

            placeholder = "{{#$output." + form_input.output_variable_name + "#}}"
            rendered_content = rendered_content.replace(placeholder, prompt)

        return rendered_content

    def _result_response(self, record) -> P2CardActionTriggerResponse:
        card_data = self._build_result_card_data(record)
        return P2CardActionTriggerResponse(
            {
                "toast": {
                    "type": "success",
                    "content": "Submitted.",
                },
                "card": {
                    "type": "raw",
                    "data": card_data,
                },
            }
        )

    def _build_result_card_data(self, record) -> dict[str, Any]:
        definition = record.definition
        rendered_content = self._render_result_form_content_with_outputs(
            definition=definition,
            submitted_data=record.submitted_data or {},
        )
        elements: list[dict[str, Any]] = [
            {
                "tag": "markdown",
                "content": rendered_content,
            }
        ]
        if record.selected_action_id:
            action_title = next(
                (action.title for action in definition.user_actions if action.id == record.selected_action_id),
                record.selected_action_id,
            )
            elements.append(
                {
                    "tag": "markdown",
                    "content": f"**Action:** {action_title}",
                }
            )

        for key, value in (record.submitted_data or {}).items():
            rendered_value = self._render_result_output_value(
                value=value,
                form_input=next(
                    (form_input for form_input in definition.inputs if form_input.output_variable_name == key),
                    None,
                ),
            )
            elements.append(
                {
                    "tag": "markdown",
                    "content": f"**{key}:** {rendered_value}",
                }
            )

        return {
            "schema": "2.0",
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": definition.node_title or "Human Input",
                },
                "template": "green",
            },
            "body": {
                "elements": elements,
            },
        }

    def _render_result_form_content_with_outputs(
        self,
        *,
        definition: FormDefinition,
        submitted_data: Mapping[str, Any],
    ) -> str:
        rendered_content = definition.rendered_content or definition.form_content
        for form_input in definition.inputs:
            field_name = form_input.output_variable_name
            placeholder = "{{#$output." + field_name + "#}}"
            replacement = self._render_result_output_value(
                value=submitted_data.get(field_name),
                form_input=form_input,
            )
            rendered_content = rendered_content.replace(placeholder, replacement)
        return rendered_content

    @staticmethod
    def _get_output_placeholder_prompt(form_input: FormInputConfig | None) -> str | None:
        if isinstance(form_input, FileInputConfig):
            return FILE_PLACEHOLDER_PROMPT

        if isinstance(form_input, FileListInputConfig):
            return FILE_LIST_PLACEHOLDER_PROMPT

        return None

    @classmethod
    def _render_result_output_value(cls, *, value: Any, form_input: FormInputConfig | None) -> str:
        if value is None:
            return ""

        prompt = cls._get_output_placeholder_prompt(form_input)
        if prompt is not None:
            return prompt

        if isinstance(form_input, ParagraphInputConfig | SelectInputConfig):
            return str(value)

        if isinstance(value, dict | list):
            return json.dumps(value, ensure_ascii=False)

        return str(value)

    def _sync_completed_delivery_cards(
        self,
        *,
        session: Session,
        form_id: str,
        current_message_id: str | None,
        record,
    ) -> None:
        deliveries = session.scalars(
            select(HumanInputFeishuDelivery).where(HumanInputFeishuDelivery.form_id == form_id)
        ).all()
        if not deliveries:
            return

        completed_at = getattr(record, "submitted_at", None) or naive_utc_now()
        card_content = json.dumps(self._build_result_card_data(record), ensure_ascii=False)
        for delivery in deliveries:
            delivery.status = HumanInputFeishuDeliveryStatus.COMPLETED
            delivery.completed_at = completed_at
            message_id = getattr(delivery, "message_id", None)

            if not message_id or message_id == current_message_id:
                continue

            self._patch_delivery_message(
                delivery=delivery,
                form_id=form_id,
                content=card_content,
            )

    def _patch_delivery_message(self, *, delivery: HumanInputFeishuDelivery, form_id: str, content: str) -> None:
        try:
            client = self._require_client()
            im_api = client.im
            assert im_api is not None

            response = im_api.v1.message.patch(
                PatchMessageRequest.builder()
                .message_id(delivery.message_id)
                .request_body(PatchMessageRequestBody.builder().content(content).build())
                .build()
            )
        except Exception:
            logger.exception(
                "Feishu message patch raised exception, form_id=%s recipient_id=%s message_id=%s",
                form_id,
                delivery.recipient_id,
                delivery.message_id,
            )
            return

        if response.code != 0:
            logger.error(
                "Feishu message patch failed, form_id=%s recipient_id=%s message_id=%s error=%s",
                form_id,
                delivery.recipient_id,
                delivery.message_id,
                json.dumps(self._summarize_send_failure(response), ensure_ascii=False, default=str),
            )

    @staticmethod
    def _toast_response(level: str, content: str) -> P2CardActionTriggerResponse:
        return P2CardActionTriggerResponse(
            {
                "toast": {
                    "type": level,
                    "content": content,
                }
            }
        )
