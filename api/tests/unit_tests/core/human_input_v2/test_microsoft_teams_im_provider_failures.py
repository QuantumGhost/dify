"""Microsoft Teams negative HTTP and cryptographic boundary tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import override

import httpx
import jwt
import jwt.algorithms
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import JsonValue, TypeAdapter

import core.human_input_v2.im_provider.providers.microsoft_teams as teams_provider
from core.human_input_v2.im_provider import (
    AuthenticatedIMEvent,
    CardAction,
    CardActionKind,
    CardIntent,
    DirectorySnapshot,
    EventAcceptance,
    IMEventSink,
    MessageAccepted,
    MicrosoftTeamsAdapter,
    MicrosoftTeamsAdapterConfig,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
    TeamsMessageReference,
    TeamsPersonalConversationDestination,
    WebhookRequest,
    thaw_json_value,
)

_SERVICE_URL = "https://smba.trafficmanager.net/emea"


def _config() -> MicrosoftTeamsAdapterConfig:
    return MicrosoftTeamsAdapterConfig(
        tenant_id="tenant-1",
        client_id="graph-client",
        client_secret="secret-test",
        bot_app_id="bot-app",
        trusted_service_url_origins=("https://smba.trafficmanager.net",),
    )


def _graph_token(*roles: str) -> str:
    return jwt.encode({"roles": roles}, key="", algorithm="none")


def _destination() -> TeamsPersonalConversationDestination:
    return TeamsPersonalConversationDestination(_SERVICE_URL, "conversation-1", "user-1")


def _install_http_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    monkeypatch.setattr(
        teams_provider,
        "_build_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _raise_connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Microsoft endpoint is unavailable", request=request)


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("token_transport", OperationFailureCode.PROVIDER),
        ("token_malformed", OperationFailureCode.PROVIDER),
        ("token_invalid_jwt", OperationFailureCode.PROVIDER),
        ("token_invalid_roles", OperationFailureCode.PROVIDER),
    ],
)
def test_teams_credential_failures_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_code: OperationFailureCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            if scenario == "token_transport":
                return _raise_connect_error(request)
            if scenario == "token_malformed":
                return httpx.Response(200, json={"access_token": "missing-expiry"})
            if scenario == "token_invalid_jwt":
                return httpx.Response(200, json={"access_token": "not-a-jwt", "expires_in": 3600})
            if scenario == "token_invalid_roles":
                invalid_roles_token = jwt.encode({"roles": "User.Read.All"}, key="", algorithm="none")
                return httpx.Response(200, json={"access_token": invalid_roles_token, "expires_in": 3600})
            return httpx.Response(
                200,
                json={
                    "access_token": _graph_token("Organization.Read.All", "User.Read.All"),
                    "expires_in": 3600,
                },
            )
        raise AssertionError("credential testing must not call an unused Microsoft Graph resource API")

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code

    adapter.close()


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("token_failure", OperationFailureCode.PROVIDER),
        ("missing_permission", OperationFailureCode.MISSING_PERMISSION),
        ("late_transport", OperationFailureCode.DIRECTORY_INCOMPLETE),
        ("malformed", OperationFailureCode.DIRECTORY_INCOMPLETE),
        ("rejected", OperationFailureCode.DIRECTORY_INCOMPLETE),
        ("invalid_user", OperationFailureCode.DIRECTORY_INCOMPLETE),
        ("invalid_retry_after", OperationFailureCode.DIRECTORY_INCOMPLETE),
        ("retry_exhausted", OperationFailureCode.DIRECTORY_INCOMPLETE),
    ],
)
def test_teams_directory_failures_return_no_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_code: OperationFailureCode,
) -> None:
    graph_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal graph_requests
        if request.url.host == "login.microsoftonline.com":
            if scenario == "token_failure":
                return httpx.Response(200, json={"access_token": "not-a-jwt", "expires_in": 3600})
            roles = () if scenario == "missing_permission" else ("User.Read.All",)
            return httpx.Response(200, json={"access_token": _graph_token(*roles), "expires_in": 3600})
        graph_requests += 1
        if scenario == "late_transport":
            if graph_requests == 1:
                return httpx.Response(
                    200,
                    json={
                        "value": [{"id": "U1", "displayName": "Ada", "mail": None}],
                        "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=next",
                    },
                )
            return _raise_connect_error(request)
        if scenario == "malformed":
            return httpx.Response(200, json={"users": []})
        if scenario == "rejected":
            return httpx.Response(503, json={"value": []})
        if scenario == "invalid_user":
            return httpx.Response(200, json={"value": [{"id": "", "displayName": "Ada", "mail": None}]})
        if scenario == "invalid_retry_after":
            return httpx.Response(429, headers={"retry-after": "later"})
        return httpx.Response(429, headers={"retry-after": "0"})

    monkeypatch.setattr(teams_provider.time, "sleep", lambda seconds: None)
    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code

    adapter.close()


def test_teams_directory_retries_rate_limit_and_reads_account_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_requests = 0
    requested_select = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal graph_requests, requested_select
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(
                200,
                json={
                    "access_token": _graph_token("User.Read.All", "User.EnableDisableAccount.All"),
                    "expires_in": 3600,
                },
            )
        graph_requests += 1
        requested_select = request.url.params["$select"]
        if graph_requests == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={"value": [{"id": "U1", "displayName": "Ada", "mail": None, "accountEnabled": False}]},
        )

    sleeps: list[int] = []
    monkeypatch.setattr(teams_provider.time, "sleep", sleeps.append)
    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, DirectorySnapshot)
    assert result.entries[0].available is False
    assert "accountEnabled" in requested_select
    assert sleeps == [0]

    adapter.close()


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("token_failure", OperationFailureCode.AUTHENTICATION),
        ("transport", OperationFailureCode.PROVIDER),
        ("forbidden", OperationFailureCode.DESTINATION_UNREACHABLE),
        ("provider", OperationFailureCode.PROVIDER),
    ],
)
def test_teams_destination_failures_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_code: OperationFailureCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            if scenario == "token_failure":
                return httpx.Response(401, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        if scenario == "transport":
            return _raise_connect_error(request)
        if scenario == "forbidden":
            return httpx.Response(403)
        return httpx.Response(500)

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.messaging.test_destination(_destination())

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code

    adapter.close()


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("token_failure", OperationFailureCode.AUTHENTICATION),
        ("transport", OperationFailureCode.AMBIGUOUS),
        ("provider", OperationFailureCode.PROVIDER),
        ("malformed", OperationFailureCode.AMBIGUOUS),
    ],
)
def test_teams_send_failures_make_one_activity_call(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_code: OperationFailureCode,
) -> None:
    activity_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal activity_requests
        if request.url.host == "login.microsoftonline.com":
            if scenario == "token_failure":
                return httpx.Response(401, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        activity_requests += 1
        if scenario == "transport":
            return _raise_connect_error(request)
        if scenario == "provider":
            return httpx.Response(503, json={"error": {"code": "ServiceUnavailable"}})
        return httpx.Response(200, json={"accepted": True})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.messaging.send_text(_destination(), "Hello")

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    assert activity_requests == (0 if scenario == "token_failure" else 1)

    adapter.close()


def test_teams_full_card_rendering_and_wrong_update_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        activity_id = "activity-1" if request.method == "POST" else "different-activity"
        return httpx.Response(200, json={"id": activity_id}, headers={"request-id": "request-1"})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None
    intent = CardIntent(
        "Approval",
        "Review the deployment.",
        (("Environment", "Production"),),
        (
            CardAction("details", "Details", CardActionKind.OPEN_URL, "https://example.com/details"),
            CardAction("approve", "Approve", CardActionKind.SUBMIT, "approved"),
        ),
        "Review the deployment.",
    )

    assessment = card_messaging.assess(intent)
    send_result = card_messaging.send_card(
        _destination(),
        intent,
        OpaqueMetadata(entries=(("form_id", "form-1"),)),
    )
    update_result = card_messaging.update_card(
        TeamsMessageReference(_SERVICE_URL, "conversation-1", "user-1", "activity-1"),
        intent,
        OpaqueMetadata(entries=(("form_id", "form-2"),)),
    )

    assert not isinstance(assessment, OperationFailure)
    assert assessment.representable is True
    assert isinstance(send_result, MessageAccepted)
    assert send_result.provider_request_id == "request-1"
    assert isinstance(update_result, OperationFailure)
    assert update_result.code is OperationFailureCode.AMBIGUOUS
    send_request = TypeAdapter(dict[str, JsonValue]).validate_json(requests[1].content)
    update_request = TypeAdapter(dict[str, JsonValue]).validate_json(requests[2].content)

    def card_from(request_body: dict[str, JsonValue]) -> dict[str, JsonValue]:
        attachments = TypeAdapter(list[dict[str, JsonValue]]).validate_python(request_body["attachments"])
        return TypeAdapter(dict[str, JsonValue]).validate_python(attachments[0]["content"])

    send_card = card_from(send_request)
    update_card = card_from(update_request)
    assert send_card["body"] == update_card["body"]
    assert len(TypeAdapter(list[JsonValue]).validate_python(send_card["body"])) == 3
    send_actions = TypeAdapter(list[dict[str, JsonValue]]).validate_python(send_card["actions"])
    update_actions = TypeAdapter(list[dict[str, JsonValue]]).validate_python(update_card["actions"])
    expected_open_url = {
        "type": "Action.OpenUrl",
        "title": "Details",
        "url": "https://example.com/details",
    }
    assert send_actions[0] == expected_open_url
    assert update_actions[0] == expected_open_url
    assert send_actions[1] == {
        "type": "Action.Submit",
        "title": "Approve",
        "data": {
            "action_id": "approve",
            "value": "approved",
            "metadata": {"form_id": "form-1"},
        },
    }
    assert update_actions[1] == {
        "type": "Action.Submit",
        "title": "Approve",
        "data": {
            "action_id": "approve",
            "value": "approved",
            "metadata": {"form_id": "form-2"},
        },
    }

    adapter.close()


def test_teams_card_empty_metadata_is_nested_in_every_submit_action(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        return httpx.Response(200, json={"id": "activity-1"})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())
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

    result = card_messaging.send_card(_destination(), intent, OpaqueMetadata(entries=()))

    assert isinstance(result, MessageAccepted)
    request_body = TypeAdapter(dict[str, JsonValue]).validate_json(requests[1].content)
    attachments = TypeAdapter(list[dict[str, JsonValue]]).validate_python(request_body["attachments"])
    card = TypeAdapter(dict[str, JsonValue]).validate_python(attachments[0]["content"])
    actions = TypeAdapter(list[dict[str, JsonValue]]).validate_python(card["actions"])
    assert [action["data"] for action in actions] == [
        {"action_id": "approve", "value": "approved", "metadata": {}},
        {"action_id": "reject", "value": "rejected", "metadata": {}},
    ]
    adapter.close()


@dataclass
class _Sink(IMEventSink):
    acceptance: EventAcceptance
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        return self.acceptance


def _signed_activity_request(
    body: bytes,
    *,
    private_key: rsa.RSAPrivateKey,
    now: datetime,
    algorithm: str = "RS256",
    key_id: str = "key-1",
    audience: str = "bot-app",
) -> WebhookRequest:
    key: rsa.RSAPrivateKey | str = private_key if algorithm == "RS256" else "unit-hmac-test-key-with-32-bytes"
    token = jwt.encode(
        {
            "iss": "https://api.botframework.com",
            "aud": audience,
            "serviceurl": _SERVICE_URL,
            "nbf": now - timedelta(minutes=1),
            "exp": now + timedelta(minutes=5),
        },
        key,
        algorithm=algorithm,
        headers={"kid": key_id},
    )
    return WebhookRequest("POST", (("authorization", f"Bearer {token}"),), (), body, now)


@pytest.mark.parametrize(
    "scenario",
    [
        "wrong_method",
        "missing_bearer",
        "wrong_issuer",
        "wrong_alg",
        "unknown_kid",
        "wrong_channel_endorsement",
        "missing_channel_with_endorsement",
        "wrong_audience",
    ],
)
def test_teams_activity_rejects_invalid_boundary_without_sink(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256"})
    if scenario in {"wrong_channel_endorsement", "missing_channel_with_endorsement", "wrong_audience"}:
        public_jwk["endorsements"] = ["msteams"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openidconfiguration"):
            issuer = "https://wrong.example" if scenario == "wrong_issuer" else "https://api.botframework.com"
            return httpx.Response(200, json={"issuer": issuer, "jwks_uri": "https://login.botframework.com/keys"})
        return httpx.Response(200, json={"keys": [public_jwk]})

    _install_http_client(monkeypatch, handler)
    now = datetime.now(UTC)
    body = json.dumps(
        {
            "type": "message",
            "channelId": "webchat" if scenario == "wrong_channel_endorsement" else "msteams",
            "serviceUrl": _SERVICE_URL,
            "channelData": {"tenant": {"id": "tenant-1"}},
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    if scenario == "missing_channel_with_endorsement":
        activity_body = json.loads(body)
        del activity_body["channelId"]
        body = json.dumps(activity_body).encode()
    request = _signed_activity_request(
        body,
        private_key=private_key,
        now=now,
        algorithm="HS256" if scenario == "wrong_alg" else "RS256",
        key_id="missing-key" if scenario == "unknown_kid" else "key-1",
        audience="other-bot" if scenario == "wrong_audience" else "bot-app",
    )
    if scenario == "wrong_method":
        request = WebhookRequest("GET", request.headers, (), body, now)
    elif scenario == "missing_bearer":
        request = WebhookRequest("POST", (), (), body, now)
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.webhook_events.handle(request, sink)

    assert result.status_code == 401
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize(
    "submit_value",
    [
        pytest.param({"action_id": "approve"}, id="missing-value"),
        pytest.param({"value": "approved"}, id="missing-action-id"),
        pytest.param({"action_id": " ", "value": "approved"}, id="blank-action-id"),
        pytest.param({"action_id": "approve", "value": " "}, id="blank-value"),
        pytest.param(
            {"action_id": "approve", "value": "approved", "metadata": []},
            id="metadata-not-object",
        ),
        pytest.param(
            {"action_id": "approve", "value": "approved", "metadata": {"form_id": 1}},
            id="metadata-non-string-value",
        ),
        pytest.param(["approve", "approved"], id="malformed-value"),
    ],
)
def test_teams_action_submit_rejects_malformed_value_before_sink(
    monkeypatch: pytest.MonkeyPatch,
    submit_value: JsonValue,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256", "endorsements": ["msteams"]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openidconfiguration"):
            return httpx.Response(
                200, json={"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/keys"}
            )
        return httpx.Response(200, json={"keys": [public_jwk]})

    _install_http_client(monkeypatch, handler)
    now = datetime.now(UTC)
    body = json.dumps(
        {
            "type": "message",
            "channelId": "msteams",
            "serviceUrl": _SERVICE_URL,
            "channelData": {"tenant": {"id": "tenant-1"}},
            "value": submit_value,
        }
    ).encode()
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.webhook_events.handle(
        _signed_activity_request(body, private_key=private_key, now=now),
        sink,
    )

    assert result.status_code == 400
    assert sink.events == []

    adapter.close()


def test_teams_action_submit_accepts_legacy_value_without_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256", "endorsements": ["msteams"]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openidconfiguration"):
            return httpx.Response(
                200, json={"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/keys"}
            )
        return httpx.Response(200, json={"keys": [public_jwk]})

    _install_http_client(monkeypatch, handler)
    now = datetime.now(UTC)
    body = json.dumps(
        {
            "type": "message",
            "channelId": "msteams",
            "serviceUrl": _SERVICE_URL,
            "channelData": {"tenant": {"id": "tenant-1"}},
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.webhook_events.handle(
        _signed_activity_request(body, private_key=private_key, now=now),
        sink,
    )

    assert result.status_code == 200
    assert result.headers == ()
    assert result.body == b""
    assert len(sink.events) == 1
    provider_payload = thaw_json_value(sink.events[0].provider_payload)
    assert isinstance(provider_payload, dict)
    assert provider_payload["value"] == {"action_id": "approve", "value": "approved"}

    adapter.close()
