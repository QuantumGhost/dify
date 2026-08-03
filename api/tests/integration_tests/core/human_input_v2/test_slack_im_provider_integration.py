"""Local transport integration coverage for the concrete Slack adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import ssl
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from typing import cast, override
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import JsonValue, TypeAdapter

from core.helper import ssrf_proxy
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AuthenticatedIMEvent,
    CardAction,
    CardActionKind,
    CardAssessment,
    CardIntent,
    CredentialTestSuccess,
    DirectorySnapshot,
    EventAcceptance,
    IMEventSink,
    ImmutableJSONArray,
    ImmutableJSONBoolean,
    ImmutableJSONFloat,
    ImmutableJSONInteger,
    ImmutableJSONObject,
    MessageAccepted,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
    SlackAdapter,
    SlackAdapterConfig,
    SlackMessageReference,
    SlackUserDestination,
    WebhookRequest,
    freeze_json_value,
    thaw_json_value,
)

_SIGNING_SECRET = "integration-signing-secret"
_BASELINE_SCOPES = "chat:write,users:read"
_SLACK_HOST = "slack.com"


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


@dataclass(frozen=True, slots=True)
class _SlackStub:
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


def _auth_success() -> _StubResponse:
    return _json_response(
        {"ok": True, "team_id": "T123"},
        headers=(("x-oauth-scopes", _BASELINE_SCOPES),),
    )


@contextmanager
def _run_slack_stub(
    monkeypatch: pytest.MonkeyPatch,
    responder: _Responder,
) -> Generator[_SlackStub, None, None]:
    requests: list[_RecordedRequest] = []

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self) -> None:
            content_length = int(self.headers.get("content-length", "0"))
            parsed_url = urlsplit(self.path)
            recorded_request = _RecordedRequest(
                method=self.command,
                host=self.headers.get("host", "").partition(":")[0].casefold(),
                path=parsed_url.path,
                query=dict(parse_qsl(parsed_url.query, keep_blank_values=True)),
                headers={name.casefold(): value for name, value in self.headers.items()},
                body=self.rfile.read(content_length),
            )
            requests.append(recorded_request)
            response = responder(recorded_request)
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

        @override
        def log_message(self, format: str, *args: object) -> None:
            return

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Slack integration stub")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(_SLACK_HOST)]), critical=False)
        .sign(private_key, hashes.SHA256())
    )

    with TemporaryDirectory(prefix="dify-slack-tls-") as tls_directory_name:
        tls_directory = Path(tls_directory_name)
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

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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
            resolved_host = "127.0.0.1" if normalized_host == _SLACK_HOST else normalized_host
            resolved_port = server.server_port if normalized_host == _SLACK_HOST else port
            return cast(
                list[_AddressInfo],
                real_getaddrinfo(resolved_host, resolved_port, family, type, proto, flags),
            )

        with monkeypatch.context() as tls_monkeypatch:
            tls_monkeypatch.setattr(socket, "getaddrinfo", resolve)
            tls_monkeypatch.setenv("SSL_CERT_FILE", str(certificate_path))
            tls_monkeypatch.setenv("NO_PROXY", "*")
            tls_monkeypatch.setenv("no_proxy", "*")
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield _SlackStub(requests=requests)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


def _adapter(monkeypatch: pytest.MonkeyPatch) -> SlackAdapter:
    monkeypatch.setattr(ssrf_proxy.dify_config, "SSRF_PROXY_ALL_URL", None)
    monkeypatch.setattr(ssrf_proxy.dify_config, "SSRF_PROXY_HTTP_URL", None)
    monkeypatch.setattr(ssrf_proxy.dify_config, "SSRF_PROXY_HTTPS_URL", None)
    return SlackAdapter(
        SlackAdapterConfig(
            bot_token="xoxb-integration-token",
            signing_secret=_SIGNING_SECRET,
            app_token="xapp-integration-token",
        )
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


def _oversized_card_intent() -> CardIntent:
    return CardIntent(
        title=None,
        body="Review this request.",
        facts=(),
        actions=tuple(CardAction(f"action-{index}", "Review", CardActionKind.SUBMIT, "review") for index in range(26)),
        fallback_text="Review this request.",
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


def _signed_request(
    body: bytes,
    *,
    timestamp: int,
    received_at: datetime | None = None,
    signature_body: bytes | None = None,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> WebhookRequest:
    signature_base = f"v0:{timestamp}:".encode() + (signature_body if signature_body is not None else body)
    signature = "v0=" + hmac.new(_SIGNING_SECRET.encode(), signature_base, hashlib.sha256).hexdigest()
    return WebhookRequest(
        method="POST",
        headers=(
            ("x-slack-request-timestamp", str(timestamp)),
            ("x-slack-signature", signature),
            *extra_headers,
        ),
        query=(),
        body=body,
        received_at=received_at or datetime.fromtimestamp(timestamp, tz=UTC),
    )


def test_slack_public_adapter_uses_one_real_http_context_for_all_api_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"second_page_attempts": 0, "post_messages": 0}

    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path == "/api/auth.test":
            return _auth_success()
        if request.path == "/api/users.list" and "cursor" not in request.query:
            return _json_response(
                {
                    "ok": True,
                    "members": [
                        {
                            "id": "U1",
                            "profile": {"display_name": "Ada", "email": "ada@example.com"},
                        }
                    ],
                    "response_metadata": {"next_cursor": "page-2"},
                }
            )
        if request.path == "/api/users.list":
            state["second_page_attempts"] += 1
            if state["second_page_attempts"] == 1:
                return _json_response(
                    {"ok": False, "error": "ratelimited"},
                    status_code=429,
                    headers=(("retry-after", "0"),),
                )
            return _json_response(
                {
                    "ok": True,
                    "members": [
                        {"id": "U2", "deleted": True, "name": "Grace", "profile": {}},
                    ],
                    "response_metadata": {"next_cursor": ""},
                }
            )
        if request.path == "/api/users.info":
            return _json_response({"ok": True, "user": {"id": "U1", "profile": {"real_name": "Ada"}}})
        if request.path == "/api/chat.postMessage":
            state["post_messages"] += 1
            return _json_response(
                {"ok": True, "channel": "D1", "ts": f"1000.{state['post_messages']}"},
                headers=(("x-slack-req-id", f"request-{state['post_messages']}"),),
            )
        if request.path == "/api/chat.update":
            body = TypeAdapter(dict[str, JsonValue]).validate_json(request.body)
            return _json_response(
                {"ok": True, "channel": body["channel"], "ts": body["ts"]},
                headers=(("x-slack-req-id", "request-update"),),
            )
        return _json_response({"ok": False, "error": "unexpected_path"}, status_code=404)

    with _run_slack_stub(monkeypatch, respond) as stub:
        adapter = _adapter(monkeypatch)
        credential_result = adapter.test_credentials()
        directory_result = adapter.directory.read_snapshot()
        destination = SlackUserDestination("U1")
        destination_result = adapter.messaging.test_destination(destination)
        text_result = adapter.messaging.send_text(destination, "Hello **team**")
        card_messaging = adapter.dynamic_card_messaging
        assert card_messaging is not None
        assessment = card_messaging.assess(_card_intent())
        card_result = card_messaging.send_card(
            destination,
            _card_intent(),
            OpaqueMetadata(entries=(("form_id", "form-1"),)),
        )
        assert isinstance(card_result, MessageAccepted)
        update_result = card_messaging.update_card(
            card_result.reference,
            _card_intent(),
            OpaqueMetadata(entries=()),
        )

        assert isinstance(credential_result, CredentialTestSuccess)
        assert credential_result.provider_tenant_id == "T123"
        assert tuple(permission.name for permission in credential_result.permissions) == (
            "chat:write",
            "users:read",
        )
        assert isinstance(directory_result, DirectorySnapshot)
        directory_facts = [
            (entry.provider_user_id, entry.display_name, entry.email, entry.available)
            for entry in directory_result.entries
        ]
        assert directory_facts == [
            ("U1", "Ada", "ada@example.com", True),
            ("U2", "Grace", None, False),
        ]
        assert destination_result is None
        assert text_result == MessageAccepted(
            SlackMessageReference("D1", "1000.1"),
            provider_request_id="request-1",
        )
        assert isinstance(assessment, CardAssessment)
        assert assessment.representable
        assert update_result == MessageAccepted(
            card_result.reference,
            provider_request_id="request-update",
        )
        assert state == {"second_page_attempts": 2, "post_messages": 2}
        assert all(request.host == _SLACK_HOST for request in stub.requests)
        assert all(request.headers["authorization"] == "Bearer xoxb-integration-token" for request in stub.requests)
        assert len({request.headers["connection"] for request in stub.requests}) == 1

        adapter.close()
        adapter.close()
        request_count = len(stub.requests)
        closed_result = adapter.messaging.send_text(SlackUserDestination("U1"), "after close")
        assert isinstance(closed_result, OperationFailure)
        assert closed_result.code is OperationFailureCode.CLOSED
        assert len(stub.requests) == request_count


@pytest.mark.parametrize("failure_kind", ["late_rejection", "rate_limit_exhaustion"])
def test_slack_directory_never_returns_partial_snapshot_after_late_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    page_two_calls = 0

    def respond(request: _RecordedRequest) -> _StubResponse:
        nonlocal page_two_calls
        if request.path == "/api/auth.test":
            return _auth_success()
        if "cursor" not in request.query:
            return _json_response(
                {
                    "ok": True,
                    "members": [{"id": "U1", "profile": {"display_name": "Ada"}}],
                    "response_metadata": {"next_cursor": "page-2"},
                }
            )
        page_two_calls += 1
        if failure_kind == "late_rejection":
            return _json_response({"ok": False, "error": "internal_error"}, status_code=500)
        return _json_response(
            {"ok": False, "error": "ratelimited"},
            status_code=429,
            headers=(("retry-after", "0"),),
        )

    with _run_slack_stub(monkeypatch, respond) as stub:
        adapter = _adapter(monkeypatch)
        result = adapter.directory.read_snapshot()

        assert isinstance(result, OperationFailure)
        assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
        assert page_two_calls == (1 if failure_kind == "late_rejection" else 4)
        adapter.close()


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (_json_response({"ok": False, "error": "invalid_auth"}), OperationFailureCode.AUTHENTICATION),
        (_json_response({"ok": True}), OperationFailureCode.TENANT_IDENTIFICATION),
        (
            _json_response({"ok": True, "team_id": "T123"}, headers=(("x-oauth-scopes", "chat:write"),)),
            OperationFailureCode.MISSING_PERMISSION,
        ),
        (_StubResponse(200, b"not-json"), OperationFailureCode.PROVIDER),
    ],
    ids=("invalid_auth", "missing_tenant", "missing_scopes", "malformed_response"),
)
def test_slack_credential_failures_are_typed_and_do_not_expose_bound_secrets(
    monkeypatch: pytest.MonkeyPatch,
    response: _StubResponse,
    expected_code: OperationFailureCode,
) -> None:
    with _run_slack_stub(monkeypatch, lambda request: response) as stub:
        adapter = _adapter(monkeypatch)
        result = adapter.test_credentials()

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert "integration-token" not in repr(result)
        assert len(stub.requests) == 1
        adapter.close()


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (_StubResponse(200, b"not-json"), OperationFailureCode.AMBIGUOUS),
        (_json_response({"ok": False, "error": "ratelimited"}, status_code=429), OperationFailureCode.RATE_LIMITED),
        (_json_response({"ok": False, "error": "restricted_action"}), OperationFailureCode.PROVIDER),
        (_json_response({"ok": True}), OperationFailureCode.AMBIGUOUS),
    ],
    ids=("malformed_response", "rate_limited", "provider_rejection", "missing_reference"),
)
def test_slack_send_failure_is_never_replayed_by_the_real_http_client(
    monkeypatch: pytest.MonkeyPatch,
    response: _StubResponse,
    expected_code: OperationFailureCode,
) -> None:
    with _run_slack_stub(monkeypatch, lambda request: response) as stub:
        adapter = _adapter(monkeypatch)
        result = adapter.messaging.send_text(SlackUserDestination("U1"), "Hello")

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert len(stub.requests) == 1
        adapter.close()


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (_json_response({"ok": False, "error": "message_not_found"}), OperationFailureCode.STALE_REFERENCE),
        (
            _json_response({"ok": True, "channel": "C2", "ts": "2000.1"}),
            OperationFailureCode.AMBIGUOUS,
        ),
    ],
    ids=("stale_reference", "changed_reference"),
)
def test_slack_card_update_preserves_the_exact_reference(
    monkeypatch: pytest.MonkeyPatch,
    response: _StubResponse,
    expected_code: OperationFailureCode,
) -> None:
    with _run_slack_stub(monkeypatch, lambda request: response) as stub:
        adapter = _adapter(monkeypatch)
        card_messaging = adapter.dynamic_card_messaging
        assert card_messaging is not None
        result = card_messaging.update_card(
            SlackMessageReference("C1", "1000.1"),
            _card_intent(),
            OpaqueMetadata(entries=()),
        )

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert len(stub.requests) == 1
        adapter.close()


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (_StubResponse(200, b"not-json"), OperationFailureCode.PROVIDER),
        (
            _json_response({"ok": False, "error": "missing_scope", "needed": "users:read"}),
            OperationFailureCode.MISSING_PERMISSION,
        ),
        (
            _json_response({"ok": False, "error": "user_not_found"}),
            OperationFailureCode.DESTINATION_UNREACHABLE,
        ),
    ],
    ids=("malformed_response", "missing_scope", "provider_rejection"),
)
def test_slack_destination_failure_is_translated_at_the_real_http_boundary(
    monkeypatch: pytest.MonkeyPatch,
    response: _StubResponse,
    expected_code: OperationFailureCode,
) -> None:
    with _run_slack_stub(monkeypatch, lambda request: response) as stub:
        adapter = _adapter(monkeypatch)
        result = adapter.messaging.test_destination(SlackUserDestination("U1"))

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert len(stub.requests) == 1
        adapter.close()


def test_slack_unrepresentable_card_is_rejected_without_an_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _run_slack_stub(monkeypatch, lambda request: _json_response({"ok": False})) as stub:
        adapter = _adapter(monkeypatch)
        card_messaging = adapter.dynamic_card_messaging
        assert card_messaging is not None
        intent = _oversized_card_intent()
        empty_metadata = OpaqueMetadata(entries=())

        assessment = card_messaging.assess(intent)
        send_result = card_messaging.send_card(SlackUserDestination("U1"), intent, empty_metadata)
        update_result = card_messaging.update_card(
            SlackMessageReference("C1", "1000.1"),
            intent,
            empty_metadata,
        )

        assert isinstance(assessment, CardAssessment)
        assert not assessment.representable
        assert isinstance(send_result, OperationFailure)
        assert isinstance(update_result, OperationFailure)
        assert send_result.code is OperationFailureCode.RENDERING
        assert update_result.code is OperationFailureCode.RENDERING
        assert stub.requests == []
        adapter.close()


def test_slack_block_action_authentication_and_sink_ack_mapping_use_the_concrete_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _run_slack_stub(monkeypatch, lambda request: _json_response({"ok": True})) as stub:
        adapter = _adapter(monkeypatch)
        timestamp = 1_787_000_000

        def event_body(action_value: str) -> bytes:
            return urlencode(
                {
                    "payload": json.dumps(
                        {
                            "type": "block_actions",
                            "team": {"id": "T123"},
                            "actions": [{"action_id": "approve", "value": action_value}],
                            "confirmed": True,
                            "attempt": 1,
                            "confidence": 1.0,
                            "optional": None,
                        }
                    )
                }
            ).encode()

        accepted_body = event_body("accepted")
        retry_body = event_body("retry")
        failing_body = event_body("failure")

        def signed_request(body: bytes, **kwargs: object) -> WebhookRequest:
            return _signed_request(
                body,
                timestamp=timestamp,
                extra_headers=(("content-type", "application/x-www-form-urlencoded; charset=utf-8"),),
                **kwargs,
            )

        accepted_sink = _Sink(EventAcceptance.ACCEPTED)
        accepted = adapter.webhook_events.handle(signed_request(accepted_body), accepted_sink)
        retry_sink = _Sink(EventAcceptance.RETRY)
        retry = adapter.webhook_events.handle(signed_request(retry_body), retry_sink)
        failing_sink = _Sink(EventAcceptance.ACCEPTED, error=RuntimeError("storage unavailable"))
        failed = adapter.webhook_events.handle(signed_request(failing_body), failing_sink)
        replay_sink = _Sink(EventAcceptance.ACCEPTED)
        replay = adapter.webhook_events.handle(
            signed_request(
                accepted_body,
            ),
            replay_sink,
        )
        tampered = adapter.webhook_events.handle(
            signed_request(event_body("tampered"), signature_body=b"different"),
            _Sink(EventAcceptance.ACCEPTED),
        )
        stale = adapter.webhook_events.handle(
            signed_request(
                event_body("stale"),
                received_at=datetime.fromtimestamp(timestamp + 301, tz=UTC),
            ),
            _Sink(EventAcceptance.ACCEPTED),
        )

        assert accepted.status_code == 200
        assert retry.status_code == 503
        assert failed.status_code == 503
        assert replay.status_code == 200
        assert replay_sink.events == []
        assert tampered.status_code == 401
        assert stale.status_code == 401
        assert len(accepted_sink.events) == len(retry_sink.events) == len(failing_sink.events) == 1
        accepted_event = accepted_sink.events[0]
        assert accepted_event.provider is IMProvider.SLACK
        assert accepted_event.provider_event_id is None
        native_payload = thaw_json_value(accepted_event.provider_payload)
        assert native_payload == {
            "type": "block_actions",
            "team": {"id": "T123"},
            "actions": [{"action_id": "approve", "value": "accepted"}],
            "confirmed": True,
            "attempt": 1,
            "confidence": 1.0,
            "optional": None,
        }
        legacy_event = AuthenticatedIMEvent(
            provider=accepted_event.provider,
            provider_tenant_id=accepted_event.provider_tenant_id,
            provider_event_id=accepted_event.provider_event_id,
            provider_event_time=accepted_event.provider_event_time,
            received_at=accepted_event.received_at,
            provider_event_type=accepted_event.provider_event_type,
            provider_payload=cast(ImmutableJSONObject, tuple(accepted_event.provider_payload)),
        )
        assert thaw_json_value(legacy_event.provider_payload) == native_payload
        refrozen_payload = freeze_json_value(native_payload)
        assert isinstance(refrozen_payload, ImmutableJSONObject)
        assert accepted_event.provider_payload == refrozen_payload
        assert accepted_event.provider_payload != ImmutableJSONObject(())
        assert hash(accepted_event.provider_payload) == hash(refrozen_payload)
        actions = dict(accepted_event.provider_payload)["actions"]
        refrozen_actions = freeze_json_value([{"action_id": "approve", "value": "accepted"}])
        assert isinstance(actions, ImmutableJSONArray)
        assert isinstance(refrozen_actions, ImmutableJSONArray)
        assert actions == refrozen_actions
        assert actions != ImmutableJSONArray(())
        assert hash(actions) == hash(refrozen_actions)
        payload_members = dict(accepted_event.provider_payload)
        confirmed = payload_members["confirmed"]
        attempt = payload_members["attempt"]
        confidence = payload_members["confidence"]
        assert isinstance(confirmed, ImmutableJSONBoolean)
        assert isinstance(attempt, ImmutableJSONInteger)
        assert isinstance(confidence, ImmutableJSONFloat)
        assert bool(confirmed)
        assert confirmed != attempt
        assert len({confirmed, attempt}) == 2
        assert attempt != confidence
        assert confidence != attempt
        assert len({attempt, confidence}) == 2
        assert accepted_event.provider_payload != actions
        assert actions != accepted_event.provider_payload
        assert stub.requests == []
        adapter.close()


def test_slack_interactive_card_click_is_authenticated_and_replay_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _run_slack_stub(monkeypatch, lambda request: _json_response({"ok": True})) as stub:
        adapter = _adapter(monkeypatch)
        timestamp = 1_787_000_000
        interactive_payload = {
            "type": "block_actions",
            "team": {"id": "T123"},
            "actions": [{"action_id": "approve", "value": "approved"}],
        }
        body = urlencode({"payload": json.dumps(interactive_payload)}).encode()
        request = _signed_request(
            body,
            timestamp=timestamp,
            extra_headers=(("content-type", "application/x-www-form-urlencoded; charset=utf-8"),),
        )
        sink = _Sink(EventAcceptance.ACCEPTED)

        accepted = adapter.webhook_events.handle(request, sink)
        replay_sink = _Sink(EventAcceptance.ACCEPTED)
        replay = adapter.webhook_events.handle(
            _signed_request(
                body,
                timestamp=timestamp,
                extra_headers=(
                    ("content-type", "application/x-www-form-urlencoded; charset=utf-8"),
                    ("x-slack-retry-num", "999"),
                    ("x-slack-retry-reason", "forged"),
                ),
            ),
            replay_sink,
        )

        assert accepted.status_code == 200
        assert len(sink.events) == 1
        assert sink.events[0].provider_event_type == "block_actions"
        assert sink.events[0].provider_tenant_id == "T123"
        assert sink.events[0].provider_event_id is None
        assert replay.status_code == 200
        assert replay_sink.events == []
        assert stub.requests == []
        adapter.close()


def test_slack_rejects_out_of_scope_signed_slash_command_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _run_slack_stub(monkeypatch, lambda request: _json_response({"ok": True})) as stub:
        adapter = _adapter(monkeypatch)
        timestamp = 1_787_000_000
        body = urlencode(
            {
                "team_id": "T123",
                "team_domain": "test-workspace",
                "channel_id": "C123",
                "user_id": "U123",
                "command": "/approve",
                "text": "request-1",
            }
        ).encode()
        request = _signed_request(
            body,
            timestamp=timestamp,
            extra_headers=(("content-type", "application/x-www-form-urlencoded; charset=utf-8"),),
        )
        sink = _Sink(EventAcceptance.ACCEPTED)

        rejected = adapter.webhook_events.handle(request, sink)

        assert rejected.status_code == 400
        assert sink.events == []
        assert stub.requests == []
        adapter.close()


@pytest.mark.parametrize(
    "request_kind",
    [
        "non_post",
        "missing_headers",
        "invalid_timestamp",
        "malformed_json",
        "unsupported_payload",
        "duplicate_interactive_payload",
        "blank_slash_team",
        "missing_slash_command",
        "blank_slash_command",
    ],
)
def test_slack_webhook_rejects_invalid_request_shapes_before_the_sink(
    monkeypatch: pytest.MonkeyPatch,
    request_kind: str,
) -> None:
    with _run_slack_stub(monkeypatch, lambda request: _json_response({"ok": True})) as stub:
        adapter = _adapter(monkeypatch)
        timestamp = 1_787_000_000
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
        elif request_kind == "duplicate_interactive_payload":
            interactive_payload = json.dumps(
                {
                    "type": "block_actions",
                    "team": {"id": "T123"},
                    "actions": [{"action_id": "approve", "value": "approved"}],
                }
            )
            body = urlencode((("payload", interactive_payload), ("payload", interactive_payload))).encode()
            request = _signed_request(
                body,
                timestamp=timestamp,
                extra_headers=(("content-type", "application/x-www-form-urlencoded; charset=utf-8"),),
            )
            expected_status = 400
        elif request_kind == "blank_slash_team":
            body = urlencode({"team_id": " ", "command": "/approve", "text": "request-1"}).encode()
            request = _signed_request(
                body,
                timestamp=timestamp,
                extra_headers=(("content-type", "application/x-www-form-urlencoded; charset=utf-8"),),
            )
            expected_status = 400
        elif request_kind in {"missing_slash_command", "blank_slash_command"}:
            fields = {"team_id": "T123", "text": "request-1"}
            if request_kind == "blank_slash_command":
                fields["command"] = " "
            body = urlencode(fields).encode()
            request = _signed_request(
                body,
                timestamp=timestamp,
                extra_headers=(("content-type", "application/x-www-form-urlencoded; charset=utf-8"),),
            )
            expected_status = 400
        else:
            body = b"not-json" if request_kind == "malformed_json" else b'{"type":"app_rate_limited"}'
            request = _signed_request(body, timestamp=timestamp)
            expected_status = 400
        sink = _Sink(EventAcceptance.ACCEPTED)

        result = adapter.webhook_events.handle(request, sink)

        assert result.status_code == expected_status
        assert sink.events == []
        assert stub.requests == []
        adapter.close()
