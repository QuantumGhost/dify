"""Local TLS transport integration coverage for the concrete Teams adapter."""

from __future__ import annotations

import json
import socket
import ssl
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import cast, override
from urllib.parse import parse_qsl, urlsplit

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from jwt.algorithms import RSAAlgorithm
from pydantic import JsonValue, TypeAdapter

from core.helper import ssrf_proxy
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AuthenticatedIMEvent,
    CardIntent,
    CredentialTestSuccess,
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
)

_TARGET_HOSTS = frozenset(
    {
        "graph.microsoft.com",
        "login.botframework.com",
        "login.microsoftonline.com",
        "smba.trafficmanager.net",
    }
)
_SERVICE_URL = "https://smba.trafficmanager.net/emea"


@dataclass(frozen=True, slots=True)
class _RecordedRequest:
    method: str
    host: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class _StubResponse:
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    disconnect: bool = False


@dataclass(frozen=True, slots=True)
class _TeamsStub:
    requests: list[_RecordedRequest]


type _Responder = Callable[[_RecordedRequest], _StubResponse]
type _AddressInfo = tuple[int, int, int, str, tuple[str, int]]


def _json_response(
    payload: JsonValue,
    *,
    status_code: int = 200,
    headers: tuple[tuple[str, str], ...] = (),
) -> _StubResponse:
    return _StubResponse(
        status_code=status_code,
        body=json.dumps(payload, separators=(",", ":")).encode(),
        headers=(("content-type", "application/json"), *headers),
    )


def _graph_token(*roles: str) -> str:
    return jwt.encode({"roles": roles}, key="", algorithm="none")


def _token_response(scope: str, *, roles: tuple[str, ...] | None = None) -> _StubResponse:
    token = "bot-token" if scope == "https://api.botframework.com/.default" else _graph_token(*(roles or ()))
    return _json_response({"access_token": token, "expires_in": 3600})


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Teams integration stub")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(host) for host in sorted(_TARGET_HOSTS)]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    tls_directory = tmp_path_factory.mktemp("teams-tls")
    certificate_path = tls_directory / "certificate.pem"
    key_path = tls_directory / "private-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, key_path


@contextmanager
def _run_teams_stub(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    responder: _Responder,
) -> Generator[_TeamsStub, None, None]:
    requests: list[_RecordedRequest] = []

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self) -> None:
            content_length = int(self.headers.get("content-length", "0"))
            parsed_url = urlsplit(self.path)
            request = _RecordedRequest(
                method=self.command,
                host=self.headers.get("host", "").partition(":")[0].casefold(),
                path=parsed_url.path,
                query=dict(parse_qsl(parsed_url.query, keep_blank_values=True)),
                headers={name.casefold(): value for name, value in self.headers.items()},
                body=self.rfile.read(content_length),
            )
            requests.append(request)
            response = responder(request)
            if response.disconnect:
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(response.status_code)
            for name, value in response.headers:
                self.send_header(name, value)
            self.send_header("content-length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def do_PUT(self) -> None:
            self._handle()

        @override
        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    certificate_path, key_path = tls_material
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls_context.load_cert_chain(certificate_path, key_path)
    server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    real_getaddrinfo = socket.getaddrinfo

    def resolve(
        host: str | bytes | None,
        port: str | int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[_AddressInfo]:
        normalized_host = host.decode() if isinstance(host, bytes) else host
        resolved_host = "127.0.0.1" if normalized_host in _TARGET_HOSTS else normalized_host
        resolved_port = server.server_port if normalized_host in _TARGET_HOSTS else port
        return cast(
            list[_AddressInfo],
            real_getaddrinfo(resolved_host, resolved_port, family, type, proto, flags),
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(ssrf_proxy.dify_config, "SSRF_PROXY_ALL_URL", None)
    monkeypatch.setattr(ssrf_proxy.dify_config, "SSRF_PROXY_HTTP_URL", None)
    monkeypatch.setattr(ssrf_proxy.dify_config, "SSRF_PROXY_HTTPS_URL", None)
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate_path))
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _TeamsStub(requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _config() -> MicrosoftTeamsAdapterConfig:
    return MicrosoftTeamsAdapterConfig(
        tenant_id="tenant-1",
        client_id="graph-client",
        client_secret="integration-secret",
        bot_app_id="bot-app",
        trusted_service_url_origins=("https://smba.trafficmanager.net",),
    )


def _destination(conversation_id: str = "conversation-1") -> TeamsPersonalConversationDestination:
    return TeamsPersonalConversationDestination(_SERVICE_URL, conversation_id, "user-1")


def _public_jwk(private_key: rsa.RSAPrivateKey, key_id: str) -> dict[str, JsonValue]:
    jwk = TypeAdapter(dict[str, JsonValue]).validate_json(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": key_id, "alg": "RS256", "endorsements": ["msteams"]})
    return jwk


def _activity_body(
    *,
    tenant_id: str = "tenant-1",
    activity_type: str = "message",
    action_id: str = "approve",
    action_value: str = "approved",
) -> bytes:
    return json.dumps(
        {
            "type": activity_type,
            "channelId": "msteams",
            "serviceUrl": _SERVICE_URL,
            "channelData": {"tenant": {"id": tenant_id}},
            "conversation": {"id": "conversation-1"},
            "text": "Hello",
            "value": {"action_id": action_id, "value": action_value},
        }
    ).encode()


def _activity_request(
    body: bytes,
    *,
    private_key: rsa.RSAPrivateKey,
    now: datetime,
    key_id: str = "key-1",
    service_url_claim: str = _SERVICE_URL,
    algorithm: str = "RS256",
) -> WebhookRequest:
    signing_key: rsa.RSAPrivateKey | str = (
        private_key if algorithm == "RS256" else "integration-hmac-test-key-with-32-bytes"
    )
    token = jwt.encode(
        {
            "iss": "https://api.botframework.com",
            "aud": "bot-app",
            "serviceurl": service_url_claim,
            "nbf": now - timedelta(minutes=1),
            "exp": now + timedelta(minutes=5),
        },
        signing_key,
        algorithm=algorithm,
        headers={"kid": key_id},
    )
    return WebhookRequest(
        "POST",
        (("authorization", f"Bearer {token}"), ("content-type", "application/json")),
        (),
        body,
        now,
    )


@dataclass(slots=True)
class _Sink(IMEventSink):
    acceptance: EventAcceptance
    error: Exception | None = None
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return self.acceptance


def test_teams_public_adapter_uses_one_real_http_context_for_all_api_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    state = {"directory_page_two": 0, "activity_sends": 0}

    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.host == "login.microsoftonline.com":
            form = dict(parse_qsl(request.body.decode()))
            if form["scope"] == "https://graph.microsoft.com/.default":
                return _token_response(
                    form["scope"],
                    roles=("Organization.Read.All", "User.Read.All", "User.EnableDisableAccount.All"),
                )
            return _token_response(form["scope"])
        if request.path == "/v1.0/organization/tenant-1":
            return _json_response({"id": "tenant-1"})
        if request.path == "/v1.0/users" and "$skiptoken" not in request.query:
            return _json_response(
                {
                    "value": [
                        {
                            "id": "U1",
                            "displayName": "Ada",
                            "mail": "ada@example.com",
                            "accountEnabled": True,
                        }
                    ],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=next-page",
                }
            )
        if request.path == "/v1.0/users":
            state["directory_page_two"] += 1
            if state["directory_page_two"] == 1:
                return _json_response({}, status_code=429, headers=(("retry-after", "0"),))
            return _json_response(
                {"value": [{"id": "U2", "displayName": "Grace", "mail": None, "accountEnabled": False}]}
            )
        if request.path.endswith("/members/user-1"):
            return _json_response({"id": "user-1"})
        if "/activities" in request.path:
            if request.method == "PUT":
                return _json_response({"id": request.path.rsplit("/", 1)[-1]}, headers=(("request-id", "update"),))
            state["activity_sends"] += 1
            return _json_response(
                {"id": f"activity-{state['activity_sends']}"},
                headers=(("request-id", f"send-{state['activity_sends']}"),),
            )
        return _json_response({"error": "unexpected path"}, status_code=404)

    with _run_teams_stub(monkeypatch, tls_material, respond) as stub:
        adapter = MicrosoftTeamsAdapter(_config())
        credentials = adapter.test_credentials()
        directory = adapter.directory.read_snapshot()
        destination = _destination()
        destination_result = adapter.messaging.test_destination(destination)
        text_result = adapter.messaging.send_text(destination, "Hello")
        card_messaging = adapter.dynamic_card_messaging
        assert card_messaging is not None
        intent = CardIntent("Approval", "Review", (("Environment", "Staging"),), (), "Review")
        assessment = card_messaging.assess(intent)
        card_result = card_messaging.send_card(destination, intent, OpaqueMetadata(entries=()))
        assert isinstance(card_result, MessageAccepted)
        update_result = card_messaging.update_card(card_result.reference, intent, OpaqueMetadata(entries=()))

        assert isinstance(credentials, CredentialTestSuccess)
        assert credentials.provider_tenant_id == "tenant-1"
        assert isinstance(directory, DirectorySnapshot)
        assert [(entry.provider_user_id, entry.available) for entry in directory.entries] == [
            ("U1", True),
            ("U2", False),
        ]
        assert destination_result is None
        assert isinstance(text_result, MessageAccepted)
        assert not isinstance(assessment, OperationFailure)
        assert assessment.representable
        assert isinstance(update_result, MessageAccepted)
        assert update_result.reference == card_result.reference
        assert state == {"directory_page_two": 2, "activity_sends": 2}
        graph_requests = [request for request in stub.requests if request.host == "graph.microsoft.com"]
        assert all(request.headers["authorization"].startswith("Bearer ") for request in graph_requests)
        bot_requests = [request for request in stub.requests if request.host == "smba.trafficmanager.net"]
        assert all(request.headers["authorization"] == "Bearer bot-token" for request in bot_requests)

        adapter.close()
        adapter.close()
        request_count = len(stub.requests)
        closed_result = adapter.messaging.send_text(destination, "after close")
        assert isinstance(closed_result, OperationFailure)
        assert closed_result.code is OperationFailureCode.CLOSED
        assert len(stub.requests) == request_count


def test_teams_card_send_acquires_cold_bot_token_before_adaptive_card_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.host == "login.microsoftonline.com":
            return _token_response("https://api.botframework.com/.default")
        return _json_response({"id": "activity-card"}, headers=(("request-id", "request-card"),))

    with _run_teams_stub(monkeypatch, tls_material, respond) as stub:
        adapter = MicrosoftTeamsAdapter(_config())
        card_messaging = adapter.dynamic_card_messaging
        assert card_messaging is not None

        result = card_messaging.send_card(
            _destination(),
            CardIntent(None, "Review", (), (), "Review"),
            OpaqueMetadata(entries=(("form_id", "form-1"),)),
        )

        assert result == MessageAccepted(
            TeamsMessageReference(_SERVICE_URL, "conversation-1", "user-1", "activity-card"),
            "request-card",
        )
        assert [request.host for request in stub.requests] == [
            "login.microsoftonline.com",
            "smba.trafficmanager.net",
        ]
        activity_body = TypeAdapter(dict[str, JsonValue]).validate_json(stub.requests[-1].body)
        assert activity_body["type"] == "message"
        adapter.close()


@pytest.mark.parametrize(
    ("token_response", "expected_code"),
    [
        (_StubResponse(429, b"{}"), OperationFailureCode.RATE_LIMITED),
        (_StubResponse(500, b"{}"), OperationFailureCode.PROVIDER),
        (_StubResponse(401, b"not-json"), OperationFailureCode.PROVIDER),
        (
            _json_response({"error": "temporarily_unavailable"}, status_code=401),
            OperationFailureCode.PROVIDER,
        ),
        (_json_response({"error": "invalid_client"}, status_code=401), OperationFailureCode.AUTHENTICATION),
        (_StubResponse(200, b"not-json"), OperationFailureCode.PROVIDER),
        (_json_response({"access_token": " ", "expires_in": 3600}), OperationFailureCode.PROVIDER),
        (_json_response({"access_token": _graph_token(), "expires_in": 0}), OperationFailureCode.PROVIDER),
        (_json_response({"access_token": "invalid", "expires_in": 3600}), OperationFailureCode.PROVIDER),
        (
            _json_response(
                {"access_token": jwt.encode({"roles": "invalid"}, "", algorithm="none"), "expires_in": 3600}
            ),
            OperationFailureCode.PROVIDER,
        ),
        (
            _token_response("https://graph.microsoft.com/.default", roles=("User.Read.All",)),
            OperationFailureCode.MISSING_PERMISSION,
        ),
    ],
    ids=(
        "rate-limited",
        "service-failure",
        "malformed-rejection",
        "upstream-rejection",
        "credential-rejection",
        "malformed-success",
        "blank-token",
        "non-positive-expiry",
        "invalid-jwt",
        "invalid-roles",
        "missing-role",
    ),
)
def test_teams_credential_token_failures_are_typed_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    token_response: _StubResponse,
    expected_code: OperationFailureCode,
) -> None:
    with _run_teams_stub(monkeypatch, tls_material, lambda request: token_response) as stub:
        adapter = MicrosoftTeamsAdapter(_config())
        result = adapter.test_credentials()

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert "integration-secret" not in repr(result)
        assert len(stub.requests) == 1
        adapter.close()


@pytest.mark.parametrize("organization_kind", ["mismatch", "malformed", "rejected", "disconnect"])
def test_teams_credential_organization_failures_are_typed_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    organization_kind: str,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.host == "login.microsoftonline.com":
            return _token_response(
                "https://graph.microsoft.com/.default",
                roles=("Organization.Read.All", "User.Read.All"),
            )
        if organization_kind == "disconnect":
            return _StubResponse(0, b"", disconnect=True)
        if organization_kind == "malformed":
            return _StubResponse(200, b"not-json")
        if organization_kind == "rejected":
            return _json_response({"id": "tenant-1"}, status_code=500)
        return _json_response({"id": "other-tenant"})

    with _run_teams_stub(monkeypatch, tls_material, respond):
        adapter = MicrosoftTeamsAdapter(_config())
        result = adapter.test_credentials()

        assert isinstance(result, OperationFailure)
        expected_code = (
            OperationFailureCode.PROVIDER
            if organization_kind == "disconnect"
            else OperationFailureCode.TENANT_IDENTIFICATION
        )
        assert result.code is expected_code
        adapter.close()


@pytest.mark.parametrize(
    "failure_kind",
    ["untrusted-link", "invalid-link", "malformed", "rejected", "invalid-user", "bad-retry-after", "disconnect"],
)
def test_teams_directory_returns_no_partial_snapshot_on_real_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    failure_kind: str,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.host == "login.microsoftonline.com":
            return _token_response("https://graph.microsoft.com/.default", roles=("User.Read.All",))
        if "$skiptoken" not in request.query:
            next_link = {
                "untrusted-link": "https://attacker.example/users?$skiptoken=next",
                "invalid-link": "http://graph.microsoft.com/users?$skiptoken=next",
            }.get(failure_kind, "https://graph.microsoft.com/v1.0/users?$skiptoken=next")
            return _json_response(
                {
                    "value": [{"id": "U1", "displayName": "Ada", "mail": None}],
                    "@odata.nextLink": next_link,
                }
            )
        if failure_kind == "malformed":
            return _StubResponse(200, b"not-json")
        if failure_kind == "rejected":
            return _json_response({"value": []}, status_code=500)
        if failure_kind == "invalid-user":
            return _json_response({"value": [{"id": " ", "displayName": "Ada"}]})
        if failure_kind == "bad-retry-after":
            return _json_response({}, status_code=429, headers=(("retry-after", "invalid"),))
        if failure_kind == "disconnect":
            return _StubResponse(0, b"", disconnect=True)
        return _json_response({"value": []})

    with _run_teams_stub(monkeypatch, tls_material, respond) as stub:
        adapter = MicrosoftTeamsAdapter(_config())
        result = adapter.directory.read_snapshot()

        assert isinstance(result, OperationFailure)
        assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
        assert len(stub.requests) == (2 if failure_kind in {"untrusted-link", "invalid-link"} else 3)
        assert all(request.host != "attacker.example" for request in stub.requests)
        adapter.close()


@pytest.mark.parametrize(
    ("operation", "provider_response", "expected_code"),
    [
        ("destination-404", _json_response({}, status_code=404), OperationFailureCode.DESTINATION_UNREACHABLE),
        ("destination-500", _json_response({}, status_code=500), OperationFailureCode.PROVIDER),
        ("destination-malformed", _StubResponse(200, b"not-json"), OperationFailureCode.PROVIDER),
        (
            "destination-user-mismatch",
            _json_response({"id": "other-user"}),
            OperationFailureCode.DESTINATION_UNREACHABLE,
        ),
        ("send-rejected", _json_response({}, status_code=500), OperationFailureCode.PROVIDER),
        ("send-malformed", _StubResponse(200, b"not-json"), OperationFailureCode.AMBIGUOUS),
        ("send-missing-id", _json_response({}), OperationFailureCode.AMBIGUOUS),
        ("update-missing", _json_response({}, status_code=404), OperationFailureCode.STALE_REFERENCE),
        ("update-changed", _json_response({"id": "other-activity"}), OperationFailureCode.AMBIGUOUS),
        ("send-disconnect", _StubResponse(0, b"", disconnect=True), OperationFailureCode.AMBIGUOUS),
    ],
)
def test_teams_messaging_failures_make_one_real_bot_operation(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    operation: str,
    provider_response: _StubResponse,
    expected_code: OperationFailureCode,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.host == "login.microsoftonline.com":
            return _token_response("https://api.botframework.com/.default")
        return provider_response

    with _run_teams_stub(monkeypatch, tls_material, respond) as stub:
        adapter = MicrosoftTeamsAdapter(_config())
        result: MessageAccepted[TeamsMessageReference] | OperationFailure | None
        if operation.startswith("destination"):
            result = adapter.messaging.test_destination(_destination())
        elif operation.startswith("update"):
            card_messaging = adapter.dynamic_card_messaging
            assert card_messaging is not None
            result = card_messaging.update_card(
                TeamsMessageReference(_SERVICE_URL, "conversation-1", "user-1", "activity-1"),
                CardIntent(None, "Review", (), (), "Review"),
                OpaqueMetadata(entries=()),
            )
        else:
            result = adapter.messaging.send_text(_destination(), "Hello")

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        bot_operations = [request for request in stub.requests if request.host == "smba.trafficmanager.net"]
        assert len(bot_operations) == 1
        adapter.close()


@pytest.mark.parametrize(
    ("conversation_id", "encoded_segment"),
    [
        ("conversation/../../token", "conversation%2F..%2F..%2Ftoken"),
        ("conversation?mode=unsafe", "conversation%3Fmode%3Dunsafe"),
    ],
)
def test_teams_messaging_encodes_path_control_in_conversation_identifier(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    conversation_id: str,
    encoded_segment: str,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.host == "login.microsoftonline.com":
            return _token_response("https://api.botframework.com/.default")
        return _json_response({"id": "activity-1"})

    with _run_teams_stub(monkeypatch, tls_material, respond) as stub:
        adapter = MicrosoftTeamsAdapter(_config())
        result = adapter.messaging.send_text(_destination(conversation_id), "Hello")

        assert isinstance(result, MessageAccepted)
        bot_request = next(request for request in stub.requests if request.host == "smba.trafficmanager.net")
        assert bot_request.path == f"/emea/v3/conversations/{encoded_segment}/activities"
        assert bot_request.query == {}
        adapter.close()


def test_teams_card_update_encodes_activity_identifier_as_one_path_segment(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    activity_id = "activity/../unsafe?mode=update"

    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.host == "login.microsoftonline.com":
            return _token_response("https://api.botframework.com/.default")
        return _json_response({"id": activity_id})

    with _run_teams_stub(monkeypatch, tls_material, respond) as stub:
        adapter = MicrosoftTeamsAdapter(_config())
        card_messaging = adapter.dynamic_card_messaging
        assert card_messaging is not None
        result = card_messaging.update_card(
            TeamsMessageReference(_SERVICE_URL, "conversation-1", "user-1", activity_id),
            CardIntent(None, "Review", (), (), "Review"),
            OpaqueMetadata(entries=()),
        )

        assert isinstance(result, MessageAccepted)
        bot_request = next(request for request in stub.requests if request.host == "smba.trafficmanager.net")
        assert bot_request.path.endswith("/activities/activity%2F..%2Funsafe%3Fmode%3Dupdate")
        assert bot_request.query == {}
        adapter.close()


def test_teams_webhook_authentication_replay_and_sink_ack_lifecycle_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = _public_jwk(private_key, "key-1")

    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("openidconfiguration"):
            return _json_response(
                {"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/keys"}
            )
        return _json_response({"keys": [public_jwk]})

    with _run_teams_stub(monkeypatch, tls_material, respond) as stub:
        adapter = MicrosoftTeamsAdapter(_config())
        now = datetime.now(UTC)
        accepted_request = _activity_request(_activity_body(), private_key=private_key, now=now)
        accepted_sink = _Sink(EventAcceptance.ACCEPTED)
        accepted = adapter.webhook_events.handle(accepted_request, accepted_sink)
        replay_sink = _Sink(EventAcceptance.ACCEPTED)
        replay = adapter.webhook_events.handle(accepted_request, replay_sink)
        retry_sink = _Sink(EventAcceptance.RETRY)
        retry_request = _activity_request(
            _activity_body(action_id="retry", action_value="retry"), private_key=private_key, now=now
        )
        retry = adapter.webhook_events.handle(retry_request, retry_sink)
        retry_sink.acceptance = EventAcceptance.ACCEPTED
        accepted_redelivery = adapter.webhook_events.handle(retry_request, retry_sink)
        failing_sink = _Sink(EventAcceptance.ACCEPTED, RuntimeError("storage unavailable"))
        failed = adapter.webhook_events.handle(
            _activity_request(
                _activity_body(action_id="sink-failure", action_value="sink-failure"),
                private_key=private_key,
                now=now,
            ),
            failing_sink,
        )
        unsupported_sink = _Sink(EventAcceptance.ACCEPTED)
        unsupported = adapter.webhook_events.handle(
            _activity_request(_activity_body(activity_type="invoke"), private_key=private_key, now=now),
            unsupported_sink,
        )

        assert accepted.status_code == 200
        assert replay.status_code == 200
        assert replay_sink.events == []
        assert retry.status_code == 500
        assert accepted_redelivery.status_code == 200
        assert len(retry_sink.events) == 2
        assert failed.status_code == 500
        assert unsupported.status_code == 400
        assert unsupported.body == b""
        assert unsupported_sink.events == []
        assert accepted_sink.events[0].provider is IMProvider.MS_TEAMS
        assert accepted_sink.events[0].provider_tenant_id == "tenant-1"
        assert accepted_sink.events[0].provider_event_id is None
        assert len(stub.requests) == 2
        adapter.close()


@pytest.mark.parametrize(
    ("endorsement_kind", "expected_status"),
    [
        ("valid", 200),
        ("absent", 200),
        ("wrong-channel", 401),
        ("not-list", 401),
        ("non-string-member", 401),
        ("missing-channel", 401),
    ],
)
def test_teams_webhook_validates_signing_key_endorsements_for_activity_channel(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    endorsement_kind: str,
    expected_status: int,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = _public_jwk(private_key, "key-1")
    if endorsement_kind == "absent":
        del public_jwk["endorsements"]
    elif endorsement_kind == "wrong-channel":
        public_jwk["endorsements"] = ["webchat"]
    elif endorsement_kind == "not-list":
        public_jwk["endorsements"] = "msteams"
    elif endorsement_kind == "non-string-member":
        public_jwk["endorsements"] = ["msteams", 42]

    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("openidconfiguration"):
            return _json_response(
                {"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/keys"}
            )
        return _json_response({"keys": [public_jwk]})

    body = TypeAdapter(dict[str, JsonValue]).validate_json(_activity_body())
    if endorsement_kind == "missing-channel":
        del body["channelId"]
    with _run_teams_stub(monkeypatch, tls_material, respond):
        now = datetime.now(UTC)
        sink = _Sink(EventAcceptance.ACCEPTED)
        adapter = MicrosoftTeamsAdapter(_config())
        result = adapter.webhook_events.handle(
            _activity_request(json.dumps(body).encode(), private_key=private_key, now=now),
            sink,
        )

        assert result.status_code == expected_status
        assert len(sink.events) == (1 if expected_status == 200 else 0)
        adapter.close()


@pytest.mark.parametrize(
    "rejection_kind",
    ["tenant", "service-url", "wrong-algorithm", "missing-auth", "method", "blank-type"],
)
def test_teams_webhook_rejects_invalid_boundaries_before_sink_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    rejection_kind: str,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = _public_jwk(private_key, "key-1")

    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("openidconfiguration"):
            return _json_response(
                {"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/keys"}
            )
        return _json_response({"keys": [public_jwk]})

    with _run_teams_stub(monkeypatch, tls_material, respond):
        now = datetime.now(UTC)
        body = _activity_body(
            tenant_id="other-tenant" if rejection_kind == "tenant" else "tenant-1",
            activity_type=" " if rejection_kind == "blank-type" else "message",
        )
        request = _activity_request(
            body,
            private_key=private_key,
            now=now,
            service_url_claim="https://other.example" if rejection_kind == "service-url" else _SERVICE_URL,
            algorithm="HS256" if rejection_kind == "wrong-algorithm" else "RS256",
        )
        if rejection_kind == "missing-auth":
            request = WebhookRequest("POST", (), (), body, now)
        elif rejection_kind == "method":
            request = WebhookRequest("GET", request.headers, (), body, now)
        sink = _Sink(EventAcceptance.ACCEPTED)
        adapter = MicrosoftTeamsAdapter(_config())

        result = adapter.webhook_events.handle(request, sink)

        assert result.status_code == (400 if rejection_kind == "blank-type" else 401)
        assert sink.events == []
        adapter.close()


def test_teams_webhook_refreshes_jwks_on_unknown_key_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    first_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    second_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys = [_public_jwk(first_private_key, "key-1"), _public_jwk(second_private_key, "key-2")]
    jwks_requests = 0

    def respond(request: _RecordedRequest) -> _StubResponse:
        nonlocal jwks_requests
        if request.path.endswith("openidconfiguration"):
            return _json_response(
                {"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/keys"}
            )
        jwks_requests += 1
        return _json_response({"keys": [keys[min(jwks_requests - 1, 1)]]})

    with _run_teams_stub(monkeypatch, tls_material, respond):
        now = datetime.now(UTC)
        sink = _Sink(EventAcceptance.ACCEPTED)
        adapter = MicrosoftTeamsAdapter(_config())

        first = adapter.webhook_events.handle(
            _activity_request(_activity_body(), private_key=first_private_key, now=now),
            sink,
        )
        second = adapter.webhook_events.handle(
            _activity_request(
                _activity_body(action_id="second", action_value="second"),
                private_key=second_private_key,
                now=now,
                key_id="key-2",
            ),
            sink,
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert jwks_requests == 2
        assert len(sink.events) == 2
        adapter.close()


@pytest.mark.parametrize("metadata_kind", ["issuer", "jwks-origin", "malformed", "disconnect"])
def test_teams_webhook_rejects_untrusted_or_unavailable_verification_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    metadata_kind: str,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def respond(request: _RecordedRequest) -> _StubResponse:
        if metadata_kind == "disconnect":
            return _StubResponse(0, b"", disconnect=True)
        if metadata_kind == "malformed":
            return _StubResponse(200, b"not-json")
        return _json_response(
            {
                "issuer": "https://attacker.example" if metadata_kind == "issuer" else "https://api.botframework.com",
                "jwks_uri": (
                    "https://attacker.example/keys"
                    if metadata_kind == "jwks-origin"
                    else "https://login.botframework.com/keys"
                ),
            }
        )

    with _run_teams_stub(monkeypatch, tls_material, respond) as stub:
        now = datetime.now(UTC)
        sink = _Sink(EventAcceptance.ACCEPTED)
        adapter = MicrosoftTeamsAdapter(_config())
        result = adapter.webhook_events.handle(
            _activity_request(_activity_body(), private_key=private_key, now=now),
            sink,
        )

        assert result.status_code == 401
        assert sink.events == []
        assert all(request.host != "attacker.example" for request in stub.requests)
        adapter.close()
