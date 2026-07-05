"""Feishu self-built IM provider adapter backed by the official ``lark_oapi`` SDK.

This adapter owns Feishu-specific transport, callback verification, and
provider-local callback parsing. The surrounding application services stay
provider-neutral and only exchange normalized DTOs from ``provider_types``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import uuid4

from lark_oapi import Client
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
    PatchMessageRequest,
    PatchMessageRequestBody,
    PatchMessageResponse,
)
from lark_oapi.core.const import (
    LARK_REQUEST_NONCE,
    LARK_REQUEST_SIGNATURE,
    LARK_REQUEST_TIMESTAMP,
)
from lark_oapi.core.exception import (
    AccessDeniedException,
    AccessTokenException,
    EventException,
    InvalidArgsException,
    ObtainAccessTokenException,
)
from lark_oapi.core.model import RawRequest, RawResponse
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler, EventDispatcherHandlerBuilder

from models.im_delivery import IMMessageCardStatus
from models.im_integration import IMProvider
from services.errors.im_binding import (
    IMBindingValidationError,
    IMProviderCallbackVerificationError,
    IMProviderTransportError,
)
from services.human_input_im.app_config_service import IMAppConfigStatus, IMAppContext
from services.human_input_im.provider_types import (
    IMCardUpdateCommand,
    IMInlineInputDefinition,
    IMInteractionRenderPayload,
    IMParsedProviderSubmission,
    IMParsedSubmissionPayload,
    IMSendCommand,
    IMSendResult,
    IMSubmissionEvent,
)

logger = logging.getLogger(__name__)

_RECEIVE_ID_TYPE_OPEN_ID = "open_id"
_MESSAGE_TYPE_INTERACTIVE = "interactive"


class FeishuMessageTransport(Protocol):
    """Narrow SDK transport seam for message create/patch calls."""

    def create_message(self, client: Client, request: CreateMessageRequest) -> CreateMessageResponse: ...

    def patch_message(self, client: Client, request: PatchMessageRequest) -> PatchMessageResponse: ...


class LarkOAPIFeishuMessageTransport:
    def create_message(self, client: Client, request: CreateMessageRequest) -> CreateMessageResponse:
        if client.im is None or client.im.v1 is None or client.im.v1.message is None:
            raise IMProviderTransportError("feishu IM message service is unavailable on the configured SDK client")
        return client.im.v1.message.create(request)

    def patch_message(self, client: Client, request: PatchMessageRequest) -> PatchMessageResponse:
        if client.im is None or client.im.v1 is None or client.im.v1.message is None:
            raise IMProviderTransportError("feishu IM message service is unavailable on the configured SDK client")
        return client.im.v1.message.patch(request)


class FeishuSDKClientFactory:
    """Build configured SDK clients from the resolved runtime app context."""

    def build(self, app_context: IMAppContext) -> Client:
        if not app_context.app_id or not app_context.app_secret:
            raise IMBindingValidationError("feishu app credentials are not configured")
        return Client.builder().app_id(app_context.app_id).app_secret(app_context.app_secret).build()


class FeishuCallbackDispatcherFactory:
    """Build official SDK callback dispatchers for signed and long-connection payloads."""

    def build_card_action_dispatcher(
        self,
        *,
        app_context: IMAppContext,
        handler,
        require_verification_material: bool = True,
    ) -> EventDispatcherHandler:
        if require_verification_material and not app_context.verification_token:
            raise IMBindingValidationError("feishu callback verification requires LARK_VERIFICATION_TOKEN")
        if require_verification_material and not app_context.encrypt_key:
            raise IMBindingValidationError("feishu callback verification requires LARK_ENCRYPT_KEY")

        return (
            EventDispatcherHandlerBuilder(app_context.encrypt_key or "", app_context.verification_token or "")
            .register_p2_card_action_trigger(handler)
            .build()
        )


class FeishuHumanInputIMProvider:
    """Production Feishu adapter for send/update/verify/parse seams.

    NOTE(QuantumGhost): phase-1 still assumes ``provider_user_id`` stores the
    Feishu ``open_id`` that ``im/v1/messages`` can address directly.
    """

    provider = IMProvider.FEISHU

    def __init__(
        self,
        *,
        client_factory: FeishuSDKClientFactory | None = None,
        transport: FeishuMessageTransport | None = None,
        dispatcher_factory: FeishuCallbackDispatcherFactory | None = None,
    ) -> None:
        self._client_factory = client_factory or FeishuSDKClientFactory()
        self._transport = transport or LarkOAPIFeishuMessageTransport()
        self._dispatcher_factory = dispatcher_factory or FeishuCallbackDispatcherFactory()

    def verify_signature(self, app_context: IMAppContext, payload: bytes, headers: dict[str, str]) -> None:
        dispatcher = self._dispatcher_factory.build_card_action_dispatcher(
            app_context=app_context,
            handler=self._acknowledge_card_action,
        )
        response = dispatcher.do(self._build_raw_request(payload=payload, headers=headers))
        self._raise_on_dispatch_failure(response, default_message="feishu callback verification failed")

    def send_form(self, command: IMSendCommand) -> IMSendResult:
        error = self._validate_send_command(command)
        if error is not None:
            return IMSendResult(provider=command.provider, accepted=False, error=error)

        try:
            client = self._client_factory.build(command.app_context)
            request = CreateMessageRequest.builder().receive_id_type(_RECEIVE_ID_TYPE_OPEN_ID).request_body(
                CreateMessageRequestBody.builder()
                .receive_id(command.recipient_id)
                .msg_type(_MESSAGE_TYPE_INTERACTIVE)
                .content(self._dump_card_content(self._build_form_card(command)))
                .uuid(command.metadata.get("correlation_id") or f"imhi-{uuid4().hex}")
                .build()
            ).build()
            response = self._transport.create_message(client, request)
        except (AccessTokenException, ObtainAccessTokenException, IMProviderTransportError) as exc:
            logger.warning(
                "Feishu IM send failed before provider acceptance, recipient_open_id=%s, form_id=%s, error=%s",
                command.recipient_id,
                command.form_id,
                exc,
            )
            return IMSendResult(provider=command.provider, accepted=False, error=str(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected Feishu IM send failure, recipient_open_id=%s, form_id=%s",
                command.recipient_id,
                command.form_id,
            )
            return IMSendResult(provider=command.provider, accepted=False, error=str(exc))

        if not response.success():
            error_message = self._format_response_error(response, "feishu send message failed")
            logger.warning(
                "Feishu IM send rejected by provider, recipient_open_id=%s, form_id=%s, error=%s",
                command.recipient_id,
                command.form_id,
                error_message,
            )
            return IMSendResult(provider=command.provider, accepted=False, error=error_message)

        provider_message_id = response.data.message_id if response.data is not None else None
        if not provider_message_id:
            error_message = "feishu send message succeeded without returning message_id"
            logger.warning(
                "Feishu IM send returned no message_id, recipient_open_id=%s, form_id=%s",
                command.recipient_id,
                command.form_id,
            )
            return IMSendResult(provider=command.provider, accepted=False, error=error_message)

        return IMSendResult(
            provider=command.provider,
            accepted=True,
            provider_message_id=provider_message_id,
        )

    def parse_submission(self, event: IMSubmissionEvent) -> IMParsedSubmissionPayload:
        payload = event.payload
        action_value = self._as_mapping(payload.get("action_value"))
        action_name = self._as_non_empty_string(payload.get("action_name"))
        provider_action_id = self._extract_provider_action_id(action_value=action_value, action_name=action_name)

        provider_inputs = self._extract_provider_inputs(payload=payload, action_name=action_name)
        return IMParsedSubmissionPayload(
            provider_action_id=provider_action_id,
            provider_inputs=provider_inputs,
        )

    def update_card(self, command: IMCardUpdateCommand) -> None:
        self._validate_card_update_command(command)

        try:
            client = self._client_factory.build(command.app_context)
            request = PatchMessageRequest.builder().message_id(command.provider_message_id).request_body(
                PatchMessageRequestBody.builder()
                .content(self._dump_card_content(self._build_status_card(command)))
                .build()
            ).build()
            response = self._transport.patch_message(client, request)
        except (AccessTokenException, ObtainAccessTokenException, IMProviderTransportError) as exc:
            raise IMProviderTransportError(str(exc)) from exc
        except Exception as exc:
            logger.exception(
                "Unexpected Feishu card update failure, provider_message_id=%s, target_status=%s",
                command.provider_message_id,
                command.target_status,
            )
            raise IMProviderTransportError(str(exc)) from exc

        if not response.success():
            raise IMProviderTransportError(self._format_response_error(response, "feishu patch message failed"))

    def build_challenge_response(self, challenge: str) -> dict[str, str]:
        return {"challenge": challenge}

    def parse_submission_callback(
        self,
        *,
        app_context: IMAppContext,
        payload: bytes,
        headers: dict[str, str] | None = None,
        assume_verified: bool = False,
    ) -> IMParsedProviderSubmission:
        captured_event: dict[str, P2CardActionTrigger] = {}

        def _capture(card_action: P2CardActionTrigger) -> P2CardActionTriggerResponse:
            captured_event["event"] = card_action
            return self._acknowledge_card_action(card_action)

        dispatcher = self._dispatcher_factory.build_card_action_dispatcher(
            app_context=app_context,
            handler=_capture,
            require_verification_material=not assume_verified,
        )

        try:
            if assume_verified:
                dispatcher._do_without_validation(payload)
            else:
                response = dispatcher.do(self._build_raw_request(payload=payload, headers=headers or {}))
                self._raise_on_dispatch_failure(response, default_message="feishu callback parsing failed")
        except (AccessDeniedException, EventException, InvalidArgsException, ValueError) as exc:
            raise IMProviderCallbackVerificationError(str(exc)) from exc

        raw_callback = captured_event.get("event")
        if raw_callback is None:
            raise IMBindingValidationError("feishu callback payload did not contain a card action event")

        event = self._normalize_submission_event(raw_callback)
        return IMParsedProviderSubmission(
            event=event,
            parsed_payload=self.parse_submission(event),
        )

    @staticmethod
    def _acknowledge_card_action(_event: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        return P2CardActionTriggerResponse()

    def _validate_send_command(self, command: IMSendCommand) -> str | None:
        if command.app_context.status != IMAppConfigStatus.CONFIGURED:
            return self._describe_app_context_error(command.app_context, "feishu app context is not configured")
        if not command.app_context.app_id or not command.app_context.app_secret:
            return "feishu app credentials are not configured"
        return None

    def _validate_card_update_command(self, command: IMCardUpdateCommand) -> None:
        if command.app_context.status != IMAppConfigStatus.CONFIGURED:
            raise IMProviderTransportError(
                self._describe_app_context_error(command.app_context, "feishu app context is not configured")
            )
        if not command.app_context.app_id or not command.app_context.app_secret:
            raise IMProviderTransportError("feishu app credentials are not configured")

    def _build_form_card(self, command: IMSendCommand) -> dict[str, Any]:
        interaction_payload = command.interaction_payload
        if interaction_payload is None:
            return self._build_status_like_card(
                title=command.title,
                template="blue",
                lines=[command.content],
            )

        elements: list[dict[str, Any]] = [
            {
                "tag": "markdown",
                "content": interaction_payload.rendered_content or command.content,
            }
        ]

        form_elements = [self._build_input_element(item) for item in interaction_payload.inputs]
        form_actions = [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": action.label},
                "type": "primary" if index == 0 else "default",
                "name": action.provider_action_id,
                "form_action_type": "submit",
                "value": {
                    "action_id": action.provider_action_id,
                    "interaction_id": interaction_payload.interaction_id,
                },
            }
            for index, action in enumerate(interaction_payload.actions)
        ]
        if form_elements or form_actions:
            elements.append(
                {
                    "tag": "form",
                    "name": interaction_payload.interaction_id,
                    "elements": form_elements,
                    "actions": form_actions,
                }
            )

        if interaction_payload.unsupported_input_names:
            unsupported_names = ", ".join(interaction_payload.unsupported_input_names)
            elements.append(
                {
                    "tag": "markdown",
                    "content": (
                        "**File inputs require the web form fallback:** "
                        f"{unsupported_names}\n[Open web form]({interaction_payload.form_link})"
                    ),
                }
            )

        elements.append(
            {
                "tag": "markdown",
                "content": f"[Open web form]({interaction_payload.form_link})",
            }
        )

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": command.title},
            },
            "elements": elements,
        }

    def _build_input_element(self, input_definition: IMInlineInputDefinition) -> dict[str, Any]:
        if input_definition.type == "paragraph":
            return {
                "tag": "input",
                "label": {"tag": "plain_text", "content": input_definition.label},
                "name": input_definition.component_id,
                "multiline": True,
                "placeholder": {
                    "tag": "plain_text",
                    "content": f"Enter {input_definition.label}",
                },
            }

        if input_definition.type == "select":
            return {
                "tag": "select_static",
                "placeholder": {"tag": "plain_text", "content": input_definition.label},
                "name": input_definition.component_id,
                "options": [
                    {
                        "text": {"tag": "plain_text", "content": option.label},
                        "value": option.value,
                    }
                    for option in input_definition.options
                ],
            }

        raise IMBindingValidationError(f"unsupported feishu interaction input type: {input_definition.type}")

    def _build_status_card(self, command: IMCardUpdateCommand) -> dict[str, Any]:
        target_status = IMMessageCardStatus(command.target_status)
        metadata = command.metadata
        title = metadata.get("title") or "Human Input"
        status_copy = {
            IMMessageCardStatus.SUBMITTED: ("green", "Form submitted"),
            IMMessageCardStatus.ERROR: ("red", "Submission failed"),
            IMMessageCardStatus.EXPIRED: ("grey", "Form expired"),
            IMMessageCardStatus.ALREADY_HANDLED: ("orange", "Form already handled"),
            IMMessageCardStatus.PENDING: ("blue", "Awaiting submission"),
        }
        template, headline = status_copy[target_status]
        lines = [headline]

        error_reason = metadata.get("error_reason")
        if error_reason and target_status == IMMessageCardStatus.ERROR:
            lines.append(error_reason)

        form_link = metadata.get("form_link")
        if form_link:
            lines.append(f"[Open web form]({form_link})")

        return self._build_status_like_card(title=title, template=template, lines=lines)

    @staticmethod
    def _build_status_like_card(*, title: str, template: str, lines: list[str]) -> dict[str, Any]:
        content = "\n\n".join(line for line in lines if line)
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": [{"tag": "markdown", "content": content}],
        }

    @staticmethod
    def _dump_card_content(card: dict[str, Any]) -> str:
        return json.dumps(card, ensure_ascii=False, separators=(",", ":"))

    def _normalize_submission_event(self, callback: P2CardActionTrigger) -> IMSubmissionEvent:
        header = callback.header
        event = callback.event
        if header is None or event is None or event.action is None or event.operator is None:
            raise IMBindingValidationError("feishu callback is missing event header, operator, or action")

        event_id = self._require_non_empty_string(header.event_id, "missing feishu callback event_id")
        provider_workspace_id = self._first_non_empty_string(event.operator.tenant_key, header.tenant_key)
        if provider_workspace_id is None:
            raise IMBindingValidationError("missing feishu callback tenant_key")

        provider_user_id = self._first_non_empty_string(event.operator.open_id, event.operator.user_id)
        if provider_user_id is None:
            raise IMBindingValidationError("missing feishu callback operator open_id")

        action_value = dict(event.action.value or {})
        interaction_id = self._extract_interaction_id(action_value)
        if interaction_id is None:
            raise IMBindingValidationError("missing feishu callback interaction_id")

        normalized_payload: dict[str, Any] = {
            "action_name": event.action.name,
            "action_value": action_value,
            "action_tag": event.action.tag,
        }
        if event.action.form_value:
            normalized_payload["form_value"] = dict(event.action.form_value)
        if event.action.input_value is not None:
            normalized_payload["input_value"] = event.action.input_value
        if event.action.option is not None:
            normalized_payload["option"] = event.action.option
        if event.action.options is not None:
            normalized_payload["options"] = list(event.action.options)
        if event.action.checked is not None:
            normalized_payload["checked"] = event.action.checked

        return IMSubmissionEvent(
            provider=IMProvider.FEISHU,
            event_id=event_id,
            provider_user_id=provider_user_id,
            provider_workspace_id=provider_workspace_id,
            interaction_id=interaction_id,
            payload=normalized_payload,
        )

    @staticmethod
    def _extract_provider_action_id(
        *,
        action_value: Mapping[str, Any],
        action_name: str | None,
    ) -> str:
        for key in ("action_id", "provider_action_id", "action"):
            candidate = FeishuHumanInputIMProvider._as_non_empty_string(action_value.get(key))
            if candidate is not None:
                return candidate
        if action_name is not None:
            return action_name
        raise IMBindingValidationError("missing feishu callback action id")

    @staticmethod
    def _extract_provider_inputs(
        *,
        payload: Mapping[str, Any],
        action_name: str | None,
    ) -> dict[str, Any]:
        form_value = FeishuHumanInputIMProvider._as_mapping(payload.get("form_value"))
        if form_value:
            return dict(form_value)

        if action_name is None:
            return {}

        if payload.get("input_value") is not None:
            return {action_name: payload["input_value"]}
        if payload.get("option") is not None:
            return {action_name: payload["option"]}
        if payload.get("options") is not None:
            return {action_name: payload["options"]}
        if payload.get("checked") is not None:
            return {action_name: payload["checked"]}
        return {}

    @staticmethod
    def _extract_interaction_id(action_value: Mapping[str, Any]) -> str | None:
        return FeishuHumanInputIMProvider._as_non_empty_string(action_value.get("interaction_id"))

    @staticmethod
    def _build_raw_request(payload: bytes, headers: dict[str, str]) -> RawRequest:
        raw_request = RawRequest()
        raw_request.uri = "/human-input-im/feishu"
        raw_request.body = payload
        normalized_headers = {key.lower(): value for key, value in headers.items()}
        for expected_key in (LARK_REQUEST_TIMESTAMP, LARK_REQUEST_NONCE, LARK_REQUEST_SIGNATURE):
            expected_value = headers.get(expected_key) or normalized_headers.get(expected_key.lower())
            if expected_value:
                raw_request.headers[expected_key] = expected_value
        return raw_request

    @staticmethod
    def _raise_on_dispatch_failure(response: RawResponse, *, default_message: str) -> None:
        if response.status_code == 200:
            return

        message = default_message
        if response.content:
            try:
                body = json.loads(response.content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = response.content.decode("utf-8", errors="replace")
            else:
                candidate = body.get("msg")
                if isinstance(candidate, str) and candidate:
                    message = candidate

        raise IMProviderCallbackVerificationError(message)

    @staticmethod
    def _describe_app_context_error(app_context: IMAppContext, default_message: str) -> str:
        if app_context.errors:
            return "; ".join(app_context.errors)
        return default_message

    @staticmethod
    def _format_response_error(response: CreateMessageResponse | PatchMessageResponse, prefix: str) -> str:
        details: list[str] = [prefix]
        if response.code is not None:
            details.append(f"code={response.code}")
        if response.msg:
            details.append(f"msg={response.msg}")
        log_id = response.get_log_id()
        if log_id:
            details.append(f"log_id={log_id}")
        troubleshooter = response.get_troubleshooter()
        if troubleshooter:
            details.append(f"troubleshooter={troubleshooter}")
        return ", ".join(details)

    @staticmethod
    def _as_mapping(value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        return {}

    @staticmethod
    def _as_non_empty_string(value: Any) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None

    @staticmethod
    def _first_non_empty_string(*values: Any) -> str | None:
        for value in values:
            resolved = FeishuHumanInputIMProvider._as_non_empty_string(value)
            if resolved is not None:
                return resolved
        return None

    @staticmethod
    def _require_non_empty_string(value: Any, error_message: str) -> str:
        resolved = FeishuHumanInputIMProvider._as_non_empty_string(value)
        if resolved is None:
            raise IMBindingValidationError(error_message)
        return resolved
