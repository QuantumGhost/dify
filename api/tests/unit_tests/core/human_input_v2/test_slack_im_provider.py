"""Slack adapter tests at the real HTTP and Webhook protocol boundaries."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import override
from urllib.parse import urlencode

import httpx
import pytest
from pydantic import JsonValue, TypeAdapter
from typing_extensions import TypedDict

import core.human_input_v2.im_provider.providers.slack as slack_provider
from configs import dify_config
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AuthenticatedIMEvent,
    CardAction,
    CardActionKind,
    CardAssessment,
    CardIntent,
    CredentialTestSuccess,
    DirectoryEntry,
    DirectorySnapshot,
    EventAcceptance,
    IMEventSink,
    MessageAccepted,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
    PermissionFact,
    SlackAdapter,
    SlackAdapterConfig,
    SlackMessageReference,
    SlackUserDestination,
    WebhookRequest,
)


class _SlackTextMessageRequest(TypedDict):
    channel: str
    text: str


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


def _card_intent_with_action_count(action_count: int) -> CardIntent:
    return CardIntent(
        title=None,
        body="Review this request.",
        facts=(),
        actions=tuple(
            CardAction(f"action-{action_index}", "Review", CardActionKind.SUBMIT, "review")
            for action_index in range(action_count)
        ),
        fallback_text="Review this request.",
    )


def _submit_value_size(action_value: str, metadata: OpaqueMetadata) -> int:
    return len(
        json.dumps(
            {"v": 1, "action_value": action_value, "metadata": metadata.as_dict()},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )


def _encoded_submit_action_value(action_value: str = "approved") -> str:
    return json.dumps(
        {"v": 1, "action_value": action_value, "metadata": {}},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass
class _RecordingSink(IMEventSink):
    acceptance: EventAcceptance
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        return self.acceptance


def _signed_request(
    body: bytes,
    *,
    timestamp: int,
    signature_override: str | None = None,
    received_at: datetime | None = None,
    extra_headers: tuple[tuple[str, str], ...] = (),
    content_type: str = "application/json",
) -> WebhookRequest:
    signature_base = f"v0:{timestamp}:".encode() + body
    signature = "v0=" + hmac.new(b"signing-test", signature_base, hashlib.sha256).hexdigest()
    return WebhookRequest(
        method="POST",
        headers=(
            ("content-type", content_type),
            ("x-slack-request-timestamp", str(timestamp)),
            ("x-slack-signature", signature_override or signature),
            *extra_headers,
        ),
        query=(),
        body=body,
        received_at=received_at or datetime.fromtimestamp(timestamp, tz=UTC),
    )


def _slack_config() -> SlackAdapterConfig:
    return SlackAdapterConfig(bot_token="xoxb-test", signing_secret="signing-test", app_token="xapp-test")


def _slash_command_body(*, text: str = "request-1") -> bytes:
    return urlencode(
        {
            "team_id": "T123",
            "team_domain": "test-workspace",
            "channel_id": "C123",
            "channel_name": "approvals",
            "user_id": "U123",
            "user_name": "reviewer",
            "command": "/approve",
            "text": text,
            "api_app_id": "A123",
            "is_enterprise_install": "false",
            "response_url": "https://hooks.slack.test/commands/response",
            "trigger_id": "trigger-1",
        }
    ).encode()


def _install_mock_http_client(
    monkeypatch: pytest.MonkeyPatch,
    handle_request: Callable[[httpx.Request], httpx.Response],
) -> None:
    def build_http_client(config: SlackAdapterConfig) -> httpx.Client:
        return httpx.Client(
            headers={"authorization": f"Bearer {config.bot_token}"},
            timeout=10.0,
            transport=httpx.MockTransport(handle_request),
        )

    monkeypatch.setattr(slack_provider, "_build_http_client", build_http_client)


def test_slack_http_client_uses_caller_owned_ssrf_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    factory_calls: list[tuple[bool, dict[str, str], float]] = []
    http_client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))

    def create_client(*, verify: bool, headers: dict[str, str], timeout: float) -> httpx.Client:
        factory_calls.append((verify, headers, timeout))
        return http_client

    monkeypatch.setattr(slack_provider, "create_ssrf_protected_client", create_client)

    result = slack_provider._build_http_client(_slack_config())

    assert result is http_client
    assert factory_calls == [
        (
            dify_config.HTTP_REQUEST_NODE_SSL_VERIFY,
            {"authorization": "Bearer xoxb-test"},
            10.0,
        )
    ]

    result.close()


def test_slack_credential_test_uses_auth_test_and_normalizes_team_and_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"ok": True, "team_id": "T123", "user_id": "U123", "bot_id": "B123"},
            headers={"x-oauth-scopes": "chat:write,users:read,users:read.email"},
        )

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.test_credentials()

    assert result == CredentialTestSuccess(
        provider=IMProvider.SLACK,
        provider_tenant_id="T123",
        permissions=(
            PermissionFact(name="chat:write", granted=True),
            PermissionFact(name="users:read", granted=True),
            PermissionFact(name="users:read.email", granted=True),
        ),
    )
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url == httpx.URL("https://slack.com/api/auth.test")
    assert requests[0].headers["authorization"] == "Bearer xoxb-test"

    adapter.close()


def test_slack_credential_test_accepts_missing_optional_email_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True, "team_id": "T123"},
            headers={"x-oauth-scopes": "chat:write,users:read"},
        )

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.test_credentials()

    assert result == CredentialTestSuccess(
        provider=IMProvider.SLACK,
        provider_tenant_id="T123",
        permissions=(
            PermissionFact(name="chat:write", granted=True),
            PermissionFact(name="users:read", granted=True),
        ),
    )

    adapter.close()


@pytest.mark.parametrize(
    ("status_code", "response_body", "scope_header", "expected_code"),
    [
        (429, {"ok": False, "error": "ratelimited"}, "", OperationFailureCode.RATE_LIMITED),
        (500, {"ok": False, "error": "server_error"}, "", OperationFailureCode.PROVIDER),
        (403, {"ok": False, "error": "unknown_error"}, "", OperationFailureCode.PROVIDER),
        (200, {"ok": False, "error": "invalid_auth"}, "", OperationFailureCode.AUTHENTICATION),
        (
            200,
            {"ok": True},
            "chat:write,users:read,users:read.email",
            OperationFailureCode.TENANT_IDENTIFICATION,
        ),
        (200, {"ok": True, "team_id": "T123"}, "chat:write", OperationFailureCode.MISSING_PERMISSION),
    ],
)
def test_slack_credential_test_returns_typed_failures_for_rejected_or_incomplete_credentials(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    response_body: dict[str, JsonValue],
    scope_header: str,
    expected_code: OperationFailureCode,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=response_body, headers={"x-oauth-scopes": scope_header})

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code

    adapter.close()


@pytest.mark.parametrize("failure_kind", ["malformed_response", "transport_error"])
def test_slack_credential_test_hides_malformed_or_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        if failure_kind == "transport_error":
            raise httpx.ConnectError("Slack is unavailable", request=request)
        return httpx.Response(200, content=b"not-json")

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER
    assert "not-json" not in result.message

    adapter.close()


def test_slack_directory_reads_every_cursor_before_returning_one_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/auth.test":
            return httpx.Response(
                200,
                json={"ok": True, "team_id": "T123"},
                headers={"x-oauth-scopes": "chat:write,users:read,users:read.email"},
            )
        if request.url.params.get("cursor") is None:
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "members": [
                        {
                            "id": "U1",
                            "deleted": False,
                            "profile": {"display_name": "Ada", "real_name": "Ada Lovelace", "email": "ada@example.com"},
                        }
                    ],
                    "response_metadata": {"next_cursor": "cursor-2"},
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "members": [
                    {
                        "id": "U2",
                        "deleted": True,
                        "profile": {"display_name": "", "real_name": "Grace Hopper"},
                    }
                ],
                "response_metadata": {"next_cursor": ""},
            },
        )

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(
        SlackAdapterConfig(
            bot_token="xoxb-test",
            signing_secret="signing-test",
            app_token="xapp-test",
            directory_page_size=1,
        )
    )

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.SLACK,
        provider_tenant_id="T123",
        entries=(
            DirectoryEntry("U1", "Ada", "ada@example.com", True),
            DirectoryEntry("U2", "Grace Hopper", None, False),
        ),
    )
    assert [request.url.path for request in requests] == ["/api/auth.test", "/api/users.list", "/api/users.list"]
    assert requests[1].url.params["limit"] == "1"
    assert requests[2].url.params["limit"] == "1"
    assert requests[2].url.params["cursor"] == "cursor-2"

    adapter.close()


def test_slack_directory_preserves_user_without_email_when_email_scope_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth.test":
            return httpx.Response(
                200,
                json={"ok": True, "team_id": "T123"},
                headers={"x-oauth-scopes": "chat:write,users:read"},
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "members": [{"id": "U1", "profile": {"display_name": "Ada"}}],
                "response_metadata": {"next_cursor": ""},
            },
        )

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.SLACK,
        provider_tenant_id="T123",
        entries=(DirectoryEntry("U1", "Ada", None, True),),
    )

    adapter.close()


@pytest.mark.parametrize("late_page_kind", ["provider_rejection", "malformed_member"])
def test_slack_directory_discards_entries_when_a_late_page_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    late_page_kind: str,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth.test":
            return httpx.Response(
                200,
                json={"ok": True, "team_id": "T123"},
                headers={"x-oauth-scopes": "chat:write,users:read,users:read.email"},
            )
        if request.url.params.get("cursor") is None:
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "members": [{"id": "U1", "profile": {"real_name": "Ada"}}],
                    "response_metadata": {"next_cursor": "cursor-2"},
                },
            )
        if late_page_kind == "provider_rejection":
            return httpx.Response(500, json={"ok": False, "error": "internal_error"})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "members": [{"id": " ", "profile": {"real_name": "Invalid"}}],
                "response_metadata": {"next_cursor": ""},
            },
        )

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE

    adapter.close()


@pytest.mark.parametrize("failure_kind", ["credential_rejection", "transport_error"])
def test_slack_directory_returns_failure_without_requesting_or_exposing_entries(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/auth.test":
            if failure_kind == "credential_rejection":
                return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
            return httpx.Response(
                200,
                json={"ok": True, "team_id": "T123"},
                headers={"x-oauth-scopes": "chat:write,users:read,users:read.email"},
            )
        raise httpx.ConnectError("Slack is unavailable", request=request)

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    expected_code = (
        OperationFailureCode.AUTHENTICATION
        if failure_kind == "credential_rejection"
        else OperationFailureCode.DIRECTORY_INCOMPLETE
    )
    assert result.code is expected_code
    expected_paths = ["/api/auth.test"]
    if failure_kind == "transport_error":
        expected_paths.append("/api/users.list")
    assert [request.url.path for request in requests] == expected_paths

    adapter.close()


@pytest.mark.parametrize("rate_limit_kind", ["invalid_retry_after", "retry_exhausted"])
def test_slack_directory_bounds_rate_limit_retries(
    monkeypatch: pytest.MonkeyPatch,
    rate_limit_kind: str,
) -> None:
    users_list_calls = 0

    def handle_request(request: httpx.Request) -> httpx.Response:
        nonlocal users_list_calls
        if request.url.path == "/api/auth.test":
            return httpx.Response(
                200,
                json={"ok": True, "team_id": "T123"},
                headers={"x-oauth-scopes": "chat:write,users:read,users:read.email"},
            )
        users_list_calls += 1
        retry_after = "invalid" if rate_limit_kind == "invalid_retry_after" else "0"
        return httpx.Response(429, json={"ok": False, "error": "ratelimited"}, headers={"retry-after": retry_after})

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    assert users_list_calls == (1 if rate_limit_kind == "invalid_retry_after" else 4)

    adapter.close()


def test_slack_directory_retries_a_rate_limited_page_without_returning_partial_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users_list_calls = 0

    def handle_request(request: httpx.Request) -> httpx.Response:
        nonlocal users_list_calls
        if request.url.path == "/api/auth.test":
            return httpx.Response(
                200,
                json={"ok": True, "team_id": "T123"},
                headers={"x-oauth-scopes": "chat:write,users:read,users:read.email"},
            )
        users_list_calls += 1
        if users_list_calls == 1:
            return httpx.Response(429, json={"ok": False, "error": "ratelimited"}, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "members": [{"id": "U1", "deleted": False, "profile": {"real_name": "Ada"}}],
                "response_metadata": {"next_cursor": ""},
            },
        )

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.SLACK,
        provider_tenant_id="T123",
        entries=(DirectoryEntry("U1", "Ada", None, True),),
    )
    assert users_list_calls == 2

    adapter.close()


def test_slack_basic_messaging_uses_read_only_destination_check_and_one_send_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/users.info":
            return httpx.Response(
                200,
                json={"ok": True, "user": {"id": "U1", "profile": {"real_name": "Ada"}}},
            )
        return httpx.Response(
            200,
            json={"ok": True, "channel": "D1", "ts": "1000.1"},
            headers={"x-slack-req-id": "request-1"},
        )

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())
    destination = SlackUserDestination(user_id="U1")

    destination_result = adapter.messaging.test_destination(destination)
    send_result = adapter.messaging.send_text(destination, "Hello **team**")

    assert destination_result is None
    assert send_result == MessageAccepted(
        reference=SlackMessageReference(channel_id="D1", message_timestamp="1000.1"),
        provider_request_id="request-1",
    )
    assert [request.url.path for request in requests] == ["/api/users.info", "/api/chat.postMessage"]
    assert dict(requests[0].url.params) == {"user": "U1"}
    assert TypeAdapter(_SlackTextMessageRequest).validate_json(requests[1].content) == {
        "channel": "U1",
        "text": "Hello **team**",
    }

    adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("provider_rejection", OperationFailureCode.DESTINATION_UNREACHABLE),
        ("malformed_response", OperationFailureCode.PROVIDER),
        ("transport_error", OperationFailureCode.PROVIDER),
    ],
)
def test_slack_destination_check_translates_provider_and_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        if failure_kind == "transport_error":
            raise httpx.ConnectError("Slack is unavailable", request=request)
        if failure_kind == "malformed_response":
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json={"ok": False, "error": "user_not_found"})

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.messaging.test_destination(SlackUserDestination(user_id="U1"))

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code

    adapter.close()


def test_slack_destination_check_translates_user_scope_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": False,
                "error": "missing_scope",
                "needed": "users:read",
                "provided": "chat:write,users:read,users:read.email",
            },
        )

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.messaging.test_destination(SlackUserDestination("U1"))

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.MISSING_PERMISSION
    assert "users:read" in result.message

    adapter.close()


def test_slack_card_assessment_send_and_exact_reference_update_use_block_kit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"ok": True, "channel": "C1", "ts": "1000.1"},
            headers={"x-slack-req-id": f"request-{len(requests)}"},
        )

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None
    destination = SlackUserDestination(user_id="U1")

    assessment = card_messaging.assess(_card_intent())
    send_result = card_messaging.send_card(
        destination,
        _card_intent(),
        OpaqueMetadata(entries=(("form_id", "form-1"),)),
    )
    reference = SlackMessageReference(channel_id="C1", message_timestamp="1000.1")
    update_result = card_messaging.update_card(
        reference,
        _card_intent(),
        OpaqueMetadata(entries=(("form_id", "form-2"),)),
    )

    assert assessment == CardAssessment(representable=True, reason=None)
    assert send_result == MessageAccepted(reference=reference, provider_request_id="request-1")
    assert update_result == MessageAccepted(reference=reference, provider_request_id="request-2")
    assert [request.url.path for request in requests] == ["/api/chat.postMessage", "/api/chat.update"]
    send_body = TypeAdapter(dict[str, JsonValue]).validate_json(requests[0].content)
    update_body = TypeAdapter(dict[str, JsonValue]).validate_json(requests[1].content)
    assert send_body["channel"] == "U1"
    assert send_body["text"] == "Please review this request."
    assert update_body["channel"] == "C1"
    assert update_body["ts"] == "1000.1"
    send_blocks = TypeAdapter(list[dict[str, JsonValue]]).validate_python(send_body["blocks"])
    update_blocks = TypeAdapter(list[dict[str, JsonValue]]).validate_python(update_body["blocks"])
    assert send_blocks[:-1] == update_blocks[:-1]
    assert send_blocks[:-1] == [
        {"type": "header", "text": {"type": "plain_text", "text": "Approval"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "Please **review** this request."}},
        {"type": "section", "fields": [{"type": "mrkdwn", "text": "*Environment*\nStaging"}]},
    ]
    send_actions = TypeAdapter(list[dict[str, JsonValue]]).validate_python(send_blocks[-1]["elements"])
    update_actions = TypeAdapter(list[dict[str, JsonValue]]).validate_python(update_blocks[-1]["elements"])
    assert send_actions[0] == {
        "type": "button",
        "action_id": "approve",
        "text": {"type": "plain_text", "text": "Approve"},
        "value": '{"action_value":"approved","metadata":{"form_id":"form-1"},"v":1}',
    }
    assert update_actions[0] == {
        "type": "button",
        "action_id": "approve",
        "text": {"type": "plain_text", "text": "Approve"},
        "value": '{"action_value":"approved","metadata":{"form_id":"form-2"},"v":1}',
    }
    expected_open_url = {
        "type": "button",
        "action_id": "details",
        "text": {"type": "plain_text", "text": "Details"},
        "url": "https://example.com/details",
    }
    assert send_actions[1] == expected_open_url
    assert update_actions[1] == expected_open_url

    adapter.close()


def test_slack_card_empty_metadata_is_nested_in_every_submit_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "channel": "C1", "ts": "1000.1"})

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())
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
        SlackUserDestination("U1"),
        intent,
        OpaqueMetadata(entries=()),
    )

    assert isinstance(result, MessageAccepted)
    request_body = TypeAdapter(dict[str, JsonValue]).validate_json(requests[0].content)
    blocks = TypeAdapter(list[dict[str, JsonValue]]).validate_python(request_body["blocks"])
    buttons = TypeAdapter(list[dict[str, JsonValue]]).validate_python(blocks[-1]["elements"])
    assert [json.loads(str(button["value"])) for button in buttons] == [
        {"v": 1, "action_value": "approved", "metadata": {}},
        {"v": 1, "action_value": "rejected", "metadata": {}},
    ]

    adapter.close()


def test_slack_submit_value_at_exact_utf8_limit_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "channel": "C1", "ts": "1000.1"})

    _install_mock_http_client(monkeypatch, handle_request)
    metadata = OpaqueMetadata(entries=())
    action_value = "a" * (2000 - _submit_value_size("", metadata))
    assert _submit_value_size(action_value, metadata) == 2000
    intent = CardIntent(
        None,
        "Review.",
        (),
        (CardAction("approve", "Approve", CardActionKind.SUBMIT, action_value),),
        "Review.",
    )
    adapter = SlackAdapter(_slack_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    result = card_messaging.send_card(SlackUserDestination("U1"), intent, metadata)

    assert isinstance(result, MessageAccepted)
    assert len(requests) == 1
    adapter.close()


@pytest.mark.parametrize("operation", ["send", "update"])
@pytest.mark.parametrize("value_kind", ["ascii-2001-bytes", "multibyte-over-limit"])
def test_slack_submit_value_over_utf8_limit_is_rendering_failure_without_provider_io(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    value_kind: str,
) -> None:
    requests: list[httpx.Request] = []

    def record_unexpected_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    _install_mock_http_client(monkeypatch, record_unexpected_request)
    metadata = OpaqueMetadata(entries=())
    exact_value = "a" * (2000 - _submit_value_size("", metadata))
    action_value = exact_value + "a" if value_kind == "ascii-2001-bytes" else exact_value[:-1] + "界"
    expected_size = 2001 if value_kind == "ascii-2001-bytes" else 2002
    assert _submit_value_size(action_value, metadata) == expected_size
    intent = CardIntent(
        None,
        "Review.",
        (),
        (CardAction("approve", "Approve", CardActionKind.SUBMIT, action_value),),
        "Review.",
    )
    adapter = SlackAdapter(_slack_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    if operation == "send":
        result = card_messaging.send_card(SlackUserDestination("U1"), intent, metadata)
    else:
        result = card_messaging.update_card(SlackMessageReference("C1", "1000.1"), intent, metadata)

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.RENDERING
    assert requests == []
    adapter.close()


def test_slack_card_update_maps_missing_exact_message_to_stale_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "message_not_found"})

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    result = card_messaging.update_card(
        SlackMessageReference(channel_id="C1", message_timestamp="1000.1"),
        _card_intent(),
        OpaqueMetadata(entries=()),
    )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.STALE_REFERENCE

    adapter.close()


def test_slack_card_rejects_unrepresentable_action_count_without_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def record_unexpected_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    _install_mock_http_client(
        monkeypatch,
        record_unexpected_request,
    )
    adapter = SlackAdapter(_slack_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None
    intent = _card_intent_with_action_count(26)
    empty_metadata = OpaqueMetadata(entries=())

    assessment = card_messaging.assess(intent)
    send_result = card_messaging.send_card(SlackUserDestination("U1"), intent, empty_metadata)
    update_result = card_messaging.update_card(SlackMessageReference("C1", "1000.1"), intent, empty_metadata)

    assert assessment == CardAssessment(
        representable=False,
        reason="Slack supports at most 25 actions in one actions block",
    )
    assert isinstance(send_result, OperationFailure)
    assert isinstance(update_result, OperationFailure)
    assert send_result.code is OperationFailureCode.RENDERING
    assert update_result.code is OperationFailureCode.RENDERING
    assert requests == []

    adapter.close()


def test_slack_card_without_optional_sections_targets_one_personal_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "channel": "C1", "ts": "1000.1"})

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    result = card_messaging.send_card(
        SlackUserDestination("U1"),
        _card_intent_with_action_count(0),
        OpaqueMetadata(entries=()),
    )

    assert isinstance(result, MessageAccepted)
    assert TypeAdapter(dict[str, JsonValue]).validate_json(requests[0].content) == {
        "channel": "U1",
        "text": "Review this request.",
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Review this request."}}],
    }

    adapter.close()


def test_slack_send_timeout_is_ambiguous_and_is_not_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("Slack response timed out", request=request)

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.messaging.send_text(SlackUserDestination(user_id="U1"), "Hello")

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.AMBIGUOUS
    assert len(requests) == 1

    adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("malformed_response", OperationFailureCode.AMBIGUOUS),
        ("rate_limited", OperationFailureCode.RATE_LIMITED),
        ("provider_rejection", OperationFailureCode.PROVIDER),
        ("missing_reference", OperationFailureCode.AMBIGUOUS),
    ],
)
def test_slack_send_translates_response_failures_without_replay(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure_kind == "malformed_response":
            return httpx.Response(200, content=b"not-json")
        if failure_kind == "rate_limited":
            return httpx.Response(429, json={"ok": False, "error": "ratelimited"})
        if failure_kind == "provider_rejection":
            return httpx.Response(200, json={"ok": False, "error": "restricted_action"})
        return httpx.Response(200, json={"ok": True})

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())

    result = adapter.messaging.send_text(SlackUserDestination("U1"), "Hello")

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    assert len(requests) == 1

    adapter.close()


def test_slack_card_update_rejects_a_changed_response_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "channel": "C2", "ts": "2000.1"})

    _install_mock_http_client(monkeypatch, handle_request)
    adapter = SlackAdapter(_slack_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    result = card_messaging.update_card(
        SlackMessageReference("C1", "1000.1"),
        _card_intent(),
        OpaqueMetadata(entries=()),
    )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.AMBIGUOUS

    adapter.close()


def test_slack_webhook_rejects_out_of_scope_url_verification_without_calling_sink() -> None:
    timestamp = 1_787_000_000
    body = json.dumps({"type": "url_verification", "challenge": "challenge-1"}).encode()
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(_signed_request(body, timestamp=timestamp), sink)

    assert result.status_code == 400
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize(
    "request_kind",
    ["non_post", "missing_headers", "invalid_timestamp", "malformed_json", "unsupported_payload"],
)
def test_slack_webhook_rejects_invalid_request_shapes_without_calling_sink(request_kind: str) -> None:
    timestamp = 1_787_000_000
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())
    if request_kind == "non_post":
        request = WebhookRequest(
            method="GET",
            headers=(),
            query=(),
            body=b"",
            received_at=datetime.fromtimestamp(timestamp, tz=UTC),
        )
        expected_status = 405
    elif request_kind == "missing_headers":
        request = WebhookRequest(
            method="POST",
            headers=(),
            query=(),
            body=b"{}",
            received_at=datetime.fromtimestamp(timestamp, tz=UTC),
        )
        expected_status = 401
    elif request_kind == "invalid_timestamp":
        request = WebhookRequest(
            method="POST",
            headers=(("x-slack-request-timestamp", "invalid"), ("x-slack-signature", "v0=invalid")),
            query=(),
            body=b"{}",
            received_at=datetime.fromtimestamp(timestamp, tz=UTC),
        )
        expected_status = 401
    else:
        body = b"not-json" if request_kind == "malformed_json" else b'{"type":"app_rate_limited"}'
        request = _signed_request(body, timestamp=timestamp)
        expected_status = 400

    result = adapter.webhook_events.handle(request, sink)

    assert result.status_code == expected_status
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize(
    "body",
    [
        json.dumps(
            {
                "type": "event_callback",
                "team_id": " ",
                "event": {"type": "message", "text": "Hello"},
            }
        ).encode(),
        json.dumps(
            {
                "type": "event_callback",
                "team_id": "T123",
                "event_time": 10**30,
                "event": {"type": "message", "text": "Hello"},
            }
        ).encode(),
    ],
    ids=("blank_team_id", "out_of_range_event_time"),
)
def test_slack_webhook_rejects_malformed_authenticated_events_without_calling_sink(body: bytes) -> None:
    timestamp = 1_787_000_000
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(_signed_request(body, timestamp=timestamp), sink)

    assert result.status_code == 400
    assert sink.events == []

    adapter.close()


def test_slack_events_api_rejects_blank_event_type_without_calling_sink() -> None:
    timestamp = 1_787_000_000
    body = json.dumps(
        {
            "type": "event_callback",
            "team_id": "T123",
            "event": {"type": " ", "text": "Hello"},
        }
    ).encode()
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(_signed_request(body, timestamp=timestamp), sink)

    assert result.status_code == 400
    assert sink.events == []
    adapter.close()


def test_slack_webhook_rejects_out_of_scope_events_api_delivery_without_calling_sink() -> None:
    timestamp = 1_787_000_000
    body = json.dumps(
        {
            "type": "event_callback",
            "team_id": "T123",
            "event_id": "Ev123",
            "event_time": timestamp - 1,
            "event": {"type": "message", "text": "Hello", "blocks": [{"type": "section"}]},
        }
    ).encode()
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(_signed_request(body, timestamp=timestamp), sink)

    assert result.status_code == 400
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize("rejection_kind", ["wrong_signature", "stale_timestamp"])
def test_slack_webhook_rejects_unauthenticated_or_stale_requests_without_calling_sink(
    rejection_kind: str,
) -> None:
    timestamp = 1_787_000_000
    body = json.dumps(
        {
            "type": "event_callback",
            "team_id": "T123",
            "event": {"type": "message", "text": "Hello"},
        }
    ).encode()
    request = (
        _signed_request(body, timestamp=timestamp, signature_override="v0=invalid")
        if rejection_kind == "wrong_signature"
        else _signed_request(
            body,
            timestamp=timestamp,
            received_at=datetime.fromtimestamp(timestamp + 301, tz=UTC),
        )
    )
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(request, sink)

    assert result.status_code == 401
    assert sink.events == []

    adapter.close()


def test_slack_webhook_acknowledges_accepted_replay_without_trusting_retry_headers() -> None:
    timestamp = 1_787_000_000
    body = urlencode(
        {
            "payload": json.dumps(
                {
                    "type": "block_actions",
                    "team": {"id": "T123"},
                    "actions": [{"type": "button", "action_id": "approve", "value": _encoded_submit_action_value()}],
                }
            )
        }
    ).encode()
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    first = adapter.webhook_events.handle(
        _signed_request(body, timestamp=timestamp, content_type="application/x-www-form-urlencoded"), sink
    )
    header_modified_replay = adapter.webhook_events.handle(
        _signed_request(
            body,
            timestamp=timestamp,
            content_type="application/x-www-form-urlencoded",
            extra_headers=(("x-slack-retry-num", "1"), ("x-slack-retry-reason", "http_timeout")),
        ),
        sink,
    )
    plain_replay = adapter.webhook_events.handle(
        _signed_request(body, timestamp=timestamp, content_type="application/x-www-form-urlencoded"), sink
    )

    assert first.status_code == 200
    assert header_modified_replay.status_code == 200
    assert plain_replay.status_code == 200
    assert len(sink.events) == 1

    adapter.close()


def test_slack_webhook_redelivers_after_retry_then_remembers_acceptance() -> None:
    timestamp = 1_787_000_000
    body = urlencode(
        {
            "payload": json.dumps(
                {
                    "type": "block_actions",
                    "team": {"id": "T123"},
                    "actions": [{"type": "button", "action_id": "approve", "value": _encoded_submit_action_value()}],
                }
            )
        }
    ).encode()
    sink = _RecordingSink(EventAcceptance.RETRY)
    adapter = SlackAdapter(_slack_config())

    first = adapter.webhook_events.handle(
        _signed_request(body, timestamp=timestamp, content_type="application/x-www-form-urlencoded"), sink
    )
    sink.acceptance = EventAcceptance.ACCEPTED
    accepted_redelivery = adapter.webhook_events.handle(
        _signed_request(
            body,
            timestamp=timestamp,
            content_type="application/x-www-form-urlencoded",
            extra_headers=(("x-slack-retry-num", "1"), ("x-slack-retry-reason", "http_timeout")),
        ),
        sink,
    )
    accepted_replay = adapter.webhook_events.handle(
        _signed_request(body, timestamp=timestamp, content_type="application/x-www-form-urlencoded"), sink
    )

    assert first.status_code == 503
    assert accepted_redelivery.status_code == 200
    assert accepted_replay.status_code == 200
    assert len(sink.events) == 2

    adapter.close()


@pytest.mark.parametrize(
    ("acceptance", "expected_status"),
    [(EventAcceptance.ACCEPTED, 200), (EventAcceptance.RETRY, 503)],
)
def test_slack_interactive_action_is_authenticated_and_mapped_to_sink(
    acceptance: EventAcceptance,
    expected_status: int,
) -> None:
    timestamp = 1_787_000_000
    interactive_payload = {
        "type": "block_actions",
        "team": {"id": "T123"},
        "actions": [{"type": "button", "action_id": "approve", "value": _encoded_submit_action_value()}],
    }
    body = urlencode({"payload": json.dumps(interactive_payload)}).encode()
    signed_request = _signed_request(
        body,
        timestamp=timestamp,
        content_type="application/x-www-form-urlencoded",
    )
    sink = _RecordingSink(acceptance)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(signed_request, sink)
    replay = adapter.webhook_events.handle(
        _signed_request(
            body,
            timestamp=timestamp,
            content_type="application/x-www-form-urlencoded",
            extra_headers=(("x-slack-retry-num", "1"), ("x-slack-retry-reason", "http_timeout")),
        ),
        sink,
    )

    assert result.status_code == expected_status
    assert replay.status_code == expected_status
    assert len(sink.events) == (1 if acceptance is EventAcceptance.ACCEPTED else 2)
    assert sink.events[0].provider_event_id is None
    assert sink.events[0].provider_event_type == "block_actions"

    adapter.close()


def test_slack_interactive_action_rejects_blank_team_id_without_calling_sink() -> None:
    timestamp = 1_787_000_000
    interactive_payload = {
        "type": "block_actions",
        "team": {"id": " "},
        "actions": [{"action_id": "approve", "value": "approved"}],
    }
    body = urlencode({"payload": json.dumps(interactive_payload)}).encode()
    signed_request = _signed_request(
        body,
        timestamp=timestamp,
        content_type="application/x-www-form-urlencoded",
    )
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(signed_request, sink)

    assert result.status_code == 400
    assert sink.events == []
    adapter.close()


def test_slack_interactive_action_rejects_blank_payload_type_without_calling_sink() -> None:
    timestamp = 1_787_000_000
    interactive_payload = {
        "type": " ",
        "team": {"id": "T123"},
        "actions": [{"action_id": "approve", "value": "approved"}],
    }
    body = urlencode({"payload": json.dumps(interactive_payload)}).encode()
    request = _signed_request(
        body,
        timestamp=timestamp,
        content_type="application/x-www-form-urlencoded",
    )
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(request, sink)

    assert result.status_code == 400
    assert sink.events == []
    adapter.close()


def test_slack_webhook_rejects_out_of_scope_slash_command_without_calling_sink() -> None:
    timestamp = 1_787_000_000
    body = _slash_command_body()
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(
        _signed_request(body, timestamp=timestamp, content_type="application/x-www-form-urlencoded"),
        sink,
    )
    assert result.status_code == 400
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize(
    "command_fields",
    [
        (),
        (("command", ""),),
        (("command", " "),),
    ],
)
def test_slack_slash_command_rejects_missing_or_blank_command_before_the_sink(
    command_fields: tuple[tuple[str, str], ...],
) -> None:
    timestamp = 1_787_000_000
    body = urlencode(
        (
            ("team_id", "T123"),
            *command_fields,
            ("text", "request-1"),
        )
    ).encode()
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(
        _signed_request(body, timestamp=timestamp, content_type="application/x-www-form-urlencoded"),
        sink,
    )

    assert result.status_code == 400
    assert sink.events == []
    adapter.close()


def test_slack_slash_command_rejects_body_tampering_before_the_sink() -> None:
    timestamp = 1_787_000_000
    original_body = _slash_command_body()
    original_request = _signed_request(
        original_body,
        timestamp=timestamp,
        content_type="application/x-www-form-urlencoded",
    )
    tampered_request = WebhookRequest(
        method=original_request.method,
        headers=original_request.headers,
        query=original_request.query,
        body=_slash_command_body(text="tampered"),
        received_at=original_request.received_at,
    )
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = SlackAdapter(_slack_config())

    result = adapter.webhook_events.handle(tampered_request, sink)

    assert result.status_code == 401
    assert sink.events == []
    adapter.close()
