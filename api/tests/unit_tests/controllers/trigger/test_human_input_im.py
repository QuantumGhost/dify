import json
import types
from unittest.mock import patch

import pytest
from werkzeug.exceptions import BadRequest

import controllers.trigger.human_input_im as module
from models.im_integration import IMBindingStatus, IMInstallMode, IMProvider, IMScopeType
from services.entities.im_binding_entities import IMBindingRecord
from services.human_input_im.callback_service import IMBindingCompletionResult


@pytest.fixture(autouse=True)
def mock_request():
    module.request = types.SimpleNamespace(
        get_data=lambda: json.dumps(
            {
                "event_id": "event-1",
                "binding_session_token": "imbs_token",
                "provider_workspace_id": "ws-1",
                "provider_user_id": "user-1",
            }
        ).encode(),
    )


@pytest.fixture(autouse=True)
def mock_jsonify():
    module.jsonify = lambda payload: payload


def test_handle_im_binding_completion_success():
    result = IMBindingCompletionResult(
        binding=IMBindingRecord(
            id="binding-1",
            account_id="account-1",
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            provider_workspace_id="ws-1",
            provider_user_id="user-1",
            provider_union_id=None,
            provider_user_display_name=None,
            provider_user_avatar_url=None,
            status=IMBindingStatus.ACTIVE,
        ),
        duplicate_event=False,
        acknowledgement={"result": "accepted", "event_id": "event-1"},
    )

    with (
        patch(
            "controllers.trigger.human_input_im.HumanInputIMService.handle_binding_completion_callback",
            return_value=result,
        ) as handle_mock,
        patch("controllers.trigger.human_input_im.db.session.commit") as commit_mock,
    ):
        response, status = module.handle_im_binding_completion("feishu")

    assert status == 202
    assert response["result"] == "accepted"
    assert response["event_id"] == "event-1"
    assert response["binding_id"] == "binding-1"
    event = handle_mock.call_args.kwargs["event"]
    assert event.provider == IMProvider.FEISHU
    assert event.binding_session_token == "imbs_token"
    assert event.provider_workspace_id == "ws-1"
    assert event.provider_user_id == "user-1"
    commit_mock.assert_called_once()


def test_handle_im_binding_completion_rejects_invalid_provider():
    with pytest.raises(BadRequest):
        module.handle_im_binding_completion("unknown")


def test_handle_im_binding_completion_acknowledges_duplicate_event():
    result = IMBindingCompletionResult(
        binding=None,
        duplicate_event=True,
        acknowledgement={"result": "accepted", "event_id": "event-1"},
    )

    with (
        patch("controllers.trigger.human_input_im.HumanInputIMService.handle_binding_completion_callback", return_value=result),
        patch("controllers.trigger.human_input_im.db.session.commit") as commit_mock,
    ):
        response, status = module.handle_im_binding_completion("feishu")

    assert status == 200
    assert response["result"] == "accepted"
    assert response["event_id"] == "event-1"
    commit_mock.assert_called_once()
