from inspect import unwrap
import importlib

from flask import Flask

from controllers.console.workspace.im_bindings import AccountIMBindingApi, AccountIMBindingSessionApi
from models.im_integration import IMBindingStatus, IMInstallMode, IMProvider, IMScopeType
from services.entities.im_binding_entities import IMBindingRecord, IMBindingSessionRecord
from services.human_input_im.app_config_service import (
    IMAppConfigStatus,
    IMAppContext,
    IMEventMode,
    IMTokenStatus,
)


class TestAccountIMBindingApi:
    def test_get_success(self, app: Flask):
        api = AccountIMBindingApi()
        method = unwrap(api.get)
        binding = IMBindingRecord(
            id="binding-1",
            account_id="account-1",
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            provider_workspace_id="ws-1",
            provider_user_id="user-1",
            provider_union_id=None,
            provider_user_display_name="User 1",
            provider_user_avatar_url=None,
            status=IMBindingStatus.ACTIVE,
        )
        current_user = type("User", (), {"id": "account-1"})()

        from unittest.mock import patch

        with patch("controllers.console.workspace.im_bindings.get_active_binding", return_value=binding):
            result, status = method(api, current_user)

        assert status == 200
        assert result["data"]["id"] == "binding-1"
        assert result["data"]["provider_user_display_name"] == "User 1"

    def test_delete_success(self, app: Flask):
        api = AccountIMBindingApi()
        method = unwrap(api.delete)
        current_user = type("User", (), {"id": "account-1"})()

        from unittest.mock import patch

        with (
            patch("controllers.console.workspace.im_bindings.revoke_active_binding") as revoke_mock,
            patch("controllers.console.workspace.im_bindings.db.session.commit") as commit_mock,
        ):
            result, status = method(api, current_user)

        assert status == 200
        assert result["result"] == "success"
        revoke_mock.assert_called_once_with(session=__import__("controllers.console.workspace.im_bindings", fromlist=["db"]).db.session, account_id="account-1")
        commit_mock.assert_called_once()


class TestAccountIMBindingSessionApi:
    def test_post_success(self, app: Flask):
        api = AccountIMBindingSessionApi()
        method = unwrap(api.post)
        payload = {"provider": "feishu"}
        current_user = type("User", (), {"id": "account-1"})()
        app_context = IMAppContext(
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            status=IMAppConfigStatus.CONFIGURED,
            token_status=IMTokenStatus.NOT_APPLICABLE,
            event_mode=IMEventMode.LONG_CONNECTION,
            app_id="cli_a",
            app_secret_configured=True,
            errors=[],
        )
        binding_session = IMBindingSessionRecord(
            id="session-1",
            account_id="account-1",
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            token="imbs_x",
            status=__import__("models.im_integration", fromlist=["IMBindingSessionStatus"]).IMBindingSessionStatus.PENDING,
            expires_at=__import__("libs.datetime_utils", fromlist=["naive_utc_now"]).naive_utc_now(),
        )

        from unittest.mock import PropertyMock, patch
        module = importlib.import_module("controllers.console.workspace.im_bindings")

        with (
            app.test_request_context("/", json=payload),
            patch.object(type(module.console_ns), "payload", new_callable=PropertyMock, return_value=payload),
            patch("controllers.console.workspace.im_bindings.resolve_im_app_context", return_value=app_context),
            patch("controllers.console.workspace.im_bindings.create_binding_session", return_value=binding_session),
            patch("controllers.console.workspace.im_bindings.db.session.commit") as commit_mock,
        ):
            result, status = method(api, current_user, "tenant-1")

        assert status == 201
        assert result["id"] == "session-1"
        commit_mock.assert_called_once()
