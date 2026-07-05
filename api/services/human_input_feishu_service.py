from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import lark_oapi as lark  # type: ignore[import-untyped]
from lark_oapi.api.authen.v1.model.get_user_info_request import GetUserInfoRequest  # type: ignore[import-untyped]
from lark_oapi.api.im.v1.model.create_message_request import CreateMessageRequest  # type: ignore[import-untyped]
from lark_oapi.api.im.v1.model.create_message_request_body import (  # type: ignore[import-untyped]
    CreateMessageRequestBody,
)
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
        definition = definition.model_copy(update={"inputs": resolved_inputs})

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
                return self._result_response(updated_record)
            except FormExpiredError:
                return self._toast_response("error", "This task has expired.")
            except InvalidFormDataError as exc:
                return self._toast_response("error", exc.description or "Invalid form data.")

            updated_record = self._human_input_form_service()._form_repository.get_by_token(recipient.access_token)
            if updated_record is None:
                return self._toast_response("success", "Submitted.")
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
                    .uuid(f"{form.id}:{recipient.id}")
                    .build()
                )
                .build()
            )
        except Exception as exc:
            delivery.status = HumanInputFeishuDeliveryStatus.FAILED
            delivery.failure_reason = str(exc)
            return

        message_id = response.data.message_id if response.data is not None else None
        if response.code != 0 or not message_id:
            delivery.status = HumanInputFeishuDeliveryStatus.FAILED
            delivery.failure_reason = response.msg
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
        form_elements = [self._build_input_element(form_input) for form_input in definition.inputs]
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
                        "tag": "markdown",
                        "content": definition.rendered_content or definition.form_content,
                    },
                    {
                        "tag": "form",
                        "name": f"form_{form_id}",
                        "elements": form_elements,
                    },
                ]
            },
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
                "label": {
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
                        "content": definition.rendered_content or definition.form_content,
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

    def _result_response(self, record) -> P2CardActionTriggerResponse:
        definition = record.definition
        elements: list[dict[str, Any]] = [
            {
                "tag": "markdown",
                "content": definition.rendered_content or definition.form_content,
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
            rendered_value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            elements.append(
                {
                    "tag": "markdown",
                    "content": f"**{key}:** {rendered_value}",
                }
            )

        return P2CardActionTriggerResponse(
            {
                "toast": {
                    "type": "success",
                    "content": "Submitted.",
                },
                "card": {
                    "type": "raw",
                    "data": {
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
                    },
                },
            }
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
