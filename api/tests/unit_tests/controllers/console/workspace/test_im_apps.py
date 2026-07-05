from inspect import unwrap

from flask import Flask
import pytest
from werkzeug.exceptions import BadRequest

from controllers.console.workspace.im_apps import WorkspaceIMAppApi
from services.human_input_im.app_config_service import (
    IMAppConfigStatus,
    IMAppContext,
    IMEventMode,
    IMInstallMode,
    IMProvider,
    IMScopeType,
    IMTokenStatus,
)


class TestWorkspaceIMAppApi:
    def test_get_success(self, app: Flask):
        api = WorkspaceIMAppApi()
        method = unwrap(api.get)
        context = IMAppContext(
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

        from unittest.mock import patch

        with patch("controllers.console.workspace.im_apps.resolve_im_app_context", return_value=context) as resolve_mock:
            result, status = method(api, "tenant-1", "feishu")

        assert status == 200
        assert result["provider"] == "feishu"
        assert result["status"] == "configured"
        assert result["app_id_configured"] is True
        resolve_mock.assert_called_once_with(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    def test_get_serializes_missing_context(self, app: Flask):
        api = WorkspaceIMAppApi()
        method = unwrap(api.get)
        context = IMAppContext(
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            status=IMAppConfigStatus.MISSING,
            token_status=IMTokenStatus.NOT_APPLICABLE,
            event_mode=None,
            app_id=None,
            app_secret_configured=False,
            errors=["missing LARK_APP_SECRET"],
        )

        from unittest.mock import patch

        with patch("controllers.console.workspace.im_apps.resolve_im_app_context", return_value=context):
            result, status = method(api, "tenant-1", "feishu")

        assert status == 200
        assert result["status"] == "missing"
        assert result["token_status"] == "not_applicable"
        assert result["event_mode"] is None
        assert result["app_id_configured"] is False
        assert result["app_secret_configured"] is False
        assert result["errors"] == ["missing LARK_APP_SECRET"]

    def test_get_serializes_invalid_context(self, app: Flask):
        api = WorkspaceIMAppApi()
        method = unwrap(api.get)
        context = IMAppContext(
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            status=IMAppConfigStatus.INVALID,
            token_status=IMTokenStatus.NOT_APPLICABLE,
            event_mode=IMEventMode.WEBHOOK,
            app_id="cli_a",
            app_secret_configured=True,
            errors=["phase-1 demo requires LARK_EVENT_MODE=long_connection"],
        )

        from unittest.mock import patch

        with patch("controllers.console.workspace.im_apps.resolve_im_app_context", return_value=context):
            result, status = method(api, "tenant-1", "feishu")

        assert status == 200
        assert result["status"] == "invalid"
        assert result["event_mode"] == "webhook"
        assert result["app_id_configured"] is True
        assert result["app_secret_configured"] is True
        assert result["errors"] == ["phase-1 demo requires LARK_EVENT_MODE=long_connection"]

    def test_get_invalid_provider_returns_400(self, app: Flask):
        api = WorkspaceIMAppApi()
        method = unwrap(api.get)

        with pytest.raises(BadRequest):
            method(api, "tenant-1", "unknown-provider")
