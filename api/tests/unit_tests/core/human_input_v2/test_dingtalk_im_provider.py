"""DingTalk adapter tests at official OpenAPI boundaries."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

import core.human_input_v2.im_provider.providers.dingtalk as dingtalk_provider
from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    CredentialTestSuccess,
    DingTalkAdapter,
    DingTalkAdapterConfig,
    DingTalkMessageReference,
    DingTalkUserDestination,
    DirectoryEntry,
    DirectorySnapshot,
    MessageAccepted,
    OperationFailure,
    OperationFailureCode,
    PermissionFact,
)


def _config() -> DingTalkAdapterConfig:
    return DingTalkAdapterConfig(
        corp_id="ding-tenant-test",
        client_id="client-test",
        client_secret="secret-test",
    )


def _install_http_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    client_options: list[dict[str, object]],
) -> None:
    def create_client(**kwargs: object) -> httpx.Client:
        client_options.append(kwargs)
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(dingtalk_provider, "create_ssrf_protected_client", create_client)


def _token_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": "access-token",
            "expires_in": 7200,
        },
    )


def _is_token_request(request: httpx.Request) -> bool:
    return request.url.path == "/v1.0/oauth2/ding-tenant-test/token"


def test_dingtalk_api_config_keeps_only_credential_directory_and_messaging_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/topapi/v2/department/listsub":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        if request.url.path == "/topapi/v2/user/list":
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
            )
        if request.url.path == "/topapi/v2/user/get":
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"userid": "user-test", "name": "Ada"}},
            )
        if request.url.path == "/v1.0/robot/oToMessages/batchSend":
            return httpx.Response(200, json={"processQueryKey": "process-key"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    config = DingTalkAdapterConfig(
        corp_id="ding-tenant-test",
        client_id="client-test",
        client_secret="secret-test",
    )
    adapter = DingTalkAdapter(config)
    destination = DingTalkUserDestination("user-test")

    credential_result = adapter.test_credentials()
    directory_result = adapter.directory.read_snapshot()
    destination_result = adapter.messaging.test_destination(destination)
    message_result = adapter.messaging.send_text(destination, "Hello")

    assert isinstance(credential_result, CredentialTestSuccess)
    assert directory_result == DirectorySnapshot(IMProvider.DING_TALK, "ding-tenant-test", ())
    assert destination_result is None
    assert message_result == MessageAccepted(
        DingTalkMessageReference(user_id="user-test", message_id="process-key"),
        None,
    )
    assert adapter.webhook_events is None
    assert adapter.stream_events is None
    adapter.close()


def test_dingtalk_credentials_reuse_token_and_confirm_directory_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    client_options: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _is_token_request(request):
            assert json.loads(request.content) == {
                "client_id": "client-test",
                "client_secret": "secret-test",
                "grant_type": "client_credentials",
            }
            return _token_response()
        assert request.url.host == "oapi.dingtalk.com"
        assert request.url.params["access_token"] == "access-token"
        if request.url.path == "/topapi/v2/department/listsub":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        if request.url.path == "/topapi/v2/user/list":
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "result": {"list": [], "has_more": False, "next_cursor": 0},
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, client_options)
    adapter = DingTalkAdapter(_config())

    first_result = adapter.test_credentials()
    second_result = adapter.test_credentials()

    assert isinstance(first_result, CredentialTestSuccess)
    assert first_result.provider_tenant_id == "ding-tenant-test"
    assert first_result.permissions == (
        PermissionFact("contact.department.read", True),
        PermissionFact("contact.user.read", True),
    )
    assert second_result == first_result
    assert sum(_is_token_request(request) for request in requests) == 1
    assert str(requests[0].url) == "https://api.dingtalk.com/v1.0/oauth2/ding-tenant-test/token"
    assert client_options == [{"verify": True, "timeout": 10.0}]

    adapter.close()


def test_dingtalk_rate_limited_access_token_is_a_typed_rate_limit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, json={"code": "TooManyRequests", "message": "rate limited"})

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.RATE_LIMITED
    assert len(requests) == 1
    assert "secret-test" not in repr(result)
    adapter.close()


@pytest.mark.parametrize(
    ("token_response", "expected_code"),
    [
        pytest.param(
            httpx.Response(400, json={"code": "invalid.client", "message": "invalid client"}),
            OperationFailureCode.AUTHENTICATION,
            id="invalid-client",
        ),
        pytest.param(
            httpx.Response(400, json={"code": "unauthorized.client", "message": "unauthorized client"}),
            OperationFailureCode.AUTHENTICATION,
            id="unauthorized-client",
        ),
        pytest.param(
            httpx.Response(400, json={"code": "unsupported.grant.type", "message": "unsupported grant"}),
            OperationFailureCode.AUTHENTICATION,
            id="unsupported-grant-type",
        ),
        pytest.param(
            httpx.Response(401, json={"code": "InvalidAuthentication", "message": "invalid secret"}),
            OperationFailureCode.AUTHENTICATION,
            id="unauthorized-http-status",
        ),
        pytest.param(
            httpx.Response(503, json={"code": "ServiceUnavailable", "message": "unavailable"}),
            OperationFailureCode.PROVIDER,
            id="provider-unavailable",
        ),
        pytest.param(
            httpx.Response(200, content=b"not-json"),
            OperationFailureCode.PROVIDER,
            id="malformed-response",
        ),
        pytest.param(
            httpx.Response(200, json={"access_token": "access-token"}),
            OperationFailureCode.PROVIDER,
            id="incomplete-response",
        ),
        pytest.param(
            httpx.Response(200, json={"access_token": "", "expires_in": 7200}),
            OperationFailureCode.PROVIDER,
            id="blank-access-token",
        ),
    ],
)
def test_dingtalk_token_response_distinguishes_authentication_rejection_from_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
    token_response: httpx.Response,
    expected_code: OperationFailureCode,
) -> None:
    _install_http_client(monkeypatch, lambda request: token_response, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    assert "secret-test" not in repr(result)

    adapter.close()


def test_dingtalk_token_transport_and_invalid_tenant_fail_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def network_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _install_http_client(monkeypatch, network_failure, [])
    adapter = DingTalkAdapter(_config())

    network_result = adapter.test_credentials()

    assert isinstance(network_result, OperationFailure)
    assert network_result.code is OperationFailureCode.PROVIDER
    adapter.close()

    for invalid_corp_id in (".", "\ud800"):
        invalid_config = DingTalkAdapterConfig(
            corp_id=invalid_corp_id,
            client_id="client-test",
            client_secret="secret-test",
        )
        _install_http_client(monkeypatch, lambda request: _token_response(), [])
        invalid_adapter = DingTalkAdapter(invalid_config)

        invalid_result = invalid_adapter.test_credentials()

        assert isinstance(invalid_result, OperationFailure)
        assert invalid_result.code is OperationFailureCode.AUTHENTICATION
        invalid_adapter.close()


def test_dingtalk_directory_reads_the_complete_hierarchy_and_deduplicates_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_page_requests: list[tuple[int, int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            return _token_response()
        request_body = json.loads(request.content)
        if request.url.path == "/topapi/v2/department/listsub":
            department_id = request_body["dept_id"]
            departments = {
                1: [{"dept_id": 2, "name": "Engineering"}, {"dept_id": 3, "name": "Support"}],
                2: [{"dept_id": 4, "name": "Platform"}],
                3: [{"dept_id": 4, "name": "Platform duplicate"}],
                4: [],
            }[department_id]
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": departments})
        if request.url.path == "/topapi/v2/user/list":
            department_id = request_body["dept_id"]
            cursor = request_body["cursor"]
            size = request_body["size"]
            user_page_requests.append((department_id, cursor, size))
            if len(user_page_requests) == 1:
                return httpx.Response(
                    200,
                    json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
                )
            pages = {
                (1, 0): {
                    "list": [{"userid": "user-root", "name": "Root User", "active": True}],
                    "has_more": True,
                    "next_cursor": 100,
                },
                (1, 100): {
                    "list": [{"userid": "user-shared", "name": "Shared User", "email": "shared@example.com"}],
                    "has_more": False,
                },
                (2, 0): {
                    "list": [{"userid": "user-shared", "name": "Shared User", "email": "shared@example.com"}],
                    "has_more": False,
                },
                (3, 0): {
                    "list": [{"userid": "user-support", "name": "Support User", "active": False}],
                    "has_more": False,
                },
                (4, 0): {"list": [], "has_more": False},
            }
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": pages[(department_id, cursor)]},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(
        DingTalkAdapterConfig(
            corp_id="ding-tenant-test",
            client_id="client-test",
            client_secret="secret-test",
            directory_page_size=1,
        )
    )

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.DING_TALK,
        provider_tenant_id="ding-tenant-test",
        entries=(
            DirectoryEntry("user-root", "Root User", None, True),
            DirectoryEntry("user-shared", "Shared User", "shared@example.com", None),
            DirectoryEntry("user-support", "Support User", None, False),
        ),
    )
    assert user_page_requests == [
        (1, 0, 1),
        (1, 0, 1),
        (1, 100, 1),
        (2, 0, 1),
        (3, 0, 1),
        (4, 0, 1),
    ]

    adapter.close()


def test_dingtalk_directory_late_failure_does_not_publish_a_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal user_page_calls
        if _is_token_request(request):
            return _token_response()
        request_body = json.loads(request.content)
        if request.url.path == "/topapi/v2/department/listsub":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        if request_body["size"] == 1:
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
            )
        user_page_calls += 1
        if user_page_calls == 1:
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "result": {
                        "list": [{"userid": "user-first", "name": "First User"}],
                        "has_more": True,
                        "next_cursor": 100,
                    },
                },
            )
        return httpx.Response(503, json={"errcode": 500, "errmsg": "unavailable"})

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE

    adapter.close()


def test_dingtalk_directory_retries_one_rate_limited_read_only_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal directory_page_calls
        if _is_token_request(request):
            return _token_response()
        request_body = json.loads(request.content)
        if request.url.path == "/topapi/v2/department/listsub":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        if request_body["size"] == 1:
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
            )
        directory_page_calls += 1
        if directory_page_calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={
                "errcode": 0,
                "errmsg": "ok",
                "result": {
                    "list": [{"userid": "user-1", "name": "Ada"}],
                    "has_more": False,
                },
            },
        )

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.DING_TALK,
        provider_tenant_id="ding-tenant-test",
        entries=(DirectoryEntry("user-1", "Ada", None, None),),
    )
    assert directory_page_calls == 2
    adapter.close()


def test_dingtalk_directory_bounds_rate_limit_retries_after_a_completed_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory_page_calls = 0
    rate_limited_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal directory_page_calls, rate_limited_calls
        if _is_token_request(request):
            return _token_response()
        request_body = json.loads(request.content)
        if request.url.path == "/topapi/v2/department/listsub":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        if request_body["size"] == 1:
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
            )
        directory_page_calls += 1
        if directory_page_calls == 1:
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "result": {
                        "list": [{"userid": "user-first", "name": "First User"}],
                        "has_more": True,
                        "next_cursor": 100,
                    },
                },
            )
        rate_limited_calls += 1
        return httpx.Response(429, headers={"retry-after": "0"})

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    assert rate_limited_calls == 4
    adapter.close()


def test_dingtalk_destination_check_uses_read_only_user_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _is_token_request(request):
            return _token_response()
        assert request.url.path == "/topapi/v2/user/get"
        assert dict(request.url.params) == {"access_token": "access-token"}
        assert json.loads(request.content) == {"userid": "user-test"}
        return httpx.Response(
            200,
            json={"errcode": 0, "errmsg": "ok", "result": {"userid": "user-test", "name": "Ada"}},
        )

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.messaging.test_destination(DingTalkUserDestination("user-test"))

    assert result is None
    assert sum(_is_token_request(request) for request in requests) == 1
    assert requests[-1].url.path == "/topapi/v2/user/get"

    adapter.close()


def test_dingtalk_send_text_returns_the_exact_process_query_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            return _token_response()
        assert request.url.path == "/v1.0/robot/oToMessages/batchSend"
        assert request.headers["x-acs-dingtalk-access-token"] == "access-token"
        assert json.loads(request.content) == {
            "robotCode": "client-test",
            "userIds": ["user-test"],
            "msgKey": "sampleMarkdown",
            "msgParam": '{"title":"Release status","text":"**Release status**\\n\\nReady"}',
        }
        return httpx.Response(
            200,
            headers={"x-acs-request-id": "request-1"},
            json={"processQueryKey": "process-key"},
        )

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.messaging.send_text(
        DingTalkUserDestination("user-test"),
        "**Release status**\n\nReady",
    )

    assert result == MessageAccepted(
        reference=DingTalkMessageReference(user_id="user-test", message_id="process-key"),
        provider_request_id="request-1",
    )

    adapter.close()


def test_dingtalk_send_timeout_is_ambiguous_and_is_not_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal send_calls
        if _is_token_request(request):
            return _token_response()
        send_calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.messaging.send_text(
        DingTalkUserDestination("user-test"),
        "Hello",
    )

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.AMBIGUOUS
    assert send_calls == 1

    adapter.close()


@pytest.mark.parametrize(
    ("permission_response", "expected_code"),
    [
        pytest.param(
            httpx.Response(401, json={"errcode": 40014, "errmsg": "invalid token"}),
            OperationFailureCode.AUTHENTICATION,
            id="authentication",
        ),
        pytest.param(
            httpx.Response(403, json={"errcode": 60011, "errmsg": "forbidden"}),
            OperationFailureCode.MISSING_PERMISSION,
            id="forbidden",
        ),
        pytest.param(
            httpx.Response(429, json={"errcode": 88, "errmsg": "rate limited"}),
            OperationFailureCode.RATE_LIMITED,
            id="rate-limited",
        ),
        pytest.param(
            httpx.Response(200, json={"errcode": 12345, "errmsg": "provider rejected"}),
            OperationFailureCode.PROVIDER,
            id="unknown-rejection",
        ),
        pytest.param(
            httpx.Response(200, json={"errcode": 60011, "errmsg": "permission denied"}),
            OperationFailureCode.MISSING_PERMISSION,
            id="provider-permission-code",
        ),
        pytest.param(httpx.Response(200, content=b"not-json"), OperationFailureCode.PROVIDER, id="malformed"),
    ],
)
def test_dingtalk_permission_probe_preserves_failure_category(
    monkeypatch: pytest.MonkeyPatch,
    permission_response: httpx.Response,
    expected_code: OperationFailureCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            return _token_response()
        return permission_response

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    adapter.close()


def test_dingtalk_permission_probe_maps_network_failure_to_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            return _token_response()
        raise httpx.ReadTimeout("timed out", request=request)

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER
    adapter.close()


def test_dingtalk_second_permission_probe_preserves_failure_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/topapi/v2/department/listsub":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        return httpx.Response(429, json={"errcode": 88, "errmsg": "rate limited"})

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.RATE_LIMITED
    adapter.close()


@pytest.mark.parametrize("failure_path", ["department", "user"])
def test_dingtalk_directory_rejects_malformed_provider_traversal(
    monkeypatch: pytest.MonkeyPatch,
    failure_path: str,
) -> None:
    permission_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal permission_calls
        if _is_token_request(request):
            return _token_response()
        if permission_calls < 2:
            permission_calls += 1
            if request.url.path == "/topapi/v2/department/listsub":
                return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
            )
        if failure_path == "department" or request.url.path == "/topapi/v2/user/list":
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    adapter.close()


def test_dingtalk_directory_rejects_non_forward_pagination_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permission_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal permission_calls
        if _is_token_request(request):
            return _token_response()
        if permission_calls < 2:
            permission_calls += 1
            if request.url.path == "/topapi/v2/department/listsub":
                return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
            )
        if request.url.path == "/topapi/v2/department/listsub":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        return httpx.Response(
            200,
            json={
                "errcode": 0,
                "errmsg": "ok",
                "result": {"list": [], "has_more": True, "next_cursor": 0},
            },
        )

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    adapter.close()


def test_dingtalk_directory_retries_rate_limited_read_without_publishing_partial_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    department_probe_calls = 0
    retry_sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal department_probe_calls
        if _is_token_request(request):
            return _token_response()
        request_body = json.loads(request.content)
        if request.url.path == "/topapi/v2/department/listsub":
            department_probe_calls += 1
            if department_probe_calls in (2, 3):
                return httpx.Response(
                    429,
                    headers={"retry-after": "0.25"},
                    json={"errcode": 88, "errmsg": "rate limited"},
                )
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        assert request.url.path == "/topapi/v2/user/list"
        if request_body["size"] == 1:
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
            )
        return httpx.Response(
            200,
            json={
                "errcode": 0,
                "errmsg": "ok",
                "result": {
                    "list": [{"userid": "user-1", "name": "Example User"}],
                    "has_more": False,
                },
            },
        )

    _install_http_client(monkeypatch, handler, [])
    monkeypatch.setattr(dingtalk_provider.time, "sleep", retry_sleeps.append)
    adapter = DingTalkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.DING_TALK,
        provider_tenant_id="ding-tenant-test",
        entries=(DirectoryEntry("user-1", "Example User", None, None),),
    )
    assert retry_sleeps == [0.25, 0.25]
    adapter.close()


def test_dingtalk_directory_fails_after_bounded_rate_limit_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    department_probe_calls = 0
    retry_sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal department_probe_calls
        if _is_token_request(request):
            return _token_response()
        request_body = json.loads(request.content)
        if request.url.path == "/topapi/v2/user/list" and request_body["size"] == 1:
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
            )
        department_probe_calls += 1
        if department_probe_calls == 1:
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        return httpx.Response(
            429,
            headers={"retry-after": "invalid"},
            json={"errcode": 88, "errmsg": "rate limited"},
        )

    _install_http_client(monkeypatch, handler, [])
    monkeypatch.setattr(dingtalk_provider.time, "sleep", retry_sleeps.append)
    adapter = DingTalkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    assert department_probe_calls == 5
    assert retry_sleeps == [0.1, 0.1, 0.1]
    adapter.close()


@pytest.mark.parametrize("rate_limited_path", ["department", "user"])
def test_dingtalk_directory_retries_legacy_200_rate_limit_without_publishing_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    rate_limited_path: str,
) -> None:
    department_calls = 0
    rate_limited_calls = 0
    retry_sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal department_calls, rate_limited_calls
        if _is_token_request(request):
            return _token_response()
        request_body = json.loads(request.content)
        if request.url.path == "/topapi/v2/department/listsub":
            department_calls += 1
            if department_calls == 1:
                return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
            if department_calls == 2:
                return httpx.Response(
                    200,
                    json={"errcode": 0, "errmsg": "ok", "result": [{"dept_id": 2}]},
                )
            if rate_limited_path == "department":
                rate_limited_calls += 1
                return httpx.Response(200, json={"errcode": 88, "errmsg": "rate limited"})
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": []})
        assert request.url.path == "/topapi/v2/user/list"
        if request_body["size"] == 1:
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "result": {"list": [], "has_more": False}},
            )
        if request_body["dept_id"] == 1:
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "result": {
                        "list": [{"userid": "user-partial", "name": "Partial User"}],
                        "has_more": False,
                    },
                },
            )
        rate_limited_calls += 1
        return httpx.Response(200, json={"errcode": 88, "errmsg": "rate limited"})

    _install_http_client(monkeypatch, handler, [])
    monkeypatch.setattr(dingtalk_provider.time, "sleep", retry_sleeps.append)
    adapter = DingTalkAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    assert rate_limited_calls == 4
    assert retry_sleeps == [0.1, 0.1, 0.1]
    adapter.close()


@pytest.mark.parametrize(
    ("destination_response", "expected_code"),
    [
        pytest.param(
            httpx.Response(429, json={"code": "TooManyRequests"}),
            OperationFailureCode.RATE_LIMITED,
            id="rate-limited",
        ),
        pytest.param(
            httpx.Response(503, json={"code": "ServiceUnavailable"}),
            OperationFailureCode.PROVIDER,
            id="server-error",
        ),
        pytest.param(
            httpx.Response(200, content=b"not-json"),
            OperationFailureCode.PROVIDER,
            id="malformed",
        ),
        pytest.param(
            httpx.Response(200, json={}),
            OperationFailureCode.PROVIDER,
            id="incomplete",
        ),
        pytest.param(
            httpx.Response(403, json={"errcode": 60011, "errmsg": "forbidden"}),
            OperationFailureCode.MISSING_PERMISSION,
            id="no-access",
        ),
        pytest.param(
            httpx.Response(
                200,
                json={
                    "errcode": 88,
                    "errmsg": "permission denied",
                    "sub_code": "60011",
                },
            ),
            OperationFailureCode.MISSING_PERMISSION,
            id="nested-no-access",
        ),
        pytest.param(
            httpx.Response(404, json={"errcode": 60121, "errmsg": "not found"}),
            OperationFailureCode.DESTINATION_UNREACHABLE,
            id="not-found",
        ),
        pytest.param(
            httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "result": {"userid": "other", "name": "Other"}}),
            OperationFailureCode.DESTINATION_UNREACHABLE,
            id="mismatch",
        ),
    ],
)
def test_dingtalk_destination_failures_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    destination_response: httpx.Response,
    expected_code: OperationFailureCode,
) -> None:
    _install_http_client(
        monkeypatch,
        lambda request: _token_response() if _is_token_request(request) else destination_response,
        [],
    )
    adapter = DingTalkAdapter(_config())

    result = adapter.messaging.test_destination(DingTalkUserDestination("user-test"))

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    adapter.close()


def test_dingtalk_destination_network_failure_is_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            return _token_response()
        raise httpx.ReadTimeout("timed out", request=request)

    _install_http_client(monkeypatch, handler, [])
    adapter = DingTalkAdapter(_config())

    result = adapter.messaging.test_destination(DingTalkUserDestination("user-test"))

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER
    adapter.close()


@pytest.mark.parametrize(
    ("send_response", "expected_code"),
    [
        pytest.param(
            httpx.Response(429, json={"code": "TooManyRequests"}), OperationFailureCode.RATE_LIMITED, id="rate-limited"
        ),
        pytest.param(httpx.Response(200, content=b"not-json"), OperationFailureCode.AMBIGUOUS, id="malformed"),
        pytest.param(
            httpx.Response(500, json={"processQueryKey": "process-key"}), OperationFailureCode.PROVIDER, id="rejected"
        ),
        pytest.param(
            httpx.Response(200, json={"processQueryKey": " "}), OperationFailureCode.AMBIGUOUS, id="missing-reference"
        ),
    ],
)
def test_dingtalk_send_failures_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    send_response: httpx.Response,
    expected_code: OperationFailureCode,
) -> None:
    _install_http_client(
        monkeypatch,
        lambda request: _token_response() if _is_token_request(request) else send_response,
        [],
    )
    adapter = DingTalkAdapter(_config())

    result = adapter.messaging.send_text(
        DingTalkUserDestination("user-test"),
        "Example",
    )

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    adapter.close()
