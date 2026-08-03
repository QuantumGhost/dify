"""Local TLS integration coverage for the concrete WeCom adapter."""

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
from core.human_input_v2.im_provider import (
    CredentialTestSuccess,
    DirectorySnapshot,
    MessageAccepted,
    OperationFailure,
    OperationFailureCode,
    WeComAdapter,
    WeComAdapterConfig,
    WeComMessageReference,
    WeComUserDestination,
)

_WECOM_HOST = "qyapi.weixin.qq.com"
_CORPORATION_ID = "ww-corp-test"
_AGENT_ID = "1000005"


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
class _WeComStub:
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
        status_code,
        json.dumps(payload, separators=(",", ":")).encode(),
        (("content-type", "application/json"), *headers),
    )


def _token_response() -> _StubResponse:
    return _json_response(
        {
            "errcode": 0,
            "errmsg": "ok",
            "access_token": "access-token",
            "expires_in": 7200,
        }
    )


def _agent_response(
    *,
    user_ids: tuple[str, ...] = ("user-explicit",),
    department_ids: tuple[int, ...] = (),
    tag_ids: tuple[int, ...] = (),
    errcode: int = 0,
    agent_id: int = 1000005,
    closed: int = 0,
) -> _StubResponse:
    return _json_response(
        {
            "errcode": errcode,
            "errmsg": "ok" if errcode == 0 else "rejected",
            "agentid": agent_id,
            "allow_userinfos": {"user": [{"userid": user_id} for user_id in user_ids]},
            "allow_partys": {"partyid": list(department_ids)},
            "allow_tags": {"tagid": list(tag_ids)},
            "close": closed,
        }
    )


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WeCom integration stub")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(_WECOM_HOST)]), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    tls_directory = tmp_path_factory.mktemp("wecom-tls")
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
def _run_wecom_stub(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    responder: _Responder,
) -> Generator[_WeComStub, None, None]:
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
        resolved_host = "127.0.0.1" if normalized_host == _WECOM_HOST else normalized_host
        resolved_port = server.server_port if normalized_host == _WECOM_HOST else port
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
        yield _WeComStub(requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _config(*, agent_id: str = _AGENT_ID) -> WeComAdapterConfig:
    return WeComAdapterConfig(
        corp_id=_CORPORATION_ID,
        agent_id=agent_id,
        corp_secret="integration-secret",
    )


def test_wecom_public_adapter_reuses_one_verified_tls_context_for_all_api_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path == "/cgi-bin/gettoken":
            assert request.query == {"corpid": _CORPORATION_ID, "corpsecret": "integration-secret"}
            return _token_response()
        if request.path == "/cgi-bin/agent/get":
            return _agent_response(department_ids=(2,), tag_ids=(7,))
        if request.path == "/cgi-bin/user/get":
            return _json_response(
                {
                    "errcode": 0,
                    "errmsg": "ok",
                    "userid": "user-explicit",
                    "name": "Explicit User",
                    "biz_mail": "explicit@example.com",
                    "status": 1,
                }
            )
        if request.path == "/cgi-bin/department/list":
            department_id = int(request.query["id"])
            return _json_response(
                {
                    "errcode": 0,
                    "errmsg": "ok",
                    "department": [{"id": department_id, "name": "Visible", "parentid": 1, "order": 1}],
                }
            )
        if request.path == "/cgi-bin/user/list":
            department_id = request.query["department_id"]
            return _json_response(
                {
                    "errcode": 0,
                    "errmsg": "ok",
                    "userlist": [
                        {
                            "userid": f"user-department-{department_id}",
                            "name": f"Department {department_id}",
                            "department": [int(department_id)],
                            "email": f"department-{department_id}@example.com",
                            "status": 1,
                        }
                    ],
                }
            )
        if request.path == "/cgi-bin/tag/get":
            return _json_response(
                {
                    "errcode": 0,
                    "errmsg": "ok",
                    "tagname": "Reviewers",
                    "userlist": [{"userid": "user-tag", "name": "Tag User"}],
                    "partylist": [3],
                }
            )
        if request.path == "/cgi-bin/message/send":
            request_body = TypeAdapter(dict[str, JsonValue]).validate_json(request.body)
            assert request_body == {
                "agentid": 1000005,
                "msgtype": "text",
                "text": {"content": "Hello from Dify"},
                "touser": "user-explicit",
            }
            return _json_response(
                {
                    "errcode": 0,
                    "errmsg": "ok",
                    "invaliduser": "",
                    "invalidparty": "",
                    "invalidtag": "",
                    "msgid": "message-1",
                }
            )
        return _json_response({"errcode": 404, "errmsg": "unexpected"}, status_code=404)

    with _run_wecom_stub(monkeypatch, tls_material, respond) as stub:
        adapter = WeComAdapter(_config())
        credential_result = adapter.test_credentials()
        directory_result = adapter.directory.read_snapshot()
        destination = WeComUserDestination("user-explicit")
        destination_result = adapter.messaging.test_destination(destination)
        message_result = adapter.messaging.send_text(destination, "Hello from Dify")

        assert isinstance(credential_result, CredentialTestSuccess)
        assert credential_result.provider_tenant_id == _CORPORATION_ID
        assert isinstance(directory_result, DirectorySnapshot)
        assert [entry.provider_user_id for entry in directory_result.entries] == [
            "user-explicit",
            "user-department-2",
            "user-tag",
            "user-department-3",
        ]
        assert destination_result is None
        assert message_result == MessageAccepted(WeComMessageReference("message-1"), None)
        assert adapter.webhook_events is None
        assert adapter.stream_events is None
        assert all(request.host == _WECOM_HOST for request in stub.requests)
        assert sum(request.path == "/cgi-bin/gettoken" for request in stub.requests) == 1

        adapter.close()
        adapter.close()
        request_count = len(stub.requests)
        closed_result = adapter.messaging.send_text(destination, "after close")
        assert isinstance(closed_result, OperationFailure)
        assert closed_result.code is OperationFailureCode.CLOSED
        assert len(stub.requests) == request_count


def test_wecom_destination_acquires_cold_token_and_checks_each_exact_user_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path == "/cgi-bin/gettoken":
            return _token_response()
        if request.path == "/cgi-bin/user/get":
            requested_user_id = request.query["userid"]
            return _json_response(
                {
                    "errcode": 0,
                    "errmsg": "ok",
                    "userid": requested_user_id if requested_user_id == "user-explicit" else "different-user",
                    "name": "Exact User",
                    "status": 1,
                }
            )
        raise AssertionError(request.path)

    with _run_wecom_stub(monkeypatch, tls_material, respond) as stub:
        adapter = WeComAdapter(_config())

        visible = adapter.messaging.test_destination(WeComUserDestination("user-explicit"))
        invisible = adapter.messaging.test_destination(WeComUserDestination("user-outside-scope"))

        assert visible is None
        assert isinstance(invisible, OperationFailure)
        assert invisible.code is OperationFailureCode.DESTINATION_UNREACHABLE
        paths = [request.path for request in stub.requests]
        assert paths == ["/cgi-bin/gettoken", "/cgi-bin/user/get", "/cgi-bin/user/get"]
        assert [request.query["userid"] for request in stub.requests if request.path == "/cgi-bin/user/get"] == [
            "user-explicit",
            "user-outside-scope",
        ]
        adapter.close()


@pytest.mark.parametrize(
    "response",
    [
        _StubResponse(200, b"not-json"),
        _json_response({"errcode": 0, "errmsg": "ok"}),
    ],
    ids=("malformed_response", "missing_user"),
)
def test_wecom_destination_rejects_invalid_user_response_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    response: _StubResponse,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path == "/cgi-bin/gettoken":
            return _token_response()
        return response

    with _run_wecom_stub(monkeypatch, tls_material, respond) as stub:
        adapter = WeComAdapter(_config())

        result = adapter.messaging.test_destination(WeComUserDestination("user-explicit"))

        assert isinstance(result, OperationFailure)
        assert result.code is OperationFailureCode.PROVIDER
        assert [request.path for request in stub.requests] == ["/cgi-bin/gettoken", "/cgi-bin/user/get"]
        adapter.close()


@pytest.mark.parametrize(
    ("stage", "response", "expected_code"),
    [
        ("token", _StubResponse(200, b"", disconnect=True), OperationFailureCode.PROVIDER),
        ("token", _StubResponse(429, b"{}"), OperationFailureCode.RATE_LIMITED),
        ("token", _StubResponse(200, b"not-json"), OperationFailureCode.PROVIDER),
        (
            "token",
            _json_response({"errcode": 40013, "errmsg": "invalid corp"}),
            OperationFailureCode.AUTHENTICATION,
        ),
        ("agent", _StubResponse(200, b"", disconnect=True), OperationFailureCode.PROVIDER),
        ("agent", _StubResponse(429, b"{}"), OperationFailureCode.RATE_LIMITED),
        ("agent", _StubResponse(200, b"not-json"), OperationFailureCode.PROVIDER),
        ("agent", _agent_response(errcode=40014), OperationFailureCode.AUTHENTICATION),
        ("agent", _agent_response(errcode=60011), OperationFailureCode.MISSING_PERMISSION),
        ("agent", _agent_response(errcode=50001), OperationFailureCode.PROVIDER),
        ("agent", _agent_response(agent_id=999), OperationFailureCode.AUTHENTICATION),
        ("agent", _agent_response(closed=1), OperationFailureCode.MISSING_PERMISSION),
    ],
    ids=(
        "token-disconnect",
        "token-rate-limit",
        "token-malformed",
        "token-rejection",
        "agent-disconnect",
        "agent-rate-limit",
        "agent-malformed",
        "agent-authentication",
        "agent-permission",
        "agent-rejection",
        "agent-mismatch",
        "agent-disabled",
    ),
)
def test_wecom_credential_failures_are_typed_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    stage: str,
    response: _StubResponse,
    expected_code: OperationFailureCode,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path == "/cgi-bin/gettoken":
            return response if stage == "token" else _token_response()
        return response

    with _run_wecom_stub(monkeypatch, tls_material, respond) as stub:
        adapter = WeComAdapter(_config())
        result = adapter.test_credentials()

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert "integration-secret" not in repr(result)
        assert len(stub.requests) == (1 if stage == "token" else 2)
        adapter.close()


@pytest.mark.parametrize("failure_path", ["/cgi-bin/user/get", "/cgi-bin/department/list", "/cgi-bin/tag/get"])
def test_wecom_directory_never_returns_partial_snapshot_after_real_tls_failure(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    failure_path: str,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path == "/cgi-bin/gettoken":
            return _token_response()
        if request.path == "/cgi-bin/agent/get":
            return _agent_response(department_ids=(2,), tag_ids=(7,))
        if request.path == failure_path:
            return _StubResponse(200, b"not-json")
        if request.path == "/cgi-bin/user/get":
            return _json_response(
                {"errcode": 0, "errmsg": "ok", "userid": "user-explicit", "name": "Explicit", "status": 1}
            )
        if request.path == "/cgi-bin/department/list":
            return _json_response({"errcode": 0, "errmsg": "ok", "department": [{"id": 2}]})
        if request.path == "/cgi-bin/user/list":
            return _json_response({"errcode": 0, "errmsg": "ok", "userlist": []})
        if request.path == "/cgi-bin/tag/get":
            return _json_response({"errcode": 0, "errmsg": "ok", "userlist": [], "partylist": []})
        raise AssertionError(request.path)

    with _run_wecom_stub(monkeypatch, tls_material, respond):
        adapter = WeComAdapter(_config())
        result = adapter.directory.read_snapshot()

        assert isinstance(result, OperationFailure)
        assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
        adapter.close()


def test_wecom_directory_exhausts_real_tls_rate_limit_retries_without_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    department_calls = 0

    def respond(request: _RecordedRequest) -> _StubResponse:
        nonlocal department_calls
        if request.path == "/cgi-bin/gettoken":
            return _token_response()
        if request.path == "/cgi-bin/agent/get":
            return _agent_response(user_ids=(), department_ids=(2,))
        if request.path == "/cgi-bin/department/list":
            department_calls += 1
            return _StubResponse(429, b"{}", (("retry-after", "0"),))
        raise AssertionError(request.path)

    with _run_wecom_stub(monkeypatch, tls_material, respond):
        adapter = WeComAdapter(_config())
        result = adapter.directory.read_snapshot()

        assert isinstance(result, OperationFailure)
        assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
        assert department_calls == 4
        adapter.close()


def test_wecom_directory_maps_real_transport_disconnect_without_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path == "/cgi-bin/gettoken":
            return _token_response()
        if request.path == "/cgi-bin/agent/get":
            return _agent_response()
        return _StubResponse(200, b"", disconnect=True)

    with _run_wecom_stub(monkeypatch, tls_material, respond):
        adapter = WeComAdapter(_config())
        result = adapter.directory.read_snapshot()

        assert isinstance(result, OperationFailure)
        assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
        adapter.close()


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (_StubResponse(200, b"", disconnect=True), OperationFailureCode.AMBIGUOUS),
        (_StubResponse(429, b"{}"), OperationFailureCode.RATE_LIMITED),
        (_StubResponse(200, b"not-json"), OperationFailureCode.AMBIGUOUS),
        (_json_response({"errcode": 50001, "errmsg": "rejected"}), OperationFailureCode.PROVIDER),
        (
            _json_response({"errcode": 0, "errmsg": "ok", "invaliduser": "user-explicit", "msgid": "msg"}),
            OperationFailureCode.AMBIGUOUS,
        ),
        (_json_response({"errcode": 0, "errmsg": "ok"}), OperationFailureCode.AMBIGUOUS),
    ],
    ids=("disconnect", "rate-limit", "malformed", "provider-rejection", "partial", "missing-reference"),
)
def test_wecom_message_failures_make_one_real_side_effecting_call(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    response: _StubResponse,
    expected_code: OperationFailureCode,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path == "/cgi-bin/gettoken":
            return _token_response()
        return response

    with _run_wecom_stub(monkeypatch, tls_material, respond) as stub:
        adapter = WeComAdapter(_config())
        result = adapter.messaging.send_text(WeComUserDestination("user-explicit"), "Hello")

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert sum(request.path == "/cgi-bin/message/send" for request in stub.requests) == 1
        adapter.close()
