"""Feishu and Lark messaging tests at their official OpenAPI boundaries."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from pydantic import JsonValue, TypeAdapter

import core.human_input_v2.im_provider.providers.feishu_lark as feishu_provider
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    CardAction,
    CardActionKind,
    CardAssessment,
    CardIntent,
    FeishuLarkAdapter,
    FeishuLarkAdapterConfig,
    FeishuMessageReference,
    FeishuUserDestination,
    MessageAccepted,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
)


def _config() -> FeishuLarkAdapterConfig:
    return FeishuLarkAdapterConfig(
        provider=IMProvider.FEISHU,
        app_id="cli_test",
        app_secret="secret-test",
        verification_token="verification-test",
        encrypt_key="encrypt-test",
    )


def _install_http_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    monkeypatch.setattr(
        feishu_provider,
        "_build_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _token_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "msg": "ok",
            "tenant_access_token": "tenant-token",
            "expire": 7200,
        },
    )


def _card_intent() -> CardIntent:
    return CardIntent(
        title="Approval",
        body="Please **review** this request.",
        facts=(("Environment", "Staging"),),
        actions=(
            CardAction("approve", "Approve", CardActionKind.SUBMIT, "approved"),
            CardAction("details", "Details", CardActionKind.OPEN_URL, "https://example.com/details"),
        ),
        fallback_text="Please review this request.",
    )


def test_feishu_destination_validation_precedes_read_only_user_reachability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        assert request.method == "GET"
        assert request.url.raw_path.split(b"?", maxsplit=1)[0].endswith(
            b"/contact/v3/users/ou%2Fuser%3Fname%3D%E6%B5%8B%E8%AF%95"
        )
        assert dict(request.url.params) == {"user_id_type": "open_id"}
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {}})

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    invalid_result = adapter.messaging.test_destination(FeishuUserDestination("oc-chat", "unknown"))
    reachable_result = adapter.messaging.test_destination(
        FeishuUserDestination("ou/user?name=测试", "open_id"),
    )

    assert isinstance(invalid_result, OperationFailure)
    assert invalid_result.code is OperationFailureCode.INVALID_DESTINATION
    assert reachable_result is None
    assert len(requests) == 2
    assert all(not request.url.path.endswith("/im/v1/messages") for request in requests)

    adapter.close()


def test_feishu_destination_reachability_translates_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        (
            httpx.Response(404, json={"code": 230001, "msg": "user not found"}),
            httpx.Response(200, content=b"not-json"),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return next(responses)

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    unreachable = adapter.messaging.test_destination(FeishuUserDestination("ou-missing", "open_id"))
    invalid_response = adapter.messaging.test_destination(FeishuUserDestination("ou-invalid", "open_id"))

    assert isinstance(unreachable, OperationFailure)
    assert unreachable.code is OperationFailureCode.DESTINATION_UNREACHABLE
    assert isinstance(invalid_response, OperationFailure)
    assert invalid_response.code is OperationFailureCode.PROVIDER

    adapter.close()


def test_feishu_card_empty_metadata_is_nested_in_every_submit_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {"message_id": "om-1"}})

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None
    intent = CardIntent(
        None,
        "Choose one.",
        (),
        (
            CardAction("approve", "Approve", CardActionKind.SUBMIT, "approved"),
            CardAction("reject", "Reject", CardActionKind.SUBMIT, "rejected"),
        ),
        "Choose one.",
    )

    result = card_messaging.send_card(
        FeishuUserDestination("ou-user", "open_id"),
        intent,
        OpaqueMetadata(entries=()),
    )

    assert isinstance(result, MessageAccepted)
    request_body = TypeAdapter(dict[str, JsonValue]).validate_json(requests[1].content)
    card = TypeAdapter(dict[str, JsonValue]).validate_json(str(request_body["content"]))
    body = TypeAdapter(dict[str, JsonValue]).validate_python(card["body"])
    elements = TypeAdapter(list[dict[str, JsonValue]]).validate_python(body["elements"])
    actions = [element for element in elements if element.get("tag") == "button"]
    assert [action["behaviors"] for action in actions] == [
        [
            {
                "type": "callback",
                "value": {"action_id": "approve", "value": "approved", "metadata": {}},
            }
        ],
        [
            {
                "type": "callback",
                "value": {"action_id": "reject", "value": "rejected", "metadata": {}},
            }
        ],
    ]
    assert [action["text"] for action in actions] == [
        {"tag": "plain_text", "content": "Approve"},
        {"tag": "plain_text", "content": "Reject"},
    ]
    assert card["schema"] == "2.0"
    adapter.close()


@pytest.mark.parametrize(
    ("receive_id_type", "expected_method", "expected_path"),
    [
        ("email", "POST", "/open-apis/contact/v3/users/batch_get_id"),
        ("open_id", "GET", "/open-apis/contact/v3/users/ou-user"),
        ("user_id", "GET", "/open-apis/contact/v3/users/ou-user"),
        ("union_id", "GET", "/open-apis/contact/v3/users/ou-user"),
    ],
)
def test_feishu_destination_reachability_uses_read_only_identity_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    receive_id_type: str,
    expected_method: str,
    expected_path: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.url.path.endswith("/contact/v3/users/batch_get_id"):
            return httpx.Response(
                200,
                json={"code": 0, "msg": "success", "data": {"user_list": [{"user_id": "ou-user"}]}},
            )
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {"user": {"open_id": "ou-user"}}})

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())
    receive_id = "reviewer@example.com" if receive_id_type == "email" else "ou-user"

    result = adapter.messaging.test_destination(FeishuUserDestination(receive_id, receive_id_type))

    assert result is None
    assert requests[-1].method == expected_method
    assert requests[-1].url.path == expected_path
    assert all(not request.url.path.endswith("/im/v1/messages") for request in requests)

    adapter.close()


def test_feishu_email_destination_requires_a_matching_user_without_sending_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {"user_list": []}})

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.messaging.test_destination(
        FeishuUserDestination("missing@example.com", "email"),
    )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DESTINATION_UNREACHABLE
    assert [request.url.path for request in requests] == [
        "/open-apis/auth/v3/tenant_access_token/internal",
        "/open-apis/contact/v3/users/batch_get_id",
    ]
    assert all(not request.url.path.endswith("/im/v1/messages") for request in requests)

    adapter.close()


def test_feishu_destination_transport_failure_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        raise httpx.ConnectError("destination failed", request=request)

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.messaging.test_destination(FeishuUserDestination("ou-user", "open_id"))

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER

    adapter.close()


def test_feishu_text_card_send_and_exact_update_reuse_one_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        request_number = len(requests) - 1
        if request.method == "PATCH":
            return httpx.Response(200, json={"code": 0, "msg": "success", "data": {}})
        return httpx.Response(
            200,
            json={"code": 0, "msg": "success", "data": {"message_id": f"om-{request_number}"}},
            headers={"x-tt-logid": f"request-{request_number}"},
        )

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())
    destination = FeishuUserDestination("ou-user", "open_id")
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    assessment = card_messaging.assess(_card_intent())
    text_result = adapter.messaging.send_text(destination, "Hello **reviewer**")
    card_result = card_messaging.send_card(
        destination,
        _card_intent(),
        OpaqueMetadata(entries=(("form_id", "form-1"),)),
    )
    reference = FeishuMessageReference("om-2")
    update_result = card_messaging.update_card(
        reference,
        _card_intent(),
        OpaqueMetadata(entries=(("form_id", "form-2"),)),
    )

    assert assessment == CardAssessment(representable=True, reason=None)
    assert text_result == MessageAccepted(FeishuMessageReference("om-1"), "request-1")
    assert card_result == MessageAccepted(reference, "request-2")
    assert update_result == MessageAccepted(reference, None)
    assert [request.method for request in requests] == ["POST", "POST", "POST", "PATCH"]
    assert [request.url.path for request in requests[1:]] == [
        "/open-apis/im/v1/messages",
        "/open-apis/im/v1/messages",
        "/open-apis/im/v1/messages/om-2",
    ]
    assert all(request.headers["authorization"] == "Bearer tenant-token" for request in requests[1:])

    text_request = TypeAdapter(dict[str, JsonValue]).validate_json(requests[1].content)
    assert requests[1].url.params["receive_id_type"] == "open_id"
    assert text_request == {
        "receive_id": "ou-user",
        "msg_type": "text",
        "content": '{"text":"Hello **reviewer**"}',
    }

    card_request = TypeAdapter(dict[str, JsonValue]).validate_json(requests[2].content)
    update_request = TypeAdapter(dict[str, JsonValue]).validate_json(requests[3].content)
    assert card_request["msg_type"] == "interactive"
    card_content = TypeAdapter(dict[str, JsonValue]).validate_json(str(card_request["content"]))
    update_content = TypeAdapter(dict[str, JsonValue]).validate_json(str(update_request["content"]))
    assert card_content["config"] == update_content["config"]
    assert card_content["header"] == update_content["header"]
    card_body = TypeAdapter(dict[str, JsonValue]).validate_python(card_content["body"])
    update_body = TypeAdapter(dict[str, JsonValue]).validate_python(update_content["body"])
    card_elements = TypeAdapter(list[dict[str, JsonValue]]).validate_python(card_body["elements"])
    update_elements = TypeAdapter(list[dict[str, JsonValue]]).validate_python(update_body["elements"])
    assert card_elements[:2] == update_elements[:2]
    assert card_elements[-1] == update_elements[-1]
    assert card_content == {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": "Approval"}},
        "body": {
            "direction": "vertical",
            "elements": [
                {"tag": "markdown", "content": "Please **review** this request."},
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": "**Environment**\nStaging"},
                        }
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Approve"},
                    "type": "primary",
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {
                                "action_id": "approve",
                                "value": "approved",
                                "metadata": {"form_id": "form-1"},
                            },
                        }
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Details"},
                    "type": "default",
                    "behaviors": [{"type": "open_url", "default_url": "https://example.com/details"}],
                },
            ],
        },
    }
    update_behaviors = TypeAdapter(list[dict[str, JsonValue]]).validate_python(update_elements[-2]["behaviors"])
    assert update_behaviors == [
        {
            "type": "callback",
            "value": {
                "action_id": "approve",
                "value": "approved",
                "metadata": {"form_id": "form-2"},
            },
        }
    ]
    assert "value" not in update_elements[-1]

    adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("timeout", OperationFailureCode.AMBIGUOUS),
        ("malformed_response", OperationFailureCode.AMBIGUOUS),
        ("rate_limited", OperationFailureCode.RATE_LIMITED),
        ("provider_rejection", OperationFailureCode.PROVIDER),
        ("missing_reference", OperationFailureCode.AMBIGUOUS),
    ],
)
def test_feishu_send_failure_is_not_replayed(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    message_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        message_requests.append(request)
        if failure_kind == "timeout":
            raise httpx.ReadTimeout("Feishu response timed out", request=request)
        if failure_kind == "malformed_response":
            return httpx.Response(200, content=b"not-json")
        if failure_kind == "rate_limited":
            return httpx.Response(429, json={"code": 230020, "msg": "rate limited"})
        if failure_kind == "provider_rejection":
            return httpx.Response(400, json={"code": 230001, "msg": "invalid request"})
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {}})

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.messaging.send_text(FeishuUserDestination("ou-user", "open_id"), "Hello")

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    assert len(message_requests) == 1

    adapter.close()


def test_feishu_stale_update_encodes_exact_reference_and_makes_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        message_requests.append(request)
        return httpx.Response(404, json={"code": 230001, "msg": "message not found"})

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    result = card_messaging.update_card(
        FeishuMessageReference("om/../?message=测试"),
        _card_intent(),
        OpaqueMetadata(entries=()),
    )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.STALE_REFERENCE
    assert len(message_requests) == 1
    assert message_requests[0].url.raw_path.endswith(b"/im/v1/messages/om%2F..%2F%3Fmessage%3D%E6%B5%8B%E8%AF%95")

    adapter.close()


def test_feishu_message_validation_and_token_failure_precede_provider_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    token_requests = 0

    def rejected_token(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        requests.append(request)
        token_requests += 1
        if token_requests == 1:
            return httpx.Response(401, json={"code": 10003, "msg": "invalid app secret"})
        return _token_response()

    _install_http_client(monkeypatch, rejected_token)
    adapter = FeishuLarkAdapter(_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    invalid_destination = adapter.messaging.send_text(
        FeishuUserDestination("oc-chat", "unknown"),
        "Hello",
    )
    token_failure = adapter.messaging.send_text(
        FeishuUserDestination("ou-user", "open_id"),
        "Hello",
    )
    invalid_reference = card_messaging.update_card(
        FeishuMessageReference(".."),
        _card_intent(),
        OpaqueMetadata(entries=()),
    )

    assert isinstance(invalid_destination, OperationFailure)
    assert invalid_destination.code is OperationFailureCode.INVALID_DESTINATION
    assert isinstance(token_failure, OperationFailure)
    assert token_failure.code is OperationFailureCode.AUTHENTICATION
    assert isinstance(invalid_reference, OperationFailure)
    assert invalid_reference.code is OperationFailureCode.STALE_REFERENCE
    assert len(requests) == 2

    adapter.close()
