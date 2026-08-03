"""WeCom adapter tests at official qyapi.weixin.qq.com boundaries."""

from __future__ import annotations

import json

import httpx
import pytest

from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    CredentialTestSuccess,
    DirectoryEntry,
    DirectorySnapshot,
    MessageAccepted,
    OperationFailure,
    OperationFailureCode,
    PermissionFact,
    WeComAdapter,
    WeComAdapterConfig,
    WeComMessageReference,
    WeComUserDestination,
)
from core.human_input_v2.im_provider.providers import wecom as wecom_provider


def _config() -> WeComAdapterConfig:
    return WeComAdapterConfig(
        corp_id="ww-corp-test",
        agent_id="1000005",
        corp_secret="secret-test",
    )


def _install_http_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransportHandler,
    client_options: list[dict[str, object]],
) -> None:
    def create_client(**kwargs: object) -> httpx.Client:
        client_options.append(kwargs)
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(wecom_provider, "_build_http_client", create_client)


def _token_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "errcode": 0,
            "errmsg": "ok",
            "access_token": "access-token",
            "expires_in": 7200,
        },
    )


def _agent_response(
    *,
    user_ids: tuple[str, ...] = ("user-visible",),
    department_ids: tuple[int, ...] = (1,),
    tag_ids: tuple[int, ...] = (),
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "errcode": 0,
            "errmsg": "ok",
            "agentid": 1000005,
            "allow_userinfos": {"user": [{"userid": user_id} for user_id in user_ids]},
            "allow_partys": {"partyid": list(department_ids)},
            "allow_tags": {"tagid": list(tag_ids)},
            "close": 0,
        },
    )


def _is_token_request(request: httpx.Request) -> bool:
    return request.url.path == "/cgi-bin/gettoken"


def test_wecom_credentials_use_official_gettoken_and_bound_agent_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    client_options: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/agent/get":
            return _agent_response(department_ids=(), tag_ids=())
        if request.url.path == "/cgi-bin/user/get":
            assert dict(request.url.params) == {
                "access_token": "access-token",
                "userid": "user-visible",
            }
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "userid": "user-visible",
                    "name": "Visible User",
                    "status": 1,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, client_options)
    adapter = WeComAdapter(_config())

    result = adapter.test_credentials()

    assert result == CredentialTestSuccess(
        provider=IMProvider.WE_COM,
        provider_tenant_id="ww-corp-test",
        permissions=(PermissionFact("agent.visibility.read", True),),
    )
    assert len(requests) == 2
    assert requests[0].method == "GET"
    assert requests[0].url.host == "qyapi.weixin.qq.com"
    assert requests[0].url.path == "/cgi-bin/gettoken"
    assert dict(requests[0].url.params) == {
        "corpid": "ww-corp-test",
        "corpsecret": "secret-test",
    }
    assert requests[1].method == "GET"
    assert requests[1].url.path == "/cgi-bin/agent/get"
    assert dict(requests[1].url.params) == {
        "access_token": "access-token",
        "agentid": "1000005",
    }
    assert client_options == [{"verify": True, "timeout": 10.0}]
    assert "secret-test" not in repr(result)
    adapter.close()


def test_wecom_directory_reads_every_visible_department_and_preserves_missing_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/agent/get":
            return _agent_response(user_ids=(), department_ids=(1,))
        if request.url.path == "/cgi-bin/department/list":
            assert dict(request.url.params) == {"access_token": "access-token", "id": "1"}
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "department": [
                        {"id": 1, "name": "Root", "parentid": 0, "order": 1},
                        {"id": 2, "name": "Engineering", "parentid": 1, "order": 2},
                    ],
                },
            )
        if request.url.path == "/cgi-bin/user/list":
            department_id = request.url.params["department_id"]
            assert dict(request.url.params) == {
                "access_token": "access-token",
                "department_id": department_id,
            }
            users = {
                "1": [
                    {
                        "userid": "user-1",
                        "name": "Ada",
                        "department": [1],
                        "email": "ada@example.com",
                        "status": 1,
                    }
                ],
                "2": [
                    {
                        "userid": "user-2",
                        "name": "Lin",
                        "department": [2],
                        "status": 4,
                    },
                    {
                        "userid": "user-1",
                        "name": "Duplicate",
                        "department": [1, 2],
                        "status": 1,
                    },
                ],
            }[department_id]
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "userlist": users})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.WE_COM,
        provider_tenant_id="ww-corp-test",
        entries=(
            DirectoryEntry("user-1", "Ada", "ada@example.com", True),
            DirectoryEntry("user-2", "Lin", None, False),
        ),
    )
    assert [request.url.path for request in requests] == [
        "/cgi-bin/gettoken",
        "/cgi-bin/agent/get",
        "/cgi-bin/department/list",
        "/cgi-bin/user/list",
        "/cgi-bin/user/list",
    ]
    adapter.close()


def test_wecom_directory_builds_a_fresh_complete_snapshot_for_every_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal agent_calls
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/agent/get":
            agent_calls += 1
            user_id = "user-first" if agent_calls == 1 else "user-second"
            return _agent_response(user_ids=(user_id,), department_ids=())
        if request.url.path == "/cgi-bin/user/get":
            user_id = request.url.params["userid"]
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "userid": user_id,
                    "name": "First User" if user_id == "user-first" else "Second User",
                    "status": 1,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    first_snapshot = adapter.directory.read_snapshot()
    second_snapshot = adapter.directory.read_snapshot()

    assert first_snapshot == DirectorySnapshot(
        IMProvider.WE_COM,
        "ww-corp-test",
        (DirectoryEntry("user-first", "First User", None, True),),
    )
    assert second_snapshot == DirectorySnapshot(
        IMProvider.WE_COM,
        "ww-corp-test",
        (DirectoryEntry("user-second", "Second User", None, True),),
    )
    adapter.close()


def test_wecom_directory_completes_explicit_department_and_tag_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/agent/get":
            return _agent_response(user_ids=(), department_ids=(2,), tag_ids=(7,))
        if request.url.path == "/cgi-bin/department/list":
            assert dict(request.url.params) == {"access_token": "access-token", "id": "2"}
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "department": [{"id": 2, "name": "Engineering", "parentid": 1, "order": 1}],
                },
            )
        if request.url.path == "/cgi-bin/user/list":
            assert dict(request.url.params) == {"access_token": "access-token", "department_id": "2"}
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "userlist": [
                        {
                            "userid": "user-department",
                            "name": "Department User",
                            "department": [2],
                            "email": "department@example.com",
                            "status": 1,
                        }
                    ],
                },
            )
        if request.url.path == "/cgi-bin/tag/get":
            assert dict(request.url.params) == {"access_token": "access-token", "tagid": "7"}
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "tagname": "Reviewers",
                    "userlist": [{"userid": "user-tag", "name": "Tag User"}],
                    "partylist": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        provider=IMProvider.WE_COM,
        provider_tenant_id="ww-corp-test",
        entries=(
            DirectoryEntry("user-department", "Department User", "department@example.com", True),
            DirectoryEntry("user-tag", "Tag User", None, None),
        ),
    )
    assert [request.url.path for request in requests] == [
        "/cgi-bin/gettoken",
        "/cgi-bin/agent/get",
        "/cgi-bin/department/list",
        "/cgi-bin/user/list",
        "/cgi-bin/tag/get",
    ]
    adapter.close()


def test_wecom_directory_merges_optional_facts_without_replacing_first_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/agent/get":
            return _agent_response(user_ids=(), department_ids=(), tag_ids=(7,))
        if request.url.path == "/cgi-bin/tag/get":
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "tagname": "Reviewers",
                    "userlist": [{"userid": "user-shared", "name": "Tag Display Name"}],
                    "partylist": [3],
                },
            )
        if request.url.path == "/cgi-bin/department/list":
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "department": [{"id": 3, "name": "Review", "parentid": 1, "order": 1}],
                },
            )
        if request.url.path == "/cgi-bin/user/list":
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "userlist": [
                        {
                            "userid": "user-shared",
                            "name": "Department Display Name",
                            "department": [3],
                            "email": "shared@example.com",
                            "status": 4,
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(
        IMProvider.WE_COM,
        "ww-corp-test",
        (DirectoryEntry("user-shared", "Tag Display Name", "shared@example.com", False),),
    )
    adapter.close()


def test_wecom_directory_retries_one_rate_limited_read_only_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    department_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal department_calls
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/agent/get":
            return _agent_response(user_ids=(), department_ids=(1,))
        if request.url.path == "/cgi-bin/department/list":
            department_calls += 1
            if department_calls == 1:
                return httpx.Response(429, headers={"retry-after": "0"})
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "department": [{"id": 1, "name": "Root", "parentid": 0, "order": 1}],
                },
            )
        if request.url.path == "/cgi-bin/user/list":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "userlist": []})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert result == DirectorySnapshot(IMProvider.WE_COM, "ww-corp-test", ())
    assert department_calls == 2
    adapter.close()


def test_wecom_directory_late_failure_never_returns_a_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/agent/get":
            return _agent_response(user_ids=(), department_ids=(1,))
        if request.url.path == "/cgi-bin/department/list":
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "department": [
                        {"id": 1, "name": "Root", "parentid": 0, "order": 1},
                        {"id": 2, "name": "Engineering", "parentid": 1, "order": 2},
                    ],
                },
            )
        if request.url.path == "/cgi-bin/user/list" and request.url.params["department_id"] == "1":
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "userlist": [{"userid": "user-partial", "name": "Partial", "department": [1], "status": 1}],
                },
            )
        if request.url.path == "/cgi-bin/user/list":
            raise httpx.ReadTimeout("timed out", request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    adapter.close()


def test_wecom_destination_check_is_read_only_and_bound_to_one_exact_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/user/get":
            user_id = request.url.params["userid"]
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "userid": user_id if user_id == "user-visible" else "different-user",
                    "name": "Destination User",
                    "status": 1,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    visible = adapter.messaging.test_destination(WeComUserDestination("user-visible"))
    invisible = adapter.messaging.test_destination(WeComUserDestination("user-outside-scope"))

    assert visible is None
    assert isinstance(invisible, OperationFailure)
    assert invisible.code is OperationFailureCode.DESTINATION_UNREACHABLE
    assert all(request.url.path != "/cgi-bin/message/send" for request in requests)
    assert [request.url.path for request in requests] == [
        "/cgi-bin/gettoken",
        "/cgi-bin/user/get",
        "/cgi-bin/user/get",
    ]
    adapter.close()


def test_wecom_send_text_uses_one_official_application_message_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/message/send":
            assert request.method == "POST"
            assert dict(request.url.params) == {"access_token": "access-token"}
            assert json.loads(request.content) == {
                "touser": "user-visible",
                "msgtype": "text",
                "agentid": 1000005,
                "text": {"content": "Hello from Dify"},
            }
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "errmsg": "ok",
                    "invaliduser": "",
                    "invalidparty": "",
                    "invalidtag": "",
                    "msgid": "message-1",
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.messaging.send_text(
        WeComUserDestination("user-visible"),
        "Hello from Dify",
    )

    assert result == MessageAccepted(WeComMessageReference("message-1"), None)
    assert [request.url.path for request in requests] == [
        "/cgi-bin/gettoken",
        "/cgi-bin/message/send",
    ]
    adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("token-network", OperationFailureCode.PROVIDER),
        ("token-rate-limit", OperationFailureCode.RATE_LIMITED),
        ("token-malformed", OperationFailureCode.PROVIDER),
        ("token-http-error", OperationFailureCode.PROVIDER),
        ("token-rejection", OperationFailureCode.AUTHENTICATION),
        ("token-blank", OperationFailureCode.PROVIDER),
        ("token-expiry", OperationFailureCode.PROVIDER),
        ("agent-network", OperationFailureCode.PROVIDER),
        ("agent-rate-limit", OperationFailureCode.RATE_LIMITED),
        ("agent-malformed", OperationFailureCode.PROVIDER),
        ("agent-blank-user", OperationFailureCode.PROVIDER),
        ("agent-authentication", OperationFailureCode.AUTHENTICATION),
        ("agent-permission", OperationFailureCode.MISSING_PERMISSION),
        ("agent-rejection", OperationFailureCode.PROVIDER),
        ("agent-mismatch", OperationFailureCode.AUTHENTICATION),
        ("agent-disabled", OperationFailureCode.MISSING_PERMISSION),
    ],
)
def test_wecom_credentials_translate_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            if failure_kind == "token-network":
                raise httpx.ReadTimeout("timed out", request=request)
            if failure_kind == "token-rate-limit":
                return httpx.Response(429)
            if failure_kind == "token-malformed":
                return httpx.Response(200, content=b"not-json")
            if failure_kind == "token-http-error":
                response = _token_response()
                return httpx.Response(500, content=response.content)
            if failure_kind == "token-rejection":
                return httpx.Response(200, json={"errcode": 40013, "errmsg": "invalid corp"})
            if failure_kind == "token-blank":
                return httpx.Response(
                    200,
                    json={"errcode": 0, "errmsg": "ok", "access_token": " ", "expires_in": 7200},
                )
            if failure_kind == "token-expiry":
                return httpx.Response(
                    200,
                    json={"errcode": 0, "errmsg": "ok", "access_token": "token", "expires_in": 0},
                )
            return _token_response()
        if failure_kind == "agent-network":
            raise httpx.ReadTimeout("timed out", request=request)
        if failure_kind == "agent-rate-limit":
            return httpx.Response(429)
        if failure_kind == "agent-malformed":
            return httpx.Response(200, content=b"not-json")
        response = {
            "errcode": 0,
            "errmsg": "ok",
            "agentid": 1000005,
            "allow_userinfos": {"user": []},
            "allow_partys": {"partyid": []},
            "allow_tags": {"tagid": []},
            "close": 0,
        }
        if failure_kind == "agent-blank-user":
            response["allow_userinfos"] = {"user": [{"userid": " "}]}
        elif failure_kind == "agent-authentication":
            response["errcode"] = 40014
        elif failure_kind == "agent-permission":
            response["errcode"] = 60011
        elif failure_kind == "agent-rejection":
            response["errcode"] = 50001
        elif failure_kind == "agent-mismatch":
            response["agentid"] = 999
        elif failure_kind == "agent-disabled":
            response["close"] = 1
        return httpx.Response(200, json=response)

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.test_credentials()

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    adapter.close()


@pytest.mark.parametrize(
    "failure_stage",
    [
        "explicit-user",
        "explicit-rejected",
        "department",
        "user-list",
        "tag",
        "tag-department",
        "tag-user",
        "network",
    ],
)
def test_wecom_directory_translates_each_incomplete_traversal_stage(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/agent/get":
            return _agent_response(
                user_ids=("user-visible",)
                if failure_stage in {"explicit-user", "explicit-rejected", "network"}
                else (),
                department_ids=(2,) if failure_stage in {"department", "user-list"} else (),
                tag_ids=(7,) if failure_stage in {"tag", "tag-department", "tag-user"} else (),
            )
        if failure_stage == "network":
            raise httpx.ReadTimeout("timed out", request=request)
        if request.url.path == "/cgi-bin/user/get":
            if failure_stage == "explicit-rejected":
                return httpx.Response(
                    200,
                    json={
                        "errcode": 50001,
                        "errmsg": "rejected",
                        "userid": "user-visible",
                        "name": "Visible User",
                        "status": 1,
                    },
                )
            return httpx.Response(200, content=b"not-json")
        if request.url.path == "/cgi-bin/department/list":
            if failure_stage in {"department", "tag-department"}:
                return httpx.Response(200, content=b"not-json")
            department_id = int(request.url.params["id"])
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "department": [{"id": department_id}]},
            )
        if request.url.path == "/cgi-bin/user/list":
            return httpx.Response(200, content=b"not-json")
        if request.url.path == "/cgi-bin/tag/get":
            if failure_stage in {"tag-department", "tag-user"}:
                return httpx.Response(
                    200,
                    json={"errcode": 0, "errmsg": "ok", "userlist": [], "partylist": [3]},
                )
            return httpx.Response(200, content=b"not-json")
        raise AssertionError(request.url.path)

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    adapter.close()


def test_wecom_directory_propagates_bound_credential_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.PROVIDER
    adapter.close()


@pytest.mark.parametrize(
    ("retry_after", "expected_calls"),
    [("invalid", 4), ("-1", 2), ("nan", 2)],
)
def test_wecom_directory_normalizes_retry_after_and_bounds_retries(
    monkeypatch: pytest.MonkeyPatch,
    retry_after: str,
    expected_calls: int,
) -> None:
    department_calls = 0
    retry_sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal department_calls
        if _is_token_request(request):
            return _token_response()
        if request.url.path == "/cgi-bin/agent/get":
            return _agent_response(user_ids=(), department_ids=(2,))
        department_calls += 1
        if retry_after == "invalid" or department_calls == 1:
            return httpx.Response(429, headers={"retry-after": retry_after})
        return httpx.Response(200, content=b"not-json")

    _install_http_client(monkeypatch, handler, [])
    monkeypatch.setattr(wecom_provider.time, "sleep", retry_sleeps.append)
    adapter = WeComAdapter(_config())

    result = adapter.directory.read_snapshot()

    assert isinstance(result, OperationFailure)
    assert result.code is OperationFailureCode.DIRECTORY_INCOMPLETE
    assert department_calls == expected_calls
    assert retry_sleeps == [0.1] * (expected_calls - 1)
    adapter.close()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("network", OperationFailureCode.AMBIGUOUS),
        ("rate-limit", OperationFailureCode.RATE_LIMITED),
        ("malformed", OperationFailureCode.AMBIGUOUS),
        ("rejection", OperationFailureCode.PROVIDER),
        ("invalid-user", OperationFailureCode.AMBIGUOUS),
        ("missing-reference", OperationFailureCode.AMBIGUOUS),
    ],
)
def test_wecom_message_failure_is_typed_and_never_retried(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_code: OperationFailureCode,
) -> None:
    message_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal message_calls
        if _is_token_request(request):
            return _token_response()
        message_calls += 1
        if failure_kind == "network":
            raise httpx.ReadTimeout("timed out", request=request)
        if failure_kind == "rate-limit":
            return httpx.Response(429)
        if failure_kind == "malformed":
            return httpx.Response(200, content=b"not-json")
        response = {
            "errcode": 0,
            "errmsg": "ok",
            "invaliduser": "",
            "invalidparty": "",
            "invalidtag": "",
            "msgid": "message-1",
        }
        if failure_kind == "rejection":
            response["errcode"] = 50001
        elif failure_kind == "invalid-user":
            response["invaliduser"] = "user-visible"
        elif failure_kind == "missing-reference":
            response["msgid"] = " "
        return httpx.Response(200, json=response)

    _install_http_client(monkeypatch, handler, [])
    adapter = WeComAdapter(_config())

    result = adapter.messaging.send_text(WeComUserDestination("user-visible"), "Hello")

    assert isinstance(result, OperationFailure)
    assert result.code is expected_code
    assert message_calls == 1
    adapter.close()
