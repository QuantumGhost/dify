from unittest.mock import patch

import pytest

import controllers.trigger.human_input_im as module


@pytest.fixture(autouse=True)
def mock_request():
    module.request = type(
        "_Request",
        (),
        {
            "headers": {"x-test": "1"},
            "get_data": staticmethod(lambda: b"{}"),
        },
    )()


class TestHandleFeishuHumanInputCallback:
    @patch.object(module, "FeishuIngressService")
    def test_success(self, mock_service):
        mock_service.return_value.handle_webhook_request.return_value = (200, b'{"ok": true}')

        response = module.handle_feishu_human_input_callback()

        assert response.status_code == 200
        assert response.get_data() == b'{"ok": true}'

    @patch.object(module, "FeishuIngressService", side_effect=Exception("boom"))
    def test_internal_error(self, mock_service):
        response, status = module.handle_feishu_human_input_callback()

        assert status == 500
        assert response.json["error"] == "Internal server error"
