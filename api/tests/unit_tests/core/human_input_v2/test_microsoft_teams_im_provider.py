"""Microsoft Teams adapter tests at Graph and Bot Framework HTTP boundaries."""

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
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AuthenticatedIMEvent,
    CardIntent,
    CredentialTestSuccess,
    DirectoryEntry,
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


def _config() -> MicrosoftTeamsAdapterConfig:
    return MicrosoftTeamsAdapterConfig(
        tenant_id="tenant-1",
        client_id="graph-client",
        client_secret="secret-test",
        bot_app_id="bot-app",
        trusted_service_url_origins=("https://smba.trafficmanager.net",),
    )


def _token(roles: tuple[str, ...]) -> str:
    return jwt.encode({"roles": roles}, key="", algorithm="none")


def _install_http_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    monkeypatch.setattr(
        teams_provider,
        "_build_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


@dataclass
class _Sink(IMEventSink):
    acceptance: EventAcceptance
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        return self.acceptance


def _activity_request(
    body: bytes,
    *,
    private_key: rsa.RSAPrivateKey,
    now: datetime,
    key_id: str = "key-1",
    service_url_claim: str = "https://smba.trafficmanager.net/emea",
    audience: str = "bot-app",
) -> WebhookRequest:
    token = jwt.encode(
        {
            "iss": "https://api.botframework.com",
            "aud": audience,
            "serviceurl": service_url_claim,
            "nbf": now - timedelta(minutes=1),
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )
    return WebhookRequest(
        "POST",
        (("authorization", f"Bearer {token}"), ("content-type", "application/json")),
        (),
        body,
        now,
    )


def test_teams_rejected_token_response_is_authentication_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_http_client(
        monkeypatch,
        lambda request: httpx.Response(401, json={"error": "invalid_client"}),
    )
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.AUTHENTICATION

    adapter.close()


def test_teams_update_404_is_stale_even_with_provider_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        return httpx.Response(404, json={"error": {"code": "NotFound", "message": "Activity was not found"}})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    result = card_messaging.update_card(
        TeamsMessageReference(
            "https://smba.trafficmanager.net/emea",
            "conversation-1",
            "user-1",
            "missing-activity",
        ),
        CardIntent(None, "Review", (), (), "Review"),
        OpaqueMetadata(entries=()),
    )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.STALE_REFERENCE

    adapter.close()


def test_teams_activity_refreshes_jwks_when_signing_key_rotates(monkeypatch: pytest.MonkeyPatch) -> None:
    first_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    second_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    first_public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(first_private_key.public_key()))
    second_public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(second_private_key.public_key()))
    first_public_jwk.update({"kid": "key-1", "alg": "RS256"})
    second_public_jwk.update({"kid": "key-2", "alg": "RS256"})
    jwks_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal jwks_requests
        if request.url.path.endswith("openidconfiguration"):
            return httpx.Response(
                200, json={"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/keys"}
            )
        jwks_requests += 1
        return httpx.Response(200, json={"keys": [first_public_jwk if jwks_requests == 1 else second_public_jwk]})

    _install_http_client(monkeypatch, handler)
    now = datetime.now(UTC)
    body = json.dumps(
        {
            "type": "message",
            "serviceUrl": "https://smba.trafficmanager.net/emea",
            "channelData": {"tenant": {"id": "tenant-1"}},
            "conversation": {"id": "conversation-1"},
            "text": "Hello",
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = MicrosoftTeamsAdapter(_config())

    first_result = adapter.webhook_events.handle(
        _activity_request(body, private_key=first_private_key, now=now),
        sink,
    )
    second_result = adapter.webhook_events.handle(
        _activity_request(body, private_key=second_private_key, now=now, key_id="key-2"),
        sink,
    )

    assert first_result.status_code == 200
    assert second_result.status_code == 200
    assert jwks_requests == 2
    assert len(sink.events) == 2

    adapter.close()


def test_teams_activity_rejects_bound_tenant_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256"})

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
            "serviceUrl": "https://smba.trafficmanager.net/emea",
            "channelData": {"tenant": {"id": "other-tenant"}},
            "conversation": {"id": "conversation-1"},
            "text": "Hello",
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.webhook_events.handle(_activity_request(body, private_key=private_key, now=now), sink)

    assert result.status_code == 401
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize(
    "next_link",
    [
        "http://graph.microsoft.com/v1.0/users?$skiptoken=next",
        "https://graph.microsoft.com.evil.example/v1.0/users?$skiptoken=next",
        "https://user@graph.microsoft.com/v1.0/users?$skiptoken=next",
        "https://graph.microsoft.com:444/v1.0/users?$skiptoken=next",
    ],
)
def test_teams_directory_rejects_untrusted_next_link_before_sending_graph_token(
    monkeypatch: pytest.MonkeyPatch,
    next_link: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(
                200,
                json={
                    "access_token": _token(("Organization.Read.All", "User.Read.All")),
                    "expires_in": 3600,
                },
            )
        if len(requests) == 2:
            return httpx.Response(200, json={"value": [], "@odata.nextLink": next_link})
        return httpx.Response(200, json={"value": []})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    assert len(requests) == 2
    assert requests[-1].url.host == "graph.microsoft.com"

    adapter.close()


@pytest.mark.parametrize(
    "service_url",
    [
        "http://smba.trafficmanager.net/emea",
        "https://smba.trafficmanager.net.evil.example/emea",
        "https://user@smba.trafficmanager.net/emea",
        "https://smba.trafficmanager.net:444/emea",
        "https://smba.trafficmanager.net/emea?region=other",
    ],
)
def test_teams_messaging_rejects_untrusted_service_url_before_requesting_bot_token(
    monkeypatch: pytest.MonkeyPatch,
    service_url: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.messaging.send_text(
        TeamsPersonalConversationDestination(service_url, "conversation-1", "user-1"),
        "Hello",
    )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.INVALID_DESTINATION
    assert requests == []

    adapter.close()


def test_teams_empty_service_origin_allowlist_disables_outbound_messaging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = MicrosoftTeamsAdapterConfig(
        tenant_id="tenant-1",
        client_id="graph-client",
        client_secret="secret-test",
        bot_app_id="bot-app",
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(config)

    result = adapter.messaging.test_destination(
        TeamsPersonalConversationDestination("https://smba.trafficmanager.net/emea", "conversation-1", "user-1")
    )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.INVALID_DESTINATION
    assert requests == []

    adapter.close()


def test_teams_service_origin_allowlist_is_normalized_and_deduplicated() -> None:
    config = MicrosoftTeamsAdapterConfig(
        tenant_id="tenant-1",
        client_id="graph-client",
        client_secret="secret-test",
        bot_app_id="bot-app",
        trusted_service_url_origins=(
            "HTTPS://SMBA.TRAFFICMANAGER.NET:443/",
            "https://smba.trafficmanager.net",
        ),
    )

    assert config.trusted_service_url_origins == ("https://smba.trafficmanager.net",)


@pytest.mark.parametrize(
    "origin",
    [
        "http://smba.trafficmanager.net",
        "https://user@smba.trafficmanager.net",
        "https://smba.trafficmanager.net:444",
        "https://smba.trafficmanager.net/emea",
        "https://smba.trafficmanager.net?region=emea",
        "https://smba.trafficmanager.net#region",
    ],
)
def test_teams_service_origin_allowlist_rejects_non_origin_values(origin: str) -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        MicrosoftTeamsAdapterConfig(
            tenant_id="tenant-1",
            client_id="graph-client",
            client_secret="secret-test",
            bot_app_id="bot-app",
            trusted_service_url_origins=(origin,),
        )


def test_teams_activity_rejects_untrusted_jwks_origin_before_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256"})
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("openidconfiguration"):
            return httpx.Response(
                200,
                json={"issuer": "https://api.botframework.com", "jwks_uri": "https://attacker.example/keys"},
            )
        return httpx.Response(200, json={"keys": [public_jwk]})

    _install_http_client(monkeypatch, handler)
    now = datetime.now(UTC)
    body = json.dumps(
        {
            "type": "message",
            "serviceUrl": "https://smba.trafficmanager.net/emea",
            "channelData": {"tenant": {"id": "tenant-1"}},
            "conversation": {"id": "conversation-1"},
            "text": "Hello",
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.webhook_events.handle(_activity_request(body, private_key=private_key, now=now), sink)

    assert result.status_code == 401
    assert sink.events == []
    assert len(requests) == 1
    assert requests[0].url.host == "login.botframework.com"

    adapter.close()


def test_teams_activity_openid_and_jwks_caches_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256"})
    monotonic_now = 0.0
    metadata_requests = 0
    jwks_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal metadata_requests, jwks_requests
        if request.url.path.endswith("openidconfiguration"):
            metadata_requests += 1
            return httpx.Response(
                200, json={"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/keys"}
            )
        jwks_requests += 1
        return httpx.Response(200, json={"keys": [public_jwk]})

    monkeypatch.setattr(teams_provider.time, "monotonic", lambda: monotonic_now)
    _install_http_client(monkeypatch, handler)
    now = datetime.now(UTC)
    body = json.dumps(
        {
            "type": "message",
            "serviceUrl": "https://smba.trafficmanager.net/emea",
            "channelData": {"tenant": {"id": "tenant-1"}},
            "conversation": {"id": "conversation-1"},
            "text": "Hello",
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    request = _activity_request(body, private_key=private_key, now=now)
    sink = _Sink(EventAcceptance.RETRY)
    adapter = MicrosoftTeamsAdapter(_config())

    first_result = adapter.webhook_events.handle(request, sink)
    monotonic_now = 3601.0
    second_result = adapter.webhook_events.handle(request, sink)

    assert first_result.status_code == 500
    assert second_result.status_code == 500
    assert metadata_requests == 2
    assert jwks_requests == 2
    assert len(sink.events) == 2

    adapter.close()


def test_teams_directory_keeps_availability_unknown_without_account_status_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(
                200,
                json={
                    "access_token": _token(("Organization.Read.All", "User.Read.All")),
                    "expires_in": 3600,
                },
            )
        return httpx.Response(200, json={"value": [{"id": "U1", "displayName": "Ada", "mail": None}]})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, DirectorySnapshot)
    assert result.entries[0].available is None
    assert "accountEnabled" not in requests[-1].url.params["$select"]

    adapter.close()


def test_teams_webhook_acknowledges_accepted_replay_without_reinvoking_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256"})

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
            "serviceUrl": "https://smba.trafficmanager.net/emea",
            "channelData": {"tenant": {"id": "tenant-1"}},
            "conversation": {"id": "conversation-1"},
            "text": "Hello",
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    request = _activity_request(body, private_key=private_key, now=now)
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = MicrosoftTeamsAdapter(_config())

    first_result = adapter.webhook_events.handle(request, sink)
    replay_result = adapter.webhook_events.handle(request, sink)

    assert first_result.status_code == 200
    assert replay_result.status_code == 200
    assert len(sink.events) == 1

    adapter.close()


def test_teams_webhook_retries_unaccepted_delivery_before_remembering_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256"})

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
            "serviceUrl": "https://smba.trafficmanager.net/emea",
            "channelData": {"tenant": {"id": "tenant-1"}},
            "conversation": {"id": "conversation-1"},
            "text": "Hello",
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    request = _activity_request(body, private_key=private_key, now=now)
    sink = _Sink(EventAcceptance.RETRY)
    adapter = MicrosoftTeamsAdapter(_config())

    retry_result = adapter.webhook_events.handle(request, sink)
    sink.acceptance = EventAcceptance.ACCEPTED
    accepted_result = adapter.webhook_events.handle(request, sink)
    replay_result = adapter.webhook_events.handle(request, sink)

    assert retry_result.status_code == 500
    assert accepted_result.status_code == 200
    assert replay_result.status_code == 200
    assert len(sink.events) == 2

    adapter.close()


def test_teams_credentials_require_only_tenant_scoped_client_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(
                200,
                json={
                    "access_token": _token(("Organization.Read.All", "User.Read.All")),
                    "expires_in": 3600,
                },
            )
        raise AssertionError("credential testing must not call an unused Microsoft Graph resource API")

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, CredentialTestSuccess)
    assert result.provider is IMProvider.MS_TEAMS
    assert result.provider_tenant_id == "tenant-1"
    assert [permission.name for permission in result.permissions] == ["oauth.client_credentials"]
    token_form = httpx.QueryParams(requests[0].content.decode())
    assert token_form["grant_type"] == "client_credentials"
    assert token_form["scope"] == "https://graph.microsoft.com/.default"
    assert len(requests) == 1

    adapter.close()


def test_teams_directory_follows_exact_next_link_and_keeps_nullable_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []
    next_link = "https://graph.microsoft.com/v1.0/users?$skiptoken=next-page"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(
                200,
                json={
                    "access_token": _token(("Organization.Read.All", "User.Read.All")),
                    "expires_in": 3600,
                },
            )
        if request.url.params.get("$skiptoken") is None:
            return httpx.Response(
                200,
                json={
                    "value": [{"id": "U1", "displayName": "Ada", "mail": "ada@example.com"}],
                    "@odata.nextLink": next_link,
                },
            )
        return httpx.Response(200, json={"value": [{"id": "U2", "displayName": "Grace", "mail": None}]})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(
        MicrosoftTeamsAdapterConfig(
            tenant_id="tenant-1",
            client_id="graph-client",
            client_secret="secret-test",
            bot_app_id="bot-app",
            trusted_service_url_origins=("https://smba.trafficmanager.net",),
            directory_page_size=1,
        )
    )

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.MS_TEAMS,
        provider_tenant_id="tenant-1",
        entries=(
            DirectoryEntry("U1", "Ada", "ada@example.com", None),
            DirectoryEntry("U2", "Grace", None, None),
        ),
    )
    assert requests[-2].url.params["$top"] == "1"
    assert str(requests[-1].url) == next_link

    adapter.close()


def test_teams_messaging_uses_separate_bot_token_and_exact_activity_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        if request.method == "GET":
            return httpx.Response(200, json={"id": "user-1"})
        return httpx.Response(200, json={"id": "activity-1"})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())
    destination = TeamsPersonalConversationDestination(
        service_url="https://smba.trafficmanager.net/emea",
        conversation_id="conversation-1",
        user_id="user-1",
    )

    destination_result = adapter.messaging.test_destination(destination)
    send_result = adapter.messaging.send_text(destination, "Hello")
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None
    card_intent = CardIntent(None, "Review", (), (), "Review")
    card_result = card_messaging.send_card(destination, card_intent, OpaqueMetadata(entries=()))
    reference = TeamsMessageReference(
        "https://smba.trafficmanager.net/emea",
        "conversation-1",
        "user-1",
        "activity-1",
    )
    update_result = card_messaging.update_card(reference, card_intent, OpaqueMetadata(entries=()))

    assert destination_result is None
    assert send_result == MessageAccepted(reference, None)
    assert card_result == MessageAccepted(reference, None)
    assert update_result == MessageAccepted(reference, None)
    token_requests = [request for request in requests if request.url.host == "login.microsoftonline.com"]
    assert len(token_requests) == 1
    token_form = httpx.QueryParams(token_requests[0].content.decode())
    assert token_form["scope"] == "https://api.botframework.com/.default"
    assert requests[1].url.path == "/emea/v3/conversations/conversation-1/members/user-1"
    assert requests[2].url.path == "/emea/v3/conversations/conversation-1/activities"
    assert requests[4].url.path == "/emea/v3/conversations/conversation-1/activities/activity-1"
    card_body = TypeAdapter(dict[str, JsonValue]).validate_json(requests[3].content)
    attachment = TypeAdapter(list[dict[str, JsonValue]]).validate_python(card_body["attachments"])[0]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert all(request.headers["authorization"] == "Bearer bot-token" for request in requests[1:])

    adapter.close()


def test_teams_destination_encodes_conversation_and_user_ids_as_single_path_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    user_id = "user/../?query#fragment%2F:用户"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        if request.method == "GET":
            return httpx.Response(200, json={"id": user_id})
        return httpx.Response(200, json={"id": "activity-1"})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())
    destination = TeamsPersonalConversationDestination(
        "https://smba.trafficmanager.net/emea",
        "conversation/../?query#fragment%2F:用户",
        user_id,
    )

    assert adapter.messaging.test_destination(destination) is None
    assert isinstance(adapter.messaging.send_text(destination, "Hello"), MessageAccepted)

    encoded_conversation = b"conversation%2F..%2F%3Fquery%23fragment%252F%3A%E7%94%A8%E6%88%B7"
    encoded_user = b"user%2F..%2F%3Fquery%23fragment%252F%3A%E7%94%A8%E6%88%B7"
    assert requests[1].url.raw_path == (b"/emea/v3/conversations/" + encoded_conversation + b"/members/" + encoded_user)
    assert requests[2].url.raw_path == b"/emea/v3/conversations/" + encoded_conversation + b"/activities"

    adapter.close()


def test_teams_card_update_encodes_activity_id_as_one_path_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    activity_id = "activity/?query#fragment%2F:用户"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        return httpx.Response(200, json={"id": activity_id})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())
    card_messaging = adapter.dynamic_card_messaging
    assert card_messaging is not None

    result = card_messaging.update_card(
        TeamsMessageReference(
            "https://smba.trafficmanager.net/emea",
            "conversation:用户",
            "user-1",
            activity_id,
        ),
        CardIntent(None, "Review", (), (), "Review"),
        OpaqueMetadata(entries=()),
    )

    assert isinstance(result, MessageAccepted)
    assert requests[1].url.raw_path == (
        b"/emea/v3/conversations/conversation%3A%E7%94%A8%E6%88%B7/activities/"
        b"activity%2F%3Fquery%23fragment%252F%3A%E7%94%A8%E6%88%B7"
    )

    adapter.close()


@pytest.mark.parametrize("operation", ["members", "send", "update"])
def test_teams_rejects_dot_path_segment_before_requesting_bot_token(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())
    destination = TeamsPersonalConversationDestination(
        "https://smba.trafficmanager.net/emea",
        ".." if operation != "update" else "conversation-1",
        "user-1",
    )

    result: MessageAccepted[TeamsMessageReference] | OperationFailure | None
    if operation == "members":
        result = adapter.messaging.test_destination(destination)
    elif operation == "send":
        result = adapter.messaging.send_text(destination, "Hello")
    else:
        card_messaging = adapter.dynamic_card_messaging
        assert card_messaging is not None
        result = card_messaging.update_card(
            TeamsMessageReference(destination.service_url, destination.conversation_id, destination.user_id, ".."),
            CardIntent(None, "Review", (), (), "Review"),
            OpaqueMetadata(entries=()),
        )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.INVALID_DESTINATION
    assert requests == []

    adapter.close()


def test_teams_encodes_tenant_id_in_token_path(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []
    tenant_id = "tenant/segment?query#fragment%2F:用户"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(
                200,
                json={
                    "access_token": _token(("Organization.Read.All", "User.Read.All")),
                    "expires_in": 3600,
                },
            )
        raise AssertionError("credential testing must not call an unused Microsoft Graph resource API")

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(
        MicrosoftTeamsAdapterConfig(
            tenant_id=tenant_id,
            client_id="graph-client",
            client_secret="secret-test",
            bot_app_id="bot-app",
        )
    )

    assert isinstance(adapter.test_credentials(), CredentialTestSuccess)

    encoded_tenant = b"tenant%2Fsegment%3Fquery%23fragment%252F%3A%E7%94%A8%E6%88%B7"
    assert requests[0].url.raw_path == b"/" + encoded_tenant + b"/oauth2/v2.0/token"
    assert len(requests) == 1

    adapter.close()


def test_teams_rejects_dot_tenant_segment_before_requesting_token(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(
        MicrosoftTeamsAdapterConfig(
            tenant_id="..",
            client_id="graph-client",
            client_secret="secret-test",
            bot_app_id="bot-app",
        )
    )

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.AUTHENTICATION
    assert requests == []

    adapter.close()


def test_teams_destination_rejects_personal_user_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        return httpx.Response(200, json={"id": "different-user"})

    _install_http_client(monkeypatch, handler)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.messaging.test_destination(
        TeamsPersonalConversationDestination("https://smba.trafficmanager.net/emea", "conversation-1", "user-1")
    )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DESTINATION_UNREACHABLE
    assert [request.url.path for request in requests] == [
        "/tenant-1/oauth2/v2.0/token",
        "/emea/v3/conversations/conversation-1/members/user-1",
    ]

    adapter.close()


@pytest.mark.parametrize(
    ("acceptance", "expected_status"),
    [(EventAcceptance.ACCEPTED, 200), (EventAcceptance.RETRY, 500)],
)
@pytest.mark.parametrize(
    ("endorsements", "channel_id"),
    [(["msteams"], "msteams"), (None, None)],
    ids=("endorsed_channel", "unendorsed_key"),
)
def test_teams_activity_jwt_validation_precedes_sink_and_maps_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    acceptance: EventAcceptance,
    expected_status: int,
    endorsements: list[str] | None,
    channel_id: str | None,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256"})
    if endorsements is not None:
        public_jwk["endorsements"] = endorsements

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openidconfiguration"):
            return httpx.Response(
                200, json={"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/keys"}
            )
        return httpx.Response(200, json={"keys": [public_jwk]})

    _install_http_client(monkeypatch, handler)
    now = datetime.now(UTC)
    activity_body = {
        "type": "message",
        "serviceUrl": "https://smba.trafficmanager.net/emea",
        "channelData": {"tenant": {"id": "tenant-1"}},
        "conversation": {"id": "conversation-1"},
        "text": "Hello",
        "value": {
            "action_id": "approve",
            "value": "approved",
            "metadata": {"form_id": "form-1", "empty_value": ""},
            "review_comment": "Ready to deploy",
            "risk_level": "high",
        },
    }
    if channel_id is not None:
        activity_body["channelId"] = channel_id
    body = json.dumps(activity_body).encode()
    sink = _Sink(acceptance)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.webhook_events.handle(_activity_request(body, private_key=private_key, now=now), sink)

    assert result.status_code == expected_status
    assert len(sink.events) == 1
    assert sink.events[0].provider_event_id is None
    assert sink.events[0].provider_event_type == "message"
    assert sink.events[0].provider_tenant_id == "tenant-1"
    assert thaw_json_value(sink.events[0].provider_payload) == activity_body

    adapter.close()


def test_teams_authenticated_activity_rejects_blank_type_without_calling_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256"})

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
            "type": "   ",
            "serviceUrl": "https://smba.trafficmanager.net/emea",
            "channelData": {"tenant": {"id": "tenant-1"}},
            "conversation": {"id": "conversation-1"},
            "text": "Hello",
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.webhook_events.handle(_activity_request(body, private_key=private_key, now=now), sink)

    assert result.status_code == 400
    assert sink.events == []

    adapter.close()


def test_teams_activity_rejects_service_url_claim_mismatch_without_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "key-1", "alg": "RS256"})

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
            "serviceUrl": "https://smba.trafficmanager.net/emea",
            "channelData": {"tenant": {"id": "tenant-1"}},
            "conversation": {"id": "conversation-1"},
            "value": {"action_id": "approve", "value": "approved"},
        }
    ).encode()
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = MicrosoftTeamsAdapter(_config())

    result = adapter.webhook_events.handle(
        _activity_request(body, private_key=private_key, now=now, service_url_claim="https://other.example"),
        sink,
    )

    assert result.status_code == 401
    assert sink.events == []

    adapter.close()
