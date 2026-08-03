"""RED contract for personal-user-only IM messaging destinations."""

from __future__ import annotations

import inspect
from dataclasses import fields, is_dataclass

import pytest

from core.human_input_v2 import im_provider
from core.human_input_v2.im_provider.providers import dingtalk, feishu_lark, microsoft_teams, slack, wecom


@pytest.mark.parametrize(
    ("obsolete_type_name", "personal_type_name", "expected_fields"),
    [
        ("SlackChannelDestination", "SlackUserDestination", {"user_id"}),
        (
            "FeishuChatDestination",
            "FeishuUserDestination",
            {"receive_id", "receive_id_type"},
        ),
        (
            "DingTalkConversationDestination",
            "DingTalkUserDestination",
            {"user_id"},
        ),
        ("WeComRecipientDestination", "WeComUserDestination", {"user_id"}),
        (
            "TeamsConversationDestination",
            "TeamsPersonalConversationDestination",
            {"service_url", "conversation_id", "user_id"},
        ),
    ],
)
def test_public_messaging_destinations_expose_only_one_personal_user(
    obsolete_type_name: str,
    personal_type_name: str,
    expected_fields: set[str],
) -> None:
    assert not hasattr(im_provider, obsolete_type_name)
    personal_type = getattr(im_provider, personal_type_name, None)
    assert personal_type is not None
    assert is_dataclass(personal_type)
    assert {field.name for field in fields(personal_type)} == expected_fields


def test_slack_personal_destination_uses_user_lookup_and_direct_post() -> None:
    destination_source = inspect.getsource(slack._SlackProviderClient.test_destination)
    send_source = inspect.getsource(slack._SlackProviderClient.send_text)

    assert "conversations.info" not in destination_source
    assert "users.info" in destination_source
    assert "destination.user_id" in destination_source
    assert '"chat.postMessage"' in send_source
    assert "destination.user_id" in send_source
    assert "thread_timestamp" not in send_source
    assert "response_reference" in inspect.getsource(slack._SlackProviderClient._send_message)


def test_feishu_destination_supports_only_personal_receive_id_types() -> None:
    assert frozenset({"open_id", "user_id", "union_id", "email"}) == feishu_lark._SUPPORTED_RECEIVE_ID_TYPES
    destination_source = inspect.getsource(feishu_lark._FeishuLarkProviderClient.test_destination)
    assert 'receive_id_type == "chat_id"' not in destination_source
    assert "/im/v1/chats/" not in destination_source


def test_dingtalk_personal_destination_uses_user_lookup() -> None:
    destination_source = inspect.getsource(dingtalk._DingTalkProviderClient.test_destination)

    assert "/v1.0/im/sceneGroups/query" not in destination_source
    assert "/topapi/v2/user/get" in destination_source
    assert "destination.user_id" in destination_source


def test_dingtalk_personal_send_uses_bound_robot_code_and_o2o_endpoint() -> None:
    send_source = inspect.getsource(dingtalk._DingTalkProviderClient.send_text)

    assert "/v1.0/robot/groupMessages/send" not in send_source
    assert "/v1.0/robot/oToMessages/batchSend" in send_source
    assert '"robotCode": self._config.client_id' in send_source
    assert '"userIds": [destination.user_id]' in send_source
    assert "openConversationId" not in send_source


def test_wecom_personal_send_has_one_touser_and_no_broadcast_fields() -> None:
    send_source = inspect.getsource(wecom._WeComProviderClient.send_text)

    assert 'request_body["touser"] = destination.user_id' in send_source
    assert "toparty" not in send_source
    assert "totag" not in send_source
    assert "department_ids" not in send_source
    assert "tag_ids" not in send_source


def test_wecom_personal_destination_uses_exact_user_lookup() -> None:
    destination_source = inspect.getsource(wecom._WeComProviderClient.test_destination)

    assert "/user/get" in destination_source
    assert "destination.user_id" in destination_source
    assert "_resolve_visibility" not in destination_source


def test_teams_destination_validation_is_bound_to_the_personal_user() -> None:
    destination_source = inspect.getsource(microsoft_teams._MicrosoftTeamsProviderClient.test_destination)

    assert "destination.user_id" in destination_source
    assert "/members/{user_path_segment}" in destination_source
    assert '/members"' not in destination_source
