"""Regression tests derived from the live Feishu directory contract."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

import core.human_input_v2.im_provider.providers.feishu_lark as feishu_provider
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    DirectoryEntry,
    DirectorySnapshot,
    FeishuLarkAdapter,
    FeishuLarkAdapterConfig,
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


def _tenant_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "msg": "success",
            "data": {"tenant": {"tenant_key": "tenant-key"}},
        },
    )


def _scope_response(
    *,
    department_ids: tuple[str, ...] = (),
    user_ids: tuple[str, ...] = (),
    has_more: bool = False,
    page_token: str = "",
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
                "has_more": has_more,
                "page_token": page_token,
            },
        },
    )


def _department_page(
    *department_ids: str,
    has_more: bool = False,
    page_token: str = "",
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "msg": "success",
            "data": {
                "items": [{"open_department_id": department_id} for department_id in department_ids],
                "has_more": has_more,
                "page_token": page_token,
            },
        },
    )


def _user_page(
    *users: dict[str, object],
    has_more: bool = False,
    page_token: str = "",
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "msg": "success",
            "data": {
                "items": list(users),
                "has_more": has_more,
                "page_token": page_token,
            },
        },
    )


def _profile_response(
    open_id: str,
    name: str,
    *,
    email: str | None = None,
    activated: bool = True,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "msg": "success",
            "data": {
                "user": {
                    "open_id": open_id,
                    "union_id": f"union-{open_id}",
                    "user_id": f"user-{open_id}",
                    "name": name,
                    "en_name": name,
                    "nickname": name,
                    "email": email,
                    "enterprise_email": "",
                    "mobile": "",
                    "mobile_visible": False,
                    "gender": 0,
                    "avatar": {},
                    "status": {
                        "is_frozen": False,
                        "is_resigned": False,
                        "is_activated": activated,
                        "is_exited": False,
                        "is_unjoin": False,
                    },
                    "department_ids": [],
                    "leader_user_id": "",
                    "city": "",
                    "country": "",
                    "work_station": "",
                    "join_time": 0,
                    "is_tenant_manager": False,
                    "employee_no": "",
                    "employee_type": 0,
                    "orders": [],
                    "custom_attrs": [],
                    "job_title": "",
                }
            },
        },
    )


def _user_without_name(open_id: str) -> dict[str, object]:
    return {
        "open_id": open_id,
        "union_id": "union-private-id-sentinel",
        "user_id": "user-private-id-sentinel",
        "en_name": "Fallback English Name Sentinel",
        "nickname": "Fallback Nickname Sentinel",
        "email": "private-email-sentinel@example.invalid",
        "enterprise_email": "private-enterprise-email-sentinel@example.invalid",
        "mobile": "private-mobile-sentinel",
        "mobile_visible": False,
        "gender": 0,
        "avatar": {},
        "status": {
            "is_frozen": False,
            "is_resigned": False,
            "is_activated": True,
            "is_exited": False,
            "is_unjoin": False,
        },
        "department_ids": ["od-private-id-sentinel"],
        "leader_user_id": "ou-private-leader-sentinel",
        "city": "private-city-sentinel",
        "country": "private-country-sentinel",
        "work_station": "private-workstation-sentinel",
        "join_time": 0,
        "is_tenant_manager": False,
        "employee_no": "private-employee-number-sentinel",
        "employee_type": 0,
        "orders": [],
        "custom_attrs": [],
        "job_title": "private-job-title-sentinel",
    }


def _common_response(request: httpx.Request) -> httpx.Response | None:
    if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
        return _token_response()
    if request.url.path.endswith("/tenant/v2/tenant/query"):
        return _tenant_response()
    return None


def test_feishu_directory_uses_endpoint_specific_page_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_page_sizes: list[str] = []
    department_page_sizes: list[str] = []
    user_page_sizes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        common_response = _common_response(request)
        if common_response is not None:
            return common_response
        if request.url.path.endswith("/contact/v3/scopes"):
            scope_page_sizes.append(request.url.params["page_size"])
            return _scope_response(department_ids=("od-visible-root",))
        if "/contact/v3/departments/" in request.url.path:
            department_page_sizes.append(request.url.params["page_size"])
            return _department_page()
        if request.url.path.endswith("/contact/v3/users/find_by_department"):
            user_page_sizes.append(request.url.params["page_size"])
            return _user_page()
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(IMProvider.FEISHU, "tenant-key", ())
    assert scope_page_sizes == ["100"]
    assert department_page_sizes == ["50"]
    assert user_page_sizes == ["50"]
    adapter.close()


def test_feishu_directory_paginates_visible_roots_and_deduplicates_explicit_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_page_tokens: list[str | None] = []
    child_requests: list[tuple[str, str | None]] = []
    user_department_ids: list[str] = []
    profile_user_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        common_response = _common_response(request)
        if common_response is not None:
            return common_response
        path = request.url.path
        if path.endswith("/contact/v3/scopes"):
            page_token = request.url.params.get("page_token")
            scope_page_tokens.append(page_token)
            if page_token is None:
                return _scope_response(
                    department_ids=("od-root-a",),
                    user_ids=("ou-explicit",),
                    has_more=True,
                    page_token="scope-page-2",
                )
            return _scope_response(
                department_ids=("od-root-b",),
                user_ids=("ou-explicit", "ou-scope-2"),
            )
        if "/contact/v3/departments/" in path:
            root_id = path.rsplit("/", 2)[-2]
            page_token = request.url.params.get("page_token")
            child_requests.append((root_id, page_token))
            if root_id == "0":
                return _department_page()
            assert request.url.params["fetch_child"] == "true"
            if root_id == "od-root-a" and page_token is None:
                return _department_page("od-child-a", has_more=True, page_token="department-page-2")
            if root_id == "od-root-a":
                return _department_page("od-child-b")
            return _department_page()
        if path.endswith("/contact/v3/users/find_by_department"):
            department_id = request.url.params["department_id"]
            user_department_ids.append(department_id)
            if department_id == "od-root-a":
                return _user_page(
                    {"open_id": "ou-explicit", "name": "Stale duplicate"},
                    {
                        "open_id": "ou-department",
                        "name": "Department User",
                        "status": {"is_activated": True},
                    },
                )
            if department_id == "od-child-a":
                return _user_page(
                    {
                        "open_id": "ou-child",
                        "name": "Child User",
                        "enterprise_email": "child@example.com",
                        "status": {"is_activated": True},
                    }
                )
            return _user_page()
        if "/contact/v3/users/" in path:
            open_id = path.rsplit("/", 1)[-1]
            profile_user_ids.append(open_id)
            assert request.url.params["user_id_type"] == "open_id"
            if open_id == "ou-explicit":
                return _profile_response(open_id, "Explicit User", email="explicit@example.com")
            return _profile_response(open_id, "Scope User")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, DirectorySnapshot)
    assert result.provider_tenant_id == "tenant-key"
    assert set(result.entries) == {
        DirectoryEntry("ou-explicit", "Explicit User", "explicit@example.com", True),
        DirectoryEntry("ou-scope-2", "Scope User", None, True),
        DirectoryEntry("ou-department", "Department User", None, True),
        DirectoryEntry("ou-child", "Child User", "child@example.com", True),
    }
    assert len(result.entries) == 4
    assert scope_page_tokens == [None, "scope-page-2"]
    assert child_requests == [
        ("od-root-a", None),
        ("od-root-a", "department-page-2"),
        ("od-root-b", None),
    ]
    assert user_department_ids == ["od-root-a", "od-child-a", "od-child-b", "od-root-b"]
    assert profile_user_ids == ["ou-explicit", "ou-scope-2"]
    adapter.close()


@pytest.mark.parametrize(
    "failure_stage",
    ["scope_page", "department_page", "department_user_page", "explicit_profile"],
)
def test_feishu_directory_late_failure_never_returns_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        common_response = _common_response(request)
        if common_response is not None:
            return common_response
        path = request.url.path
        if path.endswith("/contact/v3/scopes"):
            page_token = request.url.params.get("page_token")
            if failure_stage == "scope_page":
                if page_token is None:
                    return _scope_response(
                        department_ids=("od-visible-root",),
                        has_more=True,
                        page_token="scope-page-2",
                    )
                return httpx.Response(500, json={"code": 50001, "msg": "scope failed"})
            explicit_users = ("ou-first", "ou-failing") if failure_stage == "explicit_profile" else ()
            return _scope_response(department_ids=("od-visible-root",), user_ids=explicit_users)
        if "/contact/v3/departments/" in path:
            root_id = path.rsplit("/", 2)[-2]
            if root_id == "0":
                return _department_page()
            page_token = request.url.params.get("page_token")
            if failure_stage == "department_page":
                if page_token is None:
                    return _department_page("od-first-child", has_more=True, page_token="department-page-2")
                return httpx.Response(500, json={"code": 50002, "msg": "department failed"})
            return _department_page()
        if path.endswith("/contact/v3/users/find_by_department"):
            page_token = request.url.params.get("page_token")
            if failure_stage == "department_user_page":
                if page_token is None:
                    return _user_page(
                        {"open_id": "ou-first", "name": "First User"},
                        has_more=True,
                        page_token="user-page-2",
                    )
                return httpx.Response(500, json={"code": 50003, "msg": "user page failed"})
            return _user_page()
        if "/contact/v3/users/" in path:
            open_id = path.rsplit("/", 1)[-1]
            if open_id == "ou-failing":
                return httpx.Response(500, json={"code": 50004, "msg": "profile failed"})
            return _profile_response(open_id, "First User")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert not isinstance(result, DirectorySnapshot)
    adapter.close()


def test_feishu_directory_missing_explicit_profile_name_is_static_permission_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        common_response = _common_response(request)
        if common_response is not None:
            return common_response
        path = request.url.path
        if path.endswith("/contact/v3/scopes"):
            return _scope_response(user_ids=("ou-first", "ou-private-id-sentinel"))
        if path.endswith("/contact/v3/users/ou-first"):
            return _profile_response("ou-first", "First User")
        if path.endswith("/contact/v3/users/ou-private-id-sentinel"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "raw-provider-message-sentinel",
                    "data": {"user": _user_without_name("ou-private-id-sentinel")},
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert not isinstance(result, DirectorySnapshot)
    assert result.code is OperationFailureCode.MISSING_PERMISSION
    assert result.message == "Feishu/Lark app is missing required permission: contact:user.base:readonly"
    result_representation = repr(result)
    assert "raw-provider-message-sentinel" not in result_representation
    assert "ou-private-id-sentinel" not in result_representation
    assert "private-email-sentinel@example.invalid" not in result_representation
    assert "Fallback English Name Sentinel" not in result_representation
    assert "Fallback Nickname Sentinel" not in result_representation
    adapter.close()


def test_feishu_directory_missing_department_user_name_is_static_permission_failure_without_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_user_pages: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        common_response = _common_response(request)
        if common_response is not None:
            return common_response
        path = request.url.path
        if path.endswith("/contact/v3/scopes"):
            return _scope_response(department_ids=("od-visible-root",))
        if path.endswith("/contact/v3/departments/od-visible-root/children"):
            return _department_page()
        if path.endswith("/contact/v3/users/find_by_department"):
            page_token = request.url.params.get("page_token")
            requested_user_pages.append(page_token)
            if page_token is None:
                return _user_page(
                    {
                        "open_id": "ou-first",
                        "name": "First User",
                        "status": {"is_activated": True},
                    },
                    has_more=True,
                    page_token="user-page-2",
                )
            return _user_page(_user_without_name("ou-private-id-sentinel"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert requested_user_pages == [None, "user-page-2"]
    assert isinstance(result, OperationFailure)
    assert not isinstance(result, DirectorySnapshot)
    assert result.code is OperationFailureCode.MISSING_PERMISSION
    assert result.message == "Feishu/Lark app is missing required permission: contact:user.base:readonly"
    result_representation = repr(result)
    assert "ou-first" not in result_representation
    assert "ou-private-id-sentinel" not in result_representation
    assert "private-email-sentinel@example.invalid" not in result_representation
    assert "Fallback English Name Sentinel" not in result_representation
    assert "Fallback Nickname Sentinel" not in result_representation
    adapter.close()


@pytest.mark.parametrize(
    ("provider_code", "expected_code"),
    [
        pytest.param(99992402, OperationFailureCode.DIRECTORY_INCOMPLETE, id="invalid-page-size"),
        pytest.param(40004, OperationFailureCode.MISSING_PERMISSION, id="department-scope-denied"),
        pytest.param(40014, OperationFailureCode.MISSING_PERMISSION, id="user-scope-denied"),
    ],
)
def test_feishu_directory_distinguishes_invalid_request_from_scope_denial(
    monkeypatch: pytest.MonkeyPatch,
    provider_code: int,
    expected_code: OperationFailureCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        common_response = _common_response(request)
        if common_response is not None:
            return common_response
        if request.url.path.endswith("/contact/v3/scopes"):
            return _scope_response(department_ids=("od-visible-root",))
        if "/contact/v3/departments/" in request.url.path:
            return httpx.Response(
                400,
                json={"code": provider_code, "msg": "raw-provider-message-sentinel"},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    assert "raw-provider-message-sentinel" not in repr(result)
    adapter.close()
