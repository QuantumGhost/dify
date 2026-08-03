"""Feishu and Lark adapter tests at their official OpenAPI boundaries."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

import core.human_input_v2.im_provider.providers.feishu_lark as feishu_provider
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    CredentialTestSuccess,
    DirectoryEntry,
    DirectorySnapshot,
    FeishuLarkAdapter,
    FeishuLarkAdapterConfig,
    OperationFailure,
    OperationFailureCode,
    PermissionFact,
)


def _config(provider: IMProvider = IMProvider.FEISHU) -> FeishuLarkAdapterConfig:
    return FeishuLarkAdapterConfig(
        provider=provider,
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


def _token_response(token: str = "tenant-token", expire: int = 7200) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "msg": "ok",
            "tenant_access_token": token,
            "expire": expire,
        },
    )


def _tenant_response(tenant_key: str = "tenant-key") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "msg": "success",
            "data": {
                "tenant": {
                    "name": "Example tenant",
                    "display_id": "example",
                    "tenant_tag": 0,
                    "tenant_key": tenant_key,
                    "domain": "example.feishu.cn",
                }
            },
        },
    )


def _scope_response(
    *,
    department_ids: tuple[str, ...] = ("od-first",),
    user_ids: tuple[str, ...] = ("ou-root",),
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "msg": "success",
            "data": {
                "department_ids": list(department_ids),
                "user_ids": list(user_ids),
                "group_ids": [],
                "has_more": False,
                "page_token": "",
            },
        },
    )


def _tenant_permission_denied_response() -> httpx.Response:
    return httpx.Response(
        400,
        json={
            "code": 99991672,
            "msg": "raw-provider-message-sentinel",
            "error": {
                "log_id": "sensitive-log-id-sentinel",
                "troubleshooter": "https://open.feishu.cn/search?sensitive-troubleshooter-sentinel",
                "permission_violations": [
                    {
                        "type": "tenant",
                        "subject": "application",
                        "permission": "tenant:tenant:readonly",
                    }
                ],
            },
        },
    )


@pytest.mark.parametrize(
    ("provider", "expected_host"),
    [
        (IMProvider.FEISHU, "open.feishu.cn"),
        (IMProvider.LARK, "open.larksuite.com"),
    ],
)
def test_feishu_lark_credentials_use_provider_specific_host_and_cache_tenant_token(
    monkeypatch: pytest.MonkeyPatch,
    provider: IMProvider,
    expected_host: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.url.path.endswith("/tenant/v2/tenant/query"):
            return _tenant_response()
        if request.url.path.endswith("/contact/v3/scopes"):
            return _scope_response()
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config(provider))

    first_result = adapter.test_credentials()
    second_result = adapter.test_credentials()

    assert first_result == CredentialTestSuccess(
        provider=provider,
        provider_tenant_id="tenant-key",
        permissions=(
            PermissionFact("tenant:tenant:readonly", True),
            PermissionFact("contact.scope.read", True),
        ),
    )
    assert second_result == first_result
    assert all(request.url.host == expected_host for request in requests)
    assert [request.url.path for request in requests].count("/open-apis/auth/v3/tenant_access_token/internal") == 1
    assert all(
        request.headers.get("authorization") == "Bearer tenant-token"
        for request in requests
        if not request.url.path.endswith("/auth/v3/tenant_access_token/internal")
    )

    adapter.close()


def test_feishu_tenant_token_refreshes_after_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_times = iter((100.0, 100.0, 102.0, 102.0))
    monkeypatch.setattr(feishu_provider.time, "monotonic", lambda: next(monotonic_times))
    tokens = iter(("tenant-token-1", "tenant-token-2"))
    authorization_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response(next(tokens), expire=1)
        authorization_headers.append(request.headers["authorization"])
        if request.url.path.endswith("/tenant/v2/tenant/query"):
            return _tenant_response()
        return _scope_response()

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    assert isinstance(adapter.test_credentials(), CredentialTestSuccess)
    assert isinstance(adapter.test_credentials(), CredentialTestSuccess)
    assert authorization_headers == [
        "Bearer tenant-token-1",
        "Bearer tenant-token-1",
        "Bearer tenant-token-2",
        "Bearer tenant-token-2",
    ]

    adapter.close()


@pytest.mark.parametrize(
    ("token_response", "expected_code"),
    [
        (httpx.Response(401, json={"code": 10003, "msg": "invalid app secret"}), OperationFailureCode.AUTHENTICATION),
        (httpx.Response(200, json={"code": 0, "msg": "ok", "expire": 7200}), OperationFailureCode.PROVIDER),
    ],
)
def test_feishu_token_failure_distinguishes_rejected_credentials_from_incomplete_upstream_response(
    monkeypatch: pytest.MonkeyPatch,
    token_response: httpx.Response,
    expected_code: OperationFailureCode,
) -> None:
    _install_http_client(monkeypatch, lambda request: token_response)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    assert "secret-test" not in repr(result)

    adapter.close()


def test_feishu_missing_tenant_key_is_tenant_identification_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {"tenant": {}}})

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.TENANT_IDENTIFICATION

    adapter.close()


def test_feishu_tenant_query_permission_violation_is_missing_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return _tenant_permission_denied_response()

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.MISSING_PERMISSION
    assert "tenant:tenant:readonly" in result.message
    assert "raw-provider-message-sentinel" not in repr(result)
    assert "sensitive-log-id-sentinel" not in repr(result)
    assert "sensitive-troubleshooter-sentinel" not in repr(result)

    adapter.close()


def test_feishu_directory_preserves_tenant_query_missing_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return _tenant_permission_denied_response()

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.MISSING_PERMISSION
    assert "tenant:tenant:readonly" in result.message
    assert "raw-provider-message-sentinel" not in repr(result)
    assert "sensitive-log-id-sentinel" not in repr(result)
    assert "sensitive-troubleshooter-sentinel" not in repr(result)

    adapter.close()


def test_feishu_ordinary_contact_scope_rejection_is_directory_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.url.path.endswith("/tenant/v2/tenant/query"):
            return _tenant_response()
        return httpx.Response(403, json={"code": 99991672, "msg": "access denied"})

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE

    adapter.close()


def test_feishu_directory_reads_all_department_and_user_pages_before_publishing_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_user_pages: list[tuple[str, str | None]] = []
    directory_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.url.path.endswith("/tenant/v2/tenant/query"):
            return _tenant_response()
        if request.url.path.endswith("/contact/v3/scopes"):
            directory_requests.append(request)
            return _scope_response(department_ids=("od-root",), user_ids=())
        if request.url.path.endswith("/contact/v3/departments/od-root/children"):
            directory_requests.append(request)
            assert request.url.params["fetch_child"] == "true"
            if request.url.params.get("page_token") is None:
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "msg": "success",
                        "data": {
                            "items": [{"name": "Engineering", "open_department_id": "od-eng"}],
                            "has_more": True,
                            "page_token": "department-page-2",
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "items": [{"name": "Operations", "open_department_id": "od-ops"}],
                        "has_more": False,
                        "page_token": "",
                    },
                },
            )
        if request.url.path.endswith("/contact/v3/users/find_by_department"):
            directory_requests.append(request)
            department_id = request.url.params["department_id"]
            page_token = request.url.params.get("page_token")
            requested_user_pages.append((department_id, page_token))
            if department_id == "od-root":
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "msg": "success",
                        "data": {
                            "items": [
                                {
                                    "open_id": "ou-root",
                                    "name": "Root User",
                                    "email": "root@example.com",
                                    "status": {
                                        "is_activated": True,
                                        "is_frozen": False,
                                        "is_resigned": False,
                                        "is_exited": False,
                                        "is_unjoin": False,
                                    },
                                },
                                {"open_id": "ou-pending", "name": "Pending", "status": {}},
                                {
                                    "open_id": "ou-deactivated",
                                    "name": "Deactivated",
                                    "status": {"is_activated": False},
                                },
                            ],
                            "has_more": False,
                            "page_token": "",
                        },
                    },
                )
            if department_id == "od-eng" and page_token is None:
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "msg": "success",
                        "data": {
                            "items": [
                                {
                                    "open_id": "ou-ada",
                                    "name": "Ada",
                                    "enterprise_email": "ada@example.com",
                                    "status": {"is_activated": True},
                                }
                            ],
                            "has_more": True,
                            "page_token": "user-page-2",
                        },
                    },
                )
            if department_id == "od-eng":
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "msg": "success",
                        "data": {
                            "items": [{"open_id": "ou-lin", "name": "Lin", "status": {"is_frozen": True}}],
                            "has_more": False,
                            "page_token": "",
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "items": [{"open_id": "ou-ada", "name": "Ada duplicate"}],
                        "has_more": False,
                        "page_token": "",
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(
        FeishuLarkAdapterConfig(
            provider=IMProvider.FEISHU,
            app_id="cli_test",
            app_secret="secret-test",
            verification_token="verification-test",
            encrypt_key="encrypt-test",
            directory_page_size=1,
        )
    )

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.FEISHU,
        provider_tenant_id="tenant-key",
        entries=(
            DirectoryEntry("ou-root", "Root User", "root@example.com", True),
            DirectoryEntry("ou-pending", "Pending", None, None),
            DirectoryEntry("ou-deactivated", "Deactivated", None, False),
            DirectoryEntry("ou-ada", "Ada", "ada@example.com", True),
            DirectoryEntry("ou-lin", "Lin", None, False),
        ),
    )
    assert requested_user_pages == [
        ("od-root", None),
        ("od-eng", None),
        ("od-eng", "user-page-2"),
        ("od-ops", None),
    ]
    assert directory_requests
    assert all(request.url.params["page_size"] == "1" for request in directory_requests)

    adapter.close()


@pytest.mark.parametrize(
    ("failure_stage", "expected_code"),
    [
        ("token_transport", OperationFailureCode.PROVIDER),
        ("token_invalid", OperationFailureCode.PROVIDER),
        ("tenant_transport", OperationFailureCode.TENANT_IDENTIFICATION),
        ("tenant_invalid", OperationFailureCode.TENANT_IDENTIFICATION),
        ("scope_transport", OperationFailureCode.DIRECTORY_INCOMPLETE),
        ("scope_invalid", OperationFailureCode.DIRECTORY_INCOMPLETE),
    ],
)
def test_feishu_credential_boundary_translates_transport_and_invalid_responses(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    expected_code: OperationFailureCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            if failure_stage == "token_transport":
                raise httpx.ConnectError("token failed", request=request)
            if failure_stage == "token_invalid":
                return httpx.Response(200, content=b"not-json")
            return _token_response()
        if request.url.path.endswith("/tenant/v2/tenant/query"):
            if failure_stage == "tenant_transport":
                raise httpx.ConnectError("tenant failed", request=request)
            if failure_stage == "tenant_invalid":
                return httpx.Response(200, content=b"not-json")
            return _tenant_response()
        if failure_stage == "scope_transport":
            raise httpx.ConnectError("scope failed", request=request)
        if failure_stage == "scope_invalid":
            return httpx.Response(200, content=b"not-json")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code

    adapter.close()


@pytest.mark.parametrize(
    "failure_kind",
    ["missing_page_token", "blank_department_id", "transport", "rate_limit"],
)
def test_feishu_directory_rejects_incomplete_department_traversal(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    directory_requests = 0
    monkeypatch.setattr(feishu_provider.time, "sleep", lambda delay: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal directory_requests
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.url.path.endswith("/tenant/v2/tenant/query"):
            return _tenant_response()
        if request.url.path.endswith("/contact/v3/scopes"):
            return _scope_response(department_ids=("od-root",), user_ids=())
        directory_requests += 1
        if failure_kind == "transport":
            raise httpx.ConnectError("directory failed", request=request)
        if failure_kind == "rate_limit":
            return httpx.Response(429, headers={"retry-after": "0"})
        department_id = " " if failure_kind == "blank_department_id" else "od-eng"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "success",
                "data": {
                    "items": [{"open_department_id": department_id}],
                    "has_more": failure_kind == "missing_page_token",
                },
            },
        )

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    assert directory_requests == (4 if failure_kind == "rate_limit" else 1)

    adapter.close()


def test_feishu_directory_late_page_failure_returns_no_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_page_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal user_page_count
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        if request.url.path.endswith("/tenant/v2/tenant/query"):
            return _tenant_response()
        if request.url.path.endswith("/contact/v3/scopes"):
            return _scope_response(department_ids=("od-root",), user_ids=())
        if "/departments/od-root/children" in request.url.path:
            return httpx.Response(
                200,
                json={"code": 0, "msg": "success", "data": {"items": [], "has_more": False}},
            )
        user_page_count += 1
        if user_page_count == 1:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "items": [{"open_id": "ou-ada", "name": "Ada"}],
                        "has_more": True,
                        "page_token": "page-2",
                    },
                },
            )
        return httpx.Response(500, json={"code": 50001, "msg": "internal error"})

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    assert not isinstance(result, DirectorySnapshot)

    adapter.close()
