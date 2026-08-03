"""Local TLS integration coverage for the concrete Feishu/Lark adapter."""

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
    CardAction,
    CardActionKind,
    CardAssessment,
    CardIntent,
    CredentialTestSuccess,
    DirectorySnapshot,
    FeishuLarkAdapter,
    FeishuLarkAdapterConfig,
    FeishuMessageReference,
    FeishuUserDestination,
    MessageAccepted,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
)

_TARGET_HOSTS = frozenset({"open.feishu.cn", "open.larksuite.com"})
_VERIFICATION_TOKEN = "integration-verification-token"


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
class _FeishuStub:
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
            "code": 0,
            "msg": "ok",
            "tenant_access_token": "tenant-token",
            "expire": 7200,
        }
    )


def _tenant_response() -> _StubResponse:
    return _json_response(
        {
            "code": 0,
            "msg": "success",
            "data": {"tenant": {"tenant_key": "tenant-key"}},
        }
    )


def _scope_response(
    *,
    department_ids: tuple[str, ...] = ("od-child",),
    user_ids: tuple[str, ...] = ("ou-root",),
) -> _StubResponse:
    return _json_response(
        {
            "code": 0,
            "msg": "success",
            "data": {
                "department_ids": list(department_ids),
                "user_ids": list(user_ids),
                "group_ids": [],
                "has_more": False,
            },
        }
    )


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Feishu integration stub")])
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
    tls_directory = tmp_path_factory.mktemp("feishu-lark-tls")
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
def _run_feishu_stub(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    responder: _Responder,
) -> Generator[_FeishuStub, None, None]:
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

        def do_PATCH(self) -> None:
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
        yield _FeishuStub(requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _config(provider: IMProvider = IMProvider.FEISHU) -> FeishuLarkAdapterConfig:
    return FeishuLarkAdapterConfig(
        provider=provider,
        app_id="cli_integration",
        app_secret="integration-secret",
        verification_token=_VERIFICATION_TOKEN,
        encrypt_key="integration-encrypt-key",
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


@pytest.mark.parametrize(
    ("provider", "expected_host"),
    [
        (IMProvider.FEISHU, "open.feishu.cn"),
        (IMProvider.LARK, "open.larksuite.com"),
    ],
)
def test_feishu_lark_public_adapter_uses_real_tls_for_all_stateless_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    provider: IMProvider,
    expected_host: str,
) -> None:
    message_count = 0

    def respond(request: _RecordedRequest) -> _StubResponse:
        nonlocal message_count
        if request.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.path.endswith("/tenant/v2/tenant/query"):
            return _tenant_response()
        if request.path.endswith("/contact/v3/scopes"):
            return _scope_response()
        if request.path.endswith("/contact/v3/departments/od-child/children"):
            return _json_response(
                {
                    "code": 0,
                    "msg": "success",
                    "data": {"items": [], "has_more": False},
                }
            )
        if request.path.endswith("/contact/v3/users/ou-root"):
            return _json_response(
                {
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "user": {
                            "open_id": "ou-root",
                            "name": "Ada",
                            "email": "ada@example.com",
                            "status": {"is_activated": True},
                        }
                    },
                }
            )
        if request.path.endswith("/contact/v3/users/find_by_department"):
            assert request.query["department_id"] == "od-child"
            return _json_response(
                {
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "items": [
                            {
                                "open_id": "ou-child",
                                "name": "Grace",
                                "enterprise_email": "grace@example.com",
                                "status": {"is_resigned": True},
                            }
                        ],
                        "has_more": False,
                    },
                }
            )
        if request.path.endswith("/contact/v3/users/ou-user"):
            assert request.query == {"user_id_type": "open_id"}
            return _json_response({"code": 0, "msg": "success", "data": {}})
        if request.path.endswith("/im/v1/messages"):
            message_count += 1
            return _json_response(
                {"code": 0, "msg": "success", "data": {"message_id": f"om-{message_count}"}},
                headers=(("x-tt-logid", f"request-{message_count}"),),
            )
        if request.path.endswith("/im/v1/messages/om-2"):
            return _json_response({"code": 0, "msg": "success", "data": {}})
        return _json_response({"code": 404, "msg": "unexpected path"}, status_code=404)

    with _run_feishu_stub(monkeypatch, tls_material, respond) as stub:
        adapter = FeishuLarkAdapter(_config(provider))
        credential_result = adapter.test_credentials()
        directory_result = adapter.directory.read_snapshot()
        destination = FeishuUserDestination("ou-user", "open_id")
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
        assert credential_result.provider is provider
        assert credential_result.provider_tenant_id == "tenant-key"
        assert isinstance(directory_result, DirectorySnapshot)
        assert [
            (entry.provider_user_id, entry.display_name, entry.email, entry.available)
            for entry in directory_result.entries
        ] == [
            ("ou-root", "Ada", "ada@example.com", True),
            ("ou-child", "Grace", "grace@example.com", False),
        ]
        assert destination_result is None
        assert text_result == MessageAccepted(FeishuMessageReference("om-1"), "request-1")
        assert assessment == CardAssessment(representable=True, reason=None)
        assert update_result == MessageAccepted(FeishuMessageReference("om-2"), None)
        assert all(request.host == expected_host for request in stub.requests)
        assert sum(request.path.endswith("/auth/v3/tenant_access_token/internal") for request in stub.requests) == 1

        adapter.close()
        adapter.close()
        request_count = len(stub.requests)
        closed_result = adapter.messaging.send_text(destination, "after close")
        assert isinstance(closed_result, OperationFailure)
        assert closed_result.code is OperationFailureCode.CLOSED
        assert len(stub.requests) == request_count


def test_feishu_lark_card_send_acquires_cold_token_before_interactive_message_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return _json_response(
            {"code": 0, "msg": "success", "data": {"message_id": "om-card"}},
            headers=(("x-tt-logid", "request-card"),),
        )

    with _run_feishu_stub(monkeypatch, tls_material, respond) as stub:
        adapter = FeishuLarkAdapter(_config())
        card_messaging = adapter.dynamic_card_messaging
        assert card_messaging is not None

        result = card_messaging.send_card(
            FeishuUserDestination("ou-user", "open_id"),
            _card_intent(),
            OpaqueMetadata(entries=(("form_id", "form-1"),)),
        )

        assert result == MessageAccepted(FeishuMessageReference("om-card"), "request-card")
        assert [request.path for request in stub.requests] == [
            "/open-apis/auth/v3/tenant_access_token/internal",
            "/open-apis/im/v1/messages",
        ]
        message_body = TypeAdapter(dict[str, JsonValue]).validate_json(stub.requests[-1].body)
        assert message_body["msg_type"] == "interactive"
        adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("token_disconnect", OperationFailureCode.PROVIDER),
        ("token_malformed", OperationFailureCode.PROVIDER),
        ("token_rejected", OperationFailureCode.AUTHENTICATION),
        ("tenant_disconnect", OperationFailureCode.TENANT_IDENTIFICATION),
        ("tenant_malformed", OperationFailureCode.TENANT_IDENTIFICATION),
        ("tenant_rejected", OperationFailureCode.TENANT_IDENTIFICATION),
        ("scope_disconnect", OperationFailureCode.DIRECTORY_INCOMPLETE),
        ("scope_malformed", OperationFailureCode.DIRECTORY_INCOMPLETE),
        ("scope_rejected", OperationFailureCode.DIRECTORY_INCOMPLETE),
    ],
)
def test_feishu_lark_credential_failures_are_typed_over_real_tls(
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
        if stage == "token":
            return _json_response({"code": 10003, "msg": "invalid credentials"}, status_code=401)
        return _json_response({"code": 99991663, "msg": "rejected"}, status_code=401)

    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("/auth/v3/tenant_access_token/internal"):
            return failure_response("token") if failure_kind.startswith("token_") else _token_response()
        if request.path.endswith("/tenant/v2/tenant/query"):
            return failure_response("tenant") if failure_kind.startswith("tenant_") else _tenant_response()
        if request.path.endswith("/contact/v3/scopes"):
            return failure_response("scope")
        raise AssertionError(f"unexpected request: {request.method} {request.path}")

    with _run_feishu_stub(monkeypatch, tls_material, respond) as stub:
        adapter = FeishuLarkAdapter(_config())
        result = adapter.test_credentials()

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        assert "integration-secret" not in repr(result)
        assert 1 <= len(stub.requests) <= 3
        adapter.close()


def test_feishu_lark_directory_paginates_and_retries_read_only_requests_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    department_attempts = 0

    def respond(request: _RecordedRequest) -> _StubResponse:
        nonlocal department_attempts
        if request.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.path.endswith("/tenant/v2/tenant/query"):
            return _tenant_response()
        if request.path.endswith("/contact/v3/scopes"):
            return _scope_response(department_ids=("od-root",), user_ids=())
        if request.path.endswith("/contact/v3/departments/od-root/children"):
            department_attempts += 1
            if department_attempts == 1:
                return _json_response(
                    {"code": 99991400, "msg": "rate limited"},
                    status_code=429,
                    headers=(("retry-after", "0"),),
                )
            if "page_token" not in request.query:
                return _json_response(
                    {
                        "code": 0,
                        "msg": "success",
                        "data": {
                            "items": [{"open_department_id": "od-child"}],
                            "has_more": True,
                            "page_token": "department-next",
                        },
                    }
                )
            return _json_response(
                {
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "items": [
                            {"open_department_id": "od-child"},
                            {"open_department_id": "od-second"},
                        ],
                        "has_more": False,
                    },
                }
            )
        if request.path.endswith("/contact/v3/users/find_by_department"):
            department_id = request.query["department_id"]
            if department_id == "od-root" and "page_token" not in request.query:
                return _json_response(
                    {
                        "code": 0,
                        "msg": "success",
                        "data": {
                            "items": [{"open_id": "ou-root", "name": "Ada", "status": {}}],
                            "has_more": True,
                            "page_token": "user-next",
                        },
                    }
                )
            if department_id == "od-root":
                return _json_response(
                    {
                        "code": 0,
                        "msg": "success",
                        "data": {
                            "items": [
                                {
                                    "open_id": "ou-disabled",
                                    "name": "Lin",
                                    "status": {"is_activated": False},
                                }
                            ],
                            "has_more": False,
                        },
                    }
                )
            return _json_response(
                {
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "items": [{"open_id": f"ou-{department_id}", "name": department_id}],
                        "has_more": False,
                    },
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {request.path}")

    with _run_feishu_stub(monkeypatch, tls_material, respond):
        adapter = FeishuLarkAdapter(_config())
        result = adapter.directory.read_snapshot()

        assert isinstance(result, DirectorySnapshot)
        assert department_attempts == 3
        assert [(entry.provider_user_id, entry.available) for entry in result.entries] == [
            ("ou-root", None),
            ("ou-disabled", False),
            ("ou-od-child", None),
            ("ou-od-second", None),
        ]
        adapter.close()


@pytest.mark.parametrize(
    "failure_kind",
    [
        "department_disconnect",
        "department_malformed",
        "department_rejected",
        "department_blank_id",
        "department_missing_cursor",
        "user_disconnect",
        "user_malformed",
        "user_rejected",
        "user_missing_cursor",
        "rate_limit_bad_header",
        "rate_limit_exhausted",
    ],
)
def test_feishu_lark_directory_never_returns_partial_snapshot_after_real_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    failure_kind: str,
) -> None:
    def directory_failure_response(stage: str) -> _StubResponse:
        if failure_kind == f"{stage}_disconnect":
            return _StubResponse(0, b"", disconnect=True)
        if failure_kind == f"{stage}_malformed":
            return _StubResponse(200, b"not-json")
        if failure_kind == f"{stage}_rejected":
            return _json_response({"code": 1, "msg": "rejected"}, status_code=500)
        if failure_kind == "department_blank_id":
            return _json_response(
                {"code": 0, "msg": "success", "data": {"items": [{"open_department_id": " "}]}},
            )
        if failure_kind == f"{stage}_missing_cursor":
            return _json_response({"code": 0, "msg": "success", "data": {"items": [], "has_more": True}})
        if failure_kind == "rate_limit_bad_header":
            return _json_response({"code": 1, "msg": "limited"}, status_code=429)
        return _json_response(
            {"code": 1, "msg": "limited"},
            status_code=429,
            headers=(("retry-after", "0"),),
        )

    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.path.endswith("/tenant/v2/tenant/query"):
            return _tenant_response()
        if request.path.endswith("/contact/v3/scopes"):
            return _scope_response(department_ids=("od-root",), user_ids=())
        if request.path.endswith("/contact/v3/departments/od-root/children"):
            if failure_kind.startswith("user_"):
                return _json_response({"code": 0, "msg": "success", "data": {"items": []}})
            return directory_failure_response("department")
        if request.path.endswith("/contact/v3/users/find_by_department"):
            return directory_failure_response("user")
        raise AssertionError(f"unexpected request: {request.method} {request.path}")

    with _run_feishu_stub(monkeypatch, tls_material, respond) as stub:
        adapter = FeishuLarkAdapter(_config())
        result = adapter.directory.read_snapshot()

        assert isinstance(result, OperationFailure)
        assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
        if failure_kind == "rate_limit_exhausted":
            directory_requests = [
                request
                for request in stub.requests
                if request.path.endswith("/contact/v3/departments/od-root/children")
            ]
            assert len(directory_requests) == 4
        adapter.close()


@pytest.mark.parametrize("receive_id_type", ["email", "open_id", "user_id", "union_id"])
def test_feishu_lark_destination_address_types_use_their_real_read_only_operation(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    receive_id_type: str,
) -> None:
    receive_id = "address/../?name=integration"

    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.path.endswith("/contact/v3/users/batch_get_id"):
            return _json_response(
                {"code": 0, "msg": "success", "data": {"user_list": [{"user_id": "ou-1"}]}},
            )
        return _json_response({"code": 0, "msg": "success", "data": {"user": {"open_id": "ou-1"}}})

    with _run_feishu_stub(monkeypatch, tls_material, respond) as stub:
        adapter = FeishuLarkAdapter(_config())
        result = adapter.messaging.test_destination(FeishuUserDestination(receive_id, receive_id_type))

        assert result is None
        destination_request = stub.requests[-1]
        if receive_id_type == "email":
            assert destination_request.method == "POST"
            assert destination_request.path.endswith("/contact/v3/users/batch_get_id")
            assert TypeAdapter(dict[str, list[str]]).validate_json(destination_request.body) == {"emails": [receive_id]}
        else:
            assert destination_request.path.endswith("/contact/v3/users/address%2F..%2F%3Fname%3Dintegration")
            assert destination_request.query["user_id_type"] == receive_id_type
        adapter.close()


def test_feishu_lark_email_destination_requires_a_matching_user_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return _json_response({"code": 0, "msg": "success", "data": {"user_list": []}})

    with _run_feishu_stub(monkeypatch, tls_material, respond) as stub:
        adapter = FeishuLarkAdapter(_config())

        result = adapter.messaging.test_destination(
            FeishuUserDestination("missing@example.com", "email"),
        )

        assert isinstance(result, OperationFailure)
        assert result.code is OperationFailureCode.DESTINATION_UNREACHABLE
        assert [request.path for request in stub.requests] == [
            "/open-apis/auth/v3/tenant_access_token/internal",
            "/open-apis/contact/v3/users/batch_get_id",
        ]
        assert all(not request.path.endswith("/im/v1/messages") for request in stub.requests)
        adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("invalid_type", OperationFailureCode.INVALID_DESTINATION),
        ("dot_segment", OperationFailureCode.PROVIDER),
        ("disconnect", OperationFailureCode.PROVIDER),
        ("malformed", OperationFailureCode.PROVIDER),
        ("rejected", OperationFailureCode.DESTINATION_UNREACHABLE),
    ],
)
def test_feishu_lark_destination_failures_are_typed_over_real_tls(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if failure_kind == "disconnect":
            return _StubResponse(0, b"", disconnect=True)
        if failure_kind == "malformed":
            return _StubResponse(200, b"not-json")
        return _json_response({"code": 230001, "msg": "not found"}, status_code=404)

    receive_id_type = "unknown" if failure_kind == "invalid_type" else "open_id"
    receive_id = "." if failure_kind == "dot_segment" else "ou-user"
    with _run_feishu_stub(monkeypatch, tls_material, respond) as stub:
        adapter = FeishuLarkAdapter(_config())
        result = adapter.messaging.test_destination(FeishuUserDestination(receive_id, receive_id_type))

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        expected_requests = 0 if failure_kind == "invalid_type" else 1 if failure_kind == "dot_segment" else 2
        assert len(stub.requests) == expected_requests
        adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("invalid_destination", OperationFailureCode.INVALID_DESTINATION),
        ("send_disconnect", OperationFailureCode.AMBIGUOUS),
        ("send_rate_limited", OperationFailureCode.RATE_LIMITED),
        ("send_rejected", OperationFailureCode.PROVIDER),
        ("send_malformed", OperationFailureCode.AMBIGUOUS),
        ("send_missing_reference", OperationFailureCode.AMBIGUOUS),
        ("update_missing", OperationFailureCode.STALE_REFERENCE),
        ("update_dot_segment", OperationFailureCode.STALE_REFERENCE),
    ],
)
def test_feishu_lark_message_failures_make_at_most_one_real_side_effecting_call(
    monkeypatch: pytest.MonkeyPatch,
    tls_material: tuple[Path, Path],
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    def respond(request: _RecordedRequest) -> _StubResponse:
        if request.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if failure_kind == "send_disconnect":
            return _StubResponse(0, b"", disconnect=True)
        if failure_kind == "send_rate_limited":
            return _json_response({"code": 1, "msg": "limited"}, status_code=429)
        if failure_kind == "send_rejected":
            return _json_response({"code": 1, "msg": "rejected"}, status_code=400)
        if failure_kind == "send_malformed":
            return _StubResponse(200, b"not-json")
        if failure_kind == "update_missing":
            return _json_response({"code": 230001, "msg": "missing"}, status_code=404)
        return _json_response({"code": 0, "msg": "success", "data": {}})

    destination_type = "invalid" if failure_kind == "invalid_destination" else "open_id"
    with _run_feishu_stub(monkeypatch, tls_material, respond) as stub:
        adapter = FeishuLarkAdapter(_config())
        if failure_kind.startswith("update_"):
            card_messaging = adapter.dynamic_card_messaging
            assert card_messaging is not None
            message_id = "." if failure_kind == "update_dot_segment" else "om-missing"
            result = card_messaging.update_card(
                FeishuMessageReference(message_id),
                CardIntent(None, "Review", (), (), "Review"),
                OpaqueMetadata(entries=()),
            )
        else:
            result = adapter.messaging.send_text(
                FeishuUserDestination("ou-user", destination_type),
                "Hello",
            )

        assert isinstance(result, OperationFailure)
        assert result.code is expected_code
        side_effecting_requests = [
            request
            for request in stub.requests
            if request.path.endswith("/im/v1/messages") or "/im/v1/messages/" in request.path
        ]
        assert len(side_effecting_requests) <= 1
        adapter.close()
