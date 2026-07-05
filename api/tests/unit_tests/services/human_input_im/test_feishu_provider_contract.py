import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from lark_oapi.api.im.v1 import CreateMessageResponse, PatchMessageResponse
from lark_oapi.core.const import (
    LARK_REQUEST_NONCE,
    LARK_REQUEST_SIGNATURE,
    LARK_REQUEST_TIMESTAMP,
)

from models.im_delivery import IMMessageCardStatus
from models.im_integration import IMInstallMode, IMProvider, IMScopeType
from services.errors.im_binding import IMProviderCallbackVerificationError, IMProviderTransportError
from services.human_input_im.app_config_service import IMAppConfigStatus, IMAppContext, IMEventMode, IMTokenStatus
from services.human_input_im.feishu_provider import FeishuHumanInputIMProvider
from services.human_input_im.provider_registry import HumanInputIMProviderRegistry
from services.human_input_im.provider_types import (
    IMActionDefinition,
    IMCardUpdateCommand,
    IMInlineInputDefinition,
    IMInteractionRenderPayload,
    IMSendCommand,
    IMSendResult,
)

_VALID_CALLBACK_HEADERS = {
    LARK_REQUEST_TIMESTAMP: "1720000000",
    LARK_REQUEST_NONCE: "nonce-1",
    LARK_REQUEST_SIGNATURE: "signature-1",
}
_VALID_CALLBACK_PAYLOAD = b'{"schema":"2.0","header":{"event_id":"event-1"}}'


class _FakeResponse:
    def __init__(
        self,
        *,
        success: bool,
        code: int | None = None,
        msg: str | None = None,
        message_id: str | None = None,
        log_id: str | None = None,
        troubleshooter: str | None = None,
    ) -> None:
        self.code = code
        self.msg = msg
        self.data = None if message_id is None else SimpleNamespace(message_id=message_id)
        self._success = success
        self._log_id = log_id
        self._troubleshooter = troubleshooter

    def success(self) -> bool:
        return self._success

    def get_log_id(self) -> str | None:
        return self._log_id

    def get_troubleshooter(self) -> str | None:
        return self._troubleshooter


_TransportResponse = _FakeResponse | CreateMessageResponse | PatchMessageResponse


class _FakeClientFactory:
    def __init__(self, client: object | None = None) -> None:
        self.client = client or object()
        self.calls: list[IMAppContext] = []

    def build(self, app_context: IMAppContext) -> object:
        self.calls.append(app_context)
        return self.client


class _FakeTransport:
    def __init__(
        self,
        *,
        create_response: _TransportResponse | Exception | None = None,
        patch_response: _TransportResponse | Exception | None = None,
    ) -> None:
        self.create_response = create_response
        self.patch_response = patch_response
        self.create_calls: list[tuple[object, Any]] = []
        self.patch_calls: list[tuple[object, Any]] = []

    def create_message(self, client: object, request: Any) -> _TransportResponse:
        self.create_calls.append((client, request))
        if isinstance(self.create_response, Exception):
            raise self.create_response
        if self.create_response is None:
            raise AssertionError("create_response was not configured for this test")
        return self.create_response

    def patch_message(self, client: object, request: Any) -> _TransportResponse:
        self.patch_calls.append((client, request))
        if isinstance(self.patch_response, Exception):
            raise self.patch_response
        if self.patch_response is None:
            raise AssertionError("patch_response was not configured for this test")
        return self.patch_response


class _FakeDispatcher:
    def __init__(
        self,
        *,
        response: SimpleNamespace | None = None,
        event: object | None = None,
        do_error: Exception | None = None,
        do_without_validation_error: Exception | None = None,
    ) -> None:
        self.response = response or SimpleNamespace(status_code=200, content=b"")
        self.event = event
        self.do_error = do_error
        self.do_without_validation_error = do_without_validation_error
        self.handler = None
        self.raw_requests: list[object] = []
        self.payloads: list[bytes] = []

    def do(self, raw_request: object) -> SimpleNamespace:
        self.raw_requests.append(raw_request)
        if self.do_error is not None:
            raise self.do_error
        if self.event is not None and self.handler is not None:
            self.handler(self.event)
        return self.response

    def _do_without_validation(self, payload: bytes) -> None:
        self.payloads.append(payload)
        if self.do_without_validation_error is not None:
            raise self.do_without_validation_error
        if self.event is not None and self.handler is not None:
            self.handler(self.event)


class _FakeDispatcherFactory:
    def __init__(self, dispatcher: _FakeDispatcher) -> None:
        self.dispatcher = dispatcher
        self.calls: list[IMAppContext] = []
        self.require_verification_material: list[bool] = []

    def build_card_action_dispatcher(
        self,
        *,
        app_context: IMAppContext,
        handler,
        require_verification_material: bool = True,
    ) -> _FakeDispatcher:
        self.calls.append(app_context)
        self.require_verification_material.append(require_verification_material)
        self.dispatcher.handler = handler
        return self.dispatcher


def test_default_feishu_provider_echoes_challenge_response() -> None:
    registry = HumanInputIMProviderRegistry()
    provider = registry.get_provider(IMProvider.FEISHU)

    assert provider is not None
    assert provider.build_challenge_response("challenge-token") == {"challenge": "challenge-token"}


def test_default_feishu_provider_returns_provider_neutral_failure_when_credentials_are_missing() -> None:
    registry = HumanInputIMProviderRegistry()
    provider = registry.get_provider(IMProvider.FEISHU)

    assert provider is not None
    result = provider.send_form(
        IMSendCommand(
            provider=IMProvider.FEISHU,
            app_context=_build_app_context(app_secret=None),
            recipient_id="user-1",
            form_id="form-1",
            title="Need approval",
            content="Please approve",
            metadata={"interaction_id": "interaction-1"},
        )
    )

    assert result == IMSendResult(
        provider=IMProvider.FEISHU,
        accepted=False,
        provider_message_id=None,
        error="feishu app credentials are not configured",
    )


def test_feishu_provider_builds_interactive_send_request_and_maps_provider_rejection() -> None:
    client_factory = _FakeClientFactory()
    transport = _FakeTransport(
        create_response=_FakeResponse(
            success=False,
            code=400,
            msg="bad request",
            log_id="log-1",
        )
    )
    provider = FeishuHumanInputIMProvider(client_factory=client_factory, transport=transport)

    result = provider.send_form(
        IMSendCommand(
            provider=IMProvider.FEISHU,
            app_context=_build_app_context(),
            recipient_id="open-id-1",
            form_id="form-1",
            title="Need approval",
            content="Please approve",
            metadata={"correlation_id": "correlation-1"},
            interaction_payload=_build_interaction_payload(),
        )
    )

    assert result == IMSendResult(
        provider=IMProvider.FEISHU,
        accepted=False,
        provider_message_id=None,
        error="feishu send message failed, code=400, msg=bad request, log_id=log-1",
    )
    assert len(client_factory.calls) == 1
    assert len(transport.create_calls) == 1

    client, request = transport.create_calls[0]
    assert client is client_factory.client
    assert request.receive_id_type == "open_id"
    assert request.request_body.receive_id == "open-id-1"
    assert request.request_body.msg_type == "interactive"
    assert request.request_body.uuid == "correlation-1"

    card = json.loads(request.request_body.content)
    assert card["header"]["title"]["content"] == "Need approval"
    assert card["elements"][0]["content"] == "Rendered body"
    form_element = next(element for element in card["elements"] if element["tag"] == "form")
    assert form_element["name"] == "interaction-1"
    assert form_element["elements"][0]["name"] == "provider_component_reason"
    assert form_element["actions"][0]["name"] == "provider_action_approve"
    assert form_element["actions"][0]["value"] == {
        "action_id": "provider_action_approve",
        "interaction_id": "interaction-1",
    }


def test_feishu_provider_maps_send_success_response_to_provider_message_id() -> None:
    client_factory = _FakeClientFactory()
    transport = _FakeTransport(
        create_response=_FakeResponse(
            success=True,
            message_id="message-1",
        )
    )
    provider = FeishuHumanInputIMProvider(client_factory=client_factory, transport=transport)

    result = provider.send_form(
        IMSendCommand(
            provider=IMProvider.FEISHU,
            app_context=_build_app_context(),
            recipient_id="open-id-1",
            form_id="form-1",
            title="Need approval",
            content="Please approve",
            metadata={"correlation_id": "correlation-1"},
            interaction_payload=_build_interaction_payload(),
        )
    )

    assert result == IMSendResult(
        provider=IMProvider.FEISHU,
        accepted=True,
        provider_message_id="message-1",
        error=None,
    )
    assert len(transport.create_calls) == 1
    _, request = transport.create_calls[0]
    assert request.request_body.receive_id == "open-id-1"
    assert request.request_body.uuid == "correlation-1"


def test_feishu_provider_includes_troubleshooter_in_send_rejection_mapping(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _FakeTransport(
        create_response=_FakeResponse(
            success=False,
            code=429,
            msg="rate limited",
            log_id="log-send-1",
            troubleshooter="https://docs.example.com/feishu/send",
        )
    )
    provider = FeishuHumanInputIMProvider(client_factory=_FakeClientFactory(), transport=transport)

    with caplog.at_level(logging.WARNING, logger="services.human_input_im.feishu_provider"):
        result = provider.send_form(
            IMSendCommand(
                provider=IMProvider.FEISHU,
                app_context=_build_app_context(),
                recipient_id="open-id-1",
                form_id="form-1",
                title="Need approval",
                content="Please approve",
                metadata={"correlation_id": "correlation-1"},
                interaction_payload=_build_interaction_payload(),
            )
        )

    assert result == IMSendResult(
        provider=IMProvider.FEISHU,
        accepted=False,
        provider_message_id=None,
        error=(
            "feishu send message failed, code=429, msg=rate limited, "
            "log_id=log-send-1, troubleshooter=https://docs.example.com/feishu/send"
        ),
    )
    assert "Feishu IM send rejected by provider" in caplog.text
    assert "recipient_open_id=open-id-1" in caplog.text
    assert "form_id=form-1" in caplog.text
    assert "troubleshooter=https://docs.example.com/feishu/send" in caplog.text


def test_feishu_provider_maps_dict_shaped_sdk_error_payload_into_send_rejection() -> None:
    transport = _FakeTransport(
        create_response=CreateMessageResponse(
            {
                "error": {
                    "code": 429,
                    "message": "rate limited",
                    "log_id": "log-send-1",
                    "troubleshooter": "https://docs.example.com/feishu/send",
                }
            }
        )
    )
    provider = FeishuHumanInputIMProvider(client_factory=_FakeClientFactory(), transport=transport)

    result = provider.send_form(
        IMSendCommand(
            provider=IMProvider.FEISHU,
            app_context=_build_app_context(),
            recipient_id="open-id-1",
            form_id="form-1",
            title="Need approval",
            content="Please approve",
            metadata={"correlation_id": "correlation-1"},
            interaction_payload=_build_interaction_payload(),
        )
    )

    assert result == IMSendResult(
        provider=IMProvider.FEISHU,
        accepted=False,
        provider_message_id=None,
        error=(
            "feishu send message failed, code=429, msg=rate limited, "
            "log_id=log-send-1, troubleshooter=https://docs.example.com/feishu/send"
        ),
    )


def test_feishu_provider_rejects_invalid_signature() -> None:
    dispatcher = _FakeDispatcher(response=SimpleNamespace(status_code=401, content=b'{"msg":"signature mismatch"}'))
    dispatcher_factory = _FakeDispatcherFactory(dispatcher)
    provider = FeishuHumanInputIMProvider(dispatcher_factory=dispatcher_factory)

    with pytest.raises(IMProviderCallbackVerificationError, match="signature mismatch"):
        provider.verify_signature(
            app_context=_build_app_context(),
            payload=_VALID_CALLBACK_PAYLOAD,
            headers=_VALID_CALLBACK_HEADERS,
        )

    assert dispatcher_factory.calls == [_build_app_context()]
    assert dispatcher_factory.require_verification_material == [True]
    assert len(dispatcher.raw_requests) == 1
    raw_request = dispatcher.raw_requests[0]
    assert raw_request.body == _VALID_CALLBACK_PAYLOAD
    assert raw_request.headers[LARK_REQUEST_TIMESTAMP] == _VALID_CALLBACK_HEADERS[LARK_REQUEST_TIMESTAMP]
    assert raw_request.headers[LARK_REQUEST_NONCE] == _VALID_CALLBACK_HEADERS[LARK_REQUEST_NONCE]
    assert raw_request.headers[LARK_REQUEST_SIGNATURE] == _VALID_CALLBACK_HEADERS[LARK_REQUEST_SIGNATURE]


def test_feishu_provider_parses_valid_callback_into_provider_local_ids() -> None:
    dispatcher = _FakeDispatcher(event=_build_card_action_callback())
    provider = FeishuHumanInputIMProvider(dispatcher_factory=_FakeDispatcherFactory(dispatcher))

    parsed_submission = provider.parse_submission_callback(
        app_context=_build_app_context(),
        payload=_VALID_CALLBACK_PAYLOAD,
        headers=_VALID_CALLBACK_HEADERS,
    )

    assert dispatcher.raw_requests[0].body == _VALID_CALLBACK_PAYLOAD
    assert parsed_submission.event.provider == IMProvider.FEISHU
    assert parsed_submission.event.event_id == "event-1"
    assert parsed_submission.event.provider_workspace_id == "tenant-event"
    assert parsed_submission.event.provider_user_id == "open-id-1"
    assert parsed_submission.event.interaction_id == "interaction-1"
    assert parsed_submission.parsed_payload.provider_action_id == "provider_action_approve"
    assert parsed_submission.parsed_payload.provider_inputs == {
        "provider_component_reason": "looks good",
    }


def test_feishu_provider_keeps_unknown_component_in_provider_local_payload() -> None:
    dispatcher = _FakeDispatcher(
        event=_build_card_action_callback(
            form_value={"provider_component_unknown": "looks good"},
        )
    )
    provider = FeishuHumanInputIMProvider(dispatcher_factory=_FakeDispatcherFactory(dispatcher))

    parsed_submission = provider.parse_submission_callback(
        app_context=_build_app_context(),
        payload=_VALID_CALLBACK_PAYLOAD,
        headers=_VALID_CALLBACK_HEADERS,
    )

    assert dispatcher.raw_requests[0].body == _VALID_CALLBACK_PAYLOAD
    assert parsed_submission.parsed_payload.provider_action_id == "provider_action_approve"
    assert parsed_submission.parsed_payload.provider_inputs == {
        "provider_component_unknown": "looks good",
    }


def test_feishu_provider_rejects_malformed_callback_payload() -> None:
    dispatcher = _FakeDispatcher(do_error=ValueError("malformed payload"))
    dispatcher_factory = _FakeDispatcherFactory(dispatcher)
    provider = FeishuHumanInputIMProvider(dispatcher_factory=dispatcher_factory)

    with pytest.raises(IMProviderCallbackVerificationError, match="malformed payload"):
        provider.parse_submission_callback(
            app_context=_build_app_context(),
            payload=b"{not-json",
            headers=_VALID_CALLBACK_HEADERS,
        )

    assert dispatcher_factory.require_verification_material == [True]


def test_feishu_provider_updates_card_with_rendered_status_content() -> None:
    client_factory = _FakeClientFactory()
    transport = _FakeTransport(
        patch_response=_FakeResponse(
            success=True,
        )
    )
    provider = FeishuHumanInputIMProvider(client_factory=client_factory, transport=transport)

    provider.update_card(
        IMCardUpdateCommand(
            provider=IMProvider.FEISHU,
            app_context=_build_app_context(),
            provider_message_id="message-1",
            target_status=IMMessageCardStatus.SUBMITTED.value,
            metadata={
                "title": "Review Request",
                "form_link": "https://example.com/forms/form-1",
            },
        )
    )

    assert len(transport.patch_calls) == 1
    client, request = transport.patch_calls[0]
    assert client is client_factory.client
    assert request.message_id == "message-1"

    card = json.loads(request.request_body.content)
    assert card["header"]["title"]["content"] == "Review Request"
    assert card["header"]["template"] == "green"
    assert card["elements"][0]["content"] == "Form submitted\n\n[Open web form](https://example.com/forms/form-1)"


def test_feishu_provider_updates_error_card_with_reason_and_form_link() -> None:
    transport = _FakeTransport(
        patch_response=_FakeResponse(
            success=True,
        )
    )
    provider = FeishuHumanInputIMProvider(client_factory=_FakeClientFactory(), transport=transport)

    provider.update_card(
        IMCardUpdateCommand(
            provider=IMProvider.FEISHU,
            app_context=_build_app_context(),
            provider_message_id="message-1",
            target_status=IMMessageCardStatus.ERROR.value,
            metadata={
                "title": "Review Request",
                "error_reason": "validation failed",
                "form_link": "https://example.com/forms/form-1",
            },
        )
    )

    assert len(transport.patch_calls) == 1
    _, request = transport.patch_calls[0]
    card = json.loads(request.request_body.content)
    assert card["header"]["title"]["content"] == "Review Request"
    assert card["header"]["template"] == "red"
    assert card["elements"][0]["content"] == (
        "Submission failed\n\nvalidation failed\n\n[Open web form](https://example.com/forms/form-1)"
    )


def test_feishu_provider_raises_transport_error_when_card_update_is_rejected_by_provider() -> None:
    transport = _FakeTransport(
        patch_response=_FakeResponse(
            success=False,
            code=403,
            msg="forbidden",
            log_id="log-2",
            troubleshooter="https://docs.example.com/feishu/patch",
        )
    )
    provider = FeishuHumanInputIMProvider(client_factory=_FakeClientFactory(), transport=transport)

    with pytest.raises(IMProviderTransportError) as exc_info:
        provider.update_card(
            IMCardUpdateCommand(
                provider=IMProvider.FEISHU,
                app_context=_build_app_context(),
                provider_message_id="message-1",
                target_status=IMMessageCardStatus.ERROR.value,
                metadata={
                    "title": "Review Request",
                    "error_reason": "validation failed",
                },
            )
        )

    assert str(exc_info.value) == (
        "feishu patch message failed, code=403, msg=forbidden, "
        "log_id=log-2, troubleshooter=https://docs.example.com/feishu/patch"
    )


def test_feishu_provider_wraps_sdk_exception_during_card_update() -> None:
    transport = _FakeTransport(patch_response=RuntimeError("sdk down"))
    provider = FeishuHumanInputIMProvider(client_factory=_FakeClientFactory(), transport=transport)

    with pytest.raises(IMProviderTransportError, match="sdk down"):
        provider.update_card(
            IMCardUpdateCommand(
                provider=IMProvider.FEISHU,
                app_context=_build_app_context(),
                provider_message_id="message-1",
                target_status=IMMessageCardStatus.ERROR.value,
                metadata={"title": "Review Request"},
            )
        )


def _build_interaction_payload() -> IMInteractionRenderPayload:
    return IMInteractionRenderPayload(
        interaction_id="interaction-1",
        rendered_content="Rendered body",
        form_link="https://example.com/forms/form-1",
        inputs=[
            IMInlineInputDefinition(
                component_id="provider_component_reason",
                label="Reason",
                type="paragraph",
            )
        ],
        actions=[
            IMActionDefinition(
                provider_action_id="provider_action_approve",
                label="Approve",
            )
        ],
    )


def _build_card_action_callback(
    *,
    form_value: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        header=SimpleNamespace(event_id="event-1", tenant_key="tenant-header"),
        event=SimpleNamespace(
            operator=SimpleNamespace(tenant_key="tenant-event", open_id="open-id-1", user_id=None),
            action=SimpleNamespace(
                name="provider_component_reason",
                value={
                    "action_id": "provider_action_approve",
                    "interaction_id": "interaction-1",
                },
                tag="button",
                form_value=form_value or {"provider_component_reason": "looks good"},
                input_value=None,
                option=None,
                options=None,
                checked=None,
            ),
        ),
    )


def _build_app_context(
    *,
    status: IMAppConfigStatus = IMAppConfigStatus.CONFIGURED,
    app_secret: str | None = "secret",
) -> IMAppContext:
    return IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=status,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=IMEventMode.LONG_CONNECTION,
        app_id="cli_a",
        app_secret=app_secret,
        app_secret_configured=bool(app_secret),
        verification_token="verification-token",
        encrypt_key="encrypt-key",
        errors=[],
    )
