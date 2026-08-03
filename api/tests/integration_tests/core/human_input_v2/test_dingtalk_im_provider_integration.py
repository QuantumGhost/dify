"""Local TLS integration coverage for the concrete DingTalk API adapter."""

from __future__ import annotations

import json
import socket
import ssl
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import cast, override
from urllib.parse import parse_qsl, urlsplit

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import JsonValue, TypeAdapter

from core.helper import ssrf_proxy
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    CredentialTestSuccess,
    DingTalkAdapter,
    DingTalkAdapterConfig,
    DingTalkMessageReference,
    DingTalkUserDestination,
    DirectorySnapshot,
    MessageAccepted,
    OperationFailure,
    OperationFailureCode,
)

_TARGET_HOSTS = frozenset({"api.dingtalk.com", "oapi.dingtalk.com"})


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
class _DingTalkStub:
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


def _token_response() -> _StubResponse:
    return _json_response(
        {
            "access_token": "access-token",
            "expires_in": 7200,
        }
    )


def _is_token_request(request: _RecordedRequest) -> bool:
    return request.path == "/v1.0/oauth2/ding-tenant-test/token"


def _legacy_success(payload: JsonValue | None = None) -> _StubResponse:
    response: dict[str, JsonValue] = {"errcode": 0, "errmsg": "ok"}
    if payload is not None:
        response["result"] = payload
    return _json_response(response)


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DingTalk integration stub")])
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
    tls_directory = tmp_path_factory.mktemp("dingtalk-tls")
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
def _run_dingtalk_stub(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    responder: _Responder,
) -> Generator[_DingTalkStub, None, None]:
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

        def do_POST(self) -> None:
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
        yield _DingTalkStub(requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _config(*, corp_id: str = "ding-tenant-test") -> DingTalkAdapterConfig:
    return DingTalkAdapterConfig(
        corp_id=corp_id,
        client_id="client-test",
        client_secret="integration-secret",
    )


def _destination() -> DingTalkUserDestination:
    return DingTalkUserDestination("user-integration")


def test_dingtalk_public_adapter_reuses_one_verified_tls_context_for_all_api_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    department_requests: dict[int, int] = {}

    def respond(request: _RecordedRequest) -> _StubResponse:
        if _is_token_request(request):
            return _token_response()
        if request.path == "/topapi/v2/department/listsub":
            request_body = TypeAdapter(dict[str, int]).validate_json(request.body)
            department_id = request_body["dept_id"]
            department_requests[department_id] = department_requests.get(department_id, 0) + 1
            children: list[JsonValue] = [{"dept_id": 2}] if department_id == 1 else []
            return _legacy_success(children)
        if request.path == "/topapi/v2/user/list":
            request_body = TypeAdapter(dict[str, int]).validate_json(request.body)
            if request_body["size"] == 1:
                return _legacy_success({"list": [], "has_more": False})
            if request_body["dept_id"] == 1 and request_body["cursor"] == 0:
                return _legacy_success(
                    {
                        "list": [
                            {
                                "userid": "user-1",
                                "name": "Ada",
                                "email": "ada@example.com",
                                "active": True,
                            }
                        ],
                        "has_more": True,
                        "next_cursor": 100,
                    }
                )
            if request_body["dept_id"] == 1:
                return _legacy_success(
                    {
                        "list": [
                            {
                                "userid": "user-2",
                                "name": "Lin",
                                "org_email": "lin@example.com",
                                "active": False,
                            }
                        ],
                        "has_more": False,
                    }
                )
            return _legacy_success(
                {
                    "list": [
                        {"userid": "user-1", "name": "Duplicate"},
                        {"userid": "user-3", "name": "Grace"},
                    ],
                    "has_more": False,
                }
            )
        if request.path == "/topapi/v2/user/get":
            return _legacy_success({"userid": "user-integration", "name": "Reviewer"})
        if request.path == "/v1.0/robot/oToMessages/batchSend":
            return _json_response(
                {"processQueryKey": "message-integration"},
                headers=(("x-acs-request-id", "request-integration"),),
            )
        raise AssertionError(f"unexpected request: {request.method} {request.path}")

    with _run_dingtalk_stub(monkeypatch, tls_material, respond) as stub:
        adapter = DingTalkAdapter(_config())
        credential_result = adapter.test_credentials()
        directory_result = adapter.directory.read_snapshot()
        destination_result = adapter.messaging.test_destination(_destination())
        message_result = adapter.messaging.send_text(_destination(), "# Review\nPlease review this request.")

        assert isinstance(credential_result, CredentialTestSuccess)
        assert credential_result.provider is IMProvider.DING_TALK
        assert credential_result.provider_tenant_id == "ding-tenant-test"
        assert isinstance(directory_result, DirectorySnapshot)
        assert [
            (entry.provider_user_id, entry.display_name, entry.email, entry.available)
            for entry in directory_result.entries
        ] == [
            ("user-1", "Ada", "ada@example.com", True),
            ("user-2", "Lin", "lin@example.com", False),
            ("user-3", "Grace", None, None),
        ]
        assert destination_result is None
        assert message_result == MessageAccepted(
            DingTalkMessageReference("user-integration", "message-integration"),
            "request-integration",
        )
        assert sum(_is_token_request(request) for request in stub.requests) == 1
        token_request = stub.requests[0]
        assert token_request.host == "api.dingtalk.com"
        assert token_request.path == "/v1.0/oauth2/ding-tenant-test/token"
        assert TypeAdapter(dict[str, str]).validate_json(token_request.body) == {
            "client_id": "client-test",
            "client_secret": "integration-secret",
            "grant_type": "client_credentials",
        }
        destination_request, message_request = stub.requests[-2:]
        assert destination_request.path == "/topapi/v2/user/get"
        assert destination_request.query == {"access_token": "access-token"}
        assert TypeAdapter(dict[str, str]).validate_json(destination_request.body) == {"userid": "user-integration"}
        assert message_request.path == "/v1.0/robot/oToMessages/batchSend"
        assert message_request.headers["x-acs-dingtalk-access-token"] == "access-token"
        assert TypeAdapter(dict[str, JsonValue]).validate_json(message_request.body) == {
            "robotCode": "client-test",
            "userIds": ["user-integration"],
            "msgKey": "sampleMarkdown",
            "msgParam": '{"title":"Review","text":"# Review\\nPlease review this request."}',
        }
        assert department_requests == {1: 3, 2: 1}

        adapter.close()
        adapter.close()
        request_count = len(stub.requests)
        closed = adapter.messaging.send_text(_destination(), "after close")
        assert isinstance(closed, OperationFailure)
        assert closed.code is OperationFailureCode.CLOSED
        assert len(stub.requests) == request_count


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("token_disconnect", OperationFailureCode.PROVIDER),
        ("token_malformed", OperationFailureCode.PROVIDER),
        ("token_incomplete", OperationFailureCode.PROVIDER),
        ("token_blank", OperationFailureCode.PROVIDER),
        ("token_rate_limited", OperationFailureCode.RATE_LIMITED),
        ("token_provider_unavailable", OperationFailureCode.PROVIDER),
        ("token_rejection_malformed", OperationFailureCode.PROVIDER),
        ("token_rejection_unknown", OperationFailureCode.PROVIDER),
        ("token_rejected", OperationFailureCode.AUTHENTICATION),
        ("department_disconnect", OperationFailureCode.PROVIDER),
        ("department_malformed", OperationFailureCode.PROVIDER),
        ("department_rejected", OperationFailureCode.MISSING_PERMISSION),
        ("user_disconnect", OperationFailureCode.PROVIDER),
        ("user_malformed", OperationFailureCode.PROVIDER),
        ("user_rejected", OperationFailureCode.MISSING_PERMISSION),
    ],
)
def test_dingtalk_credential_failures_are_typed_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    def failure_response(stage: str) -> _StubResponse:
        if failure_kind == f"{stage}_disconnect":
            return _StubResponse(0, b"", disconnect=True)
        if failure_kind == f"{stage}_malformed":
            return _StubResponse(200, b"not-json")
        if failure_kind == f"{stage}_incomplete":
            return _json_response({"access_token": "access-token"})
        if stage == "token":
            if failure_kind == "token_blank":
                return _json_response({"access_token": "", "expires_in": 7200})
            if failure_kind == "token_rate_limited":
                return _json_response({"code": "TooManyRequests", "message": "rate limited"}, status_code=429)
            if failure_kind == "token_provider_unavailable":
                return _json_response({"code": "ServiceUnavailable", "message": "unavailable"}, status_code=503)
            if failure_kind == "token_rejection_malformed":
                return _StubResponse(401, b"not-json")
            if failure_kind == "token_rejection_unknown":
                return _json_response({"code": "UnexpectedError", "message": "rejected"}, status_code=400)
            return _json_response(
                {"code": "InvalidAuthentication", "message": "invalid client secret"},
                status_code=401,
            )
        return _json_response({"errcode": 40014, "errmsg": "rejected"}, status_code=403)

    def respond(request: _RecordedRequest) -> _StubResponse:
        if _is_token_request(request):
            return failure_response("token") if failure_kind.startswith("token_") else _token_response()
        if request.path == "/topapi/v2/department/listsub":
            return failure_response("department") if failure_kind.startswith("department_") else _legacy_success([])
        if request.path == "/topapi/v2/user/list":
            return failure_response("user")
        raise AssertionError(f"unexpected request: {request.method} {request.path}")

    with _run_dingtalk_stub(monkeypatch, tls_material, respond) as stub:
        adapter = DingTalkAdapter(_config())
        result = adapter.test_credentials()

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert "integration-secret" not in repr(result)
        assert 1 <= len(stub.requests) <= 3
        adapter.close()


@pytest.mark.parametrize(
    "failure_kind",
    [
        "department_disconnect",
        "department_malformed",
        "department_rejected",
        "user_disconnect",
        "user_malformed",
        "user_rejected",
        "user_missing_cursor",
    ],
)
def test_dingtalk_directory_never_publishes_partial_snapshot_after_real_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    failure_kind: str,
) -> None:
    permission_calls = 0

    def failure_response(stage: str) -> _StubResponse:
        if failure_kind == f"{stage}_disconnect":
            return _StubResponse(0, b"", disconnect=True)
        if failure_kind == f"{stage}_malformed":
            return _StubResponse(200, b"not-json")
        if failure_kind == f"{stage}_rejected":
            return _json_response({"errcode": 1, "errmsg": "rejected"}, status_code=500)
        return _legacy_success({"list": [], "has_more": True, "next_cursor": 0})

    def respond(request: _RecordedRequest) -> _StubResponse:
        nonlocal permission_calls
        if _is_token_request(request):
            return _token_response()
        if request.path == "/topapi/v2/department/listsub":
            request_body = TypeAdapter(dict[str, int]).validate_json(request.body)
            if permission_calls == 0:
                permission_calls += 1
                return _legacy_success([])
            if failure_kind.startswith("department_"):
                return failure_response("department")
            return _legacy_success([])
        if request.path == "/topapi/v2/user/list":
            request_body = TypeAdapter(dict[str, int]).validate_json(request.body)
            if request_body["size"] == 1:
                return _legacy_success({"list": [], "has_more": False})
            return failure_response("user")
        raise AssertionError(f"unexpected request: {request.method} {request.path}")

    with _run_dingtalk_stub(monkeypatch, tls_material, respond):
        adapter = DingTalkAdapter(_config())
        result = adapter.directory.read_snapshot()

        assert isinstance(result, OperationFailure)
        assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
        adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("disconnect", OperationFailureCode.PROVIDER),
        ("rate_limited", OperationFailureCode.RATE_LIMITED),
        ("server_error", OperationFailureCode.PROVIDER),
        ("malformed", OperationFailureCode.PROVIDER),
        ("incomplete", OperationFailureCode.PROVIDER),
        ("mismatch", OperationFailureCode.DESTINATION_UNREACHABLE),
        ("no_access", OperationFailureCode.MISSING_PERMISSION),
        ("not_found", OperationFailureCode.DESTINATION_UNREACHABLE),
    ],
)
def test_dingtalk_destination_failures_are_typed_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if _is_token_request(request):
            return _token_response()
        if failure_kind == "disconnect":
            return _StubResponse(0, b"", disconnect=True)
        if failure_kind == "malformed":
            return _StubResponse(200, b"not-json")
        if failure_kind == "incomplete":
            return _json_response({})
        if failure_kind == "rate_limited":
            return _json_response({"code": "TooManyRequests"}, status_code=429)
        if failure_kind == "server_error":
            return _json_response({"code": "ServiceUnavailable"}, status_code=503)
        user_id = "other-user" if failure_kind == "mismatch" else "user-integration"
        status_code = 403 if failure_kind == "no_access" else 404 if failure_kind == "not_found" else 200
        return _json_response(
            {"errcode": 0, "errmsg": "ok", "result": {"userid": user_id, "name": "Reviewer"}},
            status_code=status_code,
        )

    with _run_dingtalk_stub(monkeypatch, tls_material, respond) as stub:
        adapter = DingTalkAdapter(_config())
        result = adapter.messaging.test_destination(_destination())

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert len(stub.requests) == 2
        adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("disconnect", OperationFailureCode.AMBIGUOUS),
        ("rate_limited", OperationFailureCode.RATE_LIMITED),
        ("malformed", OperationFailureCode.AMBIGUOUS),
        ("rejected", OperationFailureCode.PROVIDER),
        ("missing_reference", OperationFailureCode.AMBIGUOUS),
    ],
)
def test_dingtalk_message_failures_make_one_real_side_effecting_call(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if _is_token_request(request):
            return _token_response()
        if failure_kind == "disconnect":
            return _StubResponse(0, b"", disconnect=True)
        if failure_kind == "rate_limited":
            return _json_response({}, status_code=429)
        if failure_kind == "malformed":
            return _StubResponse(200, b"not-json")
        if failure_kind == "rejected":
            return _json_response({"processQueryKey": "rejected"}, status_code=400)
        return _json_response({"processQueryKey": " "})

    with _run_dingtalk_stub(monkeypatch, tls_material, respond) as stub:
        adapter = DingTalkAdapter(_config())
        result = adapter.messaging.send_text(_destination(), "Hello")

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        message_requests = [request for request in stub.requests if request.path == "/v1.0/robot/oToMessages/batchSend"]
        assert len(message_requests) == 1
        adapter.close()
