import json
import types
from unittest.mock import patch

import pytest
from werkzeug.exceptions import BadRequest

import controllers.trigger.human_input_im as module


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
    binding = types.SimpleNamespace(id="binding-1")

    with (
        patch("controllers.trigger.human_input_im.HumanInputIMCallbackService.complete_binding", return_value=binding),
        patch("controllers.trigger.human_input_im.db.session.commit") as commit_mock,
    ):
        response, status = module.handle_im_binding_completion("feishu")

    assert status == 202
    assert response["result"] == "accepted"
    assert response["binding_id"] == "binding-1"
    commit_mock.assert_called_once()


def test_handle_im_binding_completion_rejects_invalid_provider():
    with pytest.raises(BadRequest):
        module.handle_im_binding_completion("unknown")
