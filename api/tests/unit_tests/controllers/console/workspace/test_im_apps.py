import importlib
from inspect import unwrap

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest, UnprocessableEntity

module = importlib.import_module("controllers.console.workspace.im_apps")
from controllers.console.workspace.im_apps import WorkspaceIMAppApi
from services.entities.im_app_entities import IMAppInstallationRecord, IMSelfBuiltTenantConfigRecord
from services.errors.im_app_config import IMAppConfigValidationError
from services.human_input_im.app_config_service import (
    IMAppConfigStatus,
    IMAppContext,
    IMEventMode,
    IMInstallMode,
    IMInstallStatus,
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
            install_status=IMInstallStatus.NOT_APPLICABLE,
            event_mode=IMEventMode.LONG_CONNECTION,
            app_id="cli_a",
            app_secret_configured=True,
            errors=[],
        )

        from unittest.mock import patch

        with patch(
            "controllers.console.workspace.im_apps.resolve_im_app_context",
            return_value=context,
        ) as resolve_mock:
            result, status = method(api, "tenant-1", "feishu")

        assert status == 200
        assert result["provider"] == "feishu"
        assert result["status"] == "configured"
        assert result["scope_type"] == "deployment"
        assert result["scope_id"] == "deployment"
        assert result["install_status"] == "not_applicable"
        assert result["app_id_configured"] is True
        assert "credential_source" not in result
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
            install_status=IMInstallStatus.NOT_APPLICABLE,
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
            install_status=IMInstallStatus.NOT_APPLICABLE,
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

    def test_get_serializes_tenant_install_status_and_token_status(self, app: Flask):
        api = WorkspaceIMAppApi()
        method = unwrap(api.get)
        context = IMAppContext(
            provider=IMProvider.SLACK,
            install_mode=IMInstallMode.ISV,
            scope_type=IMScopeType.TENANT,
            scope_id="tenant-1",
            status=IMAppConfigStatus.CONFIGURED,
            token_status=IMTokenStatus.VALID,
            install_status=IMInstallStatus.INSTALLED,
            event_mode=None,
            app_id=None,
            app_secret_configured=False,
            errors=[],
        )

        from unittest.mock import patch

        with patch("controllers.console.workspace.im_apps.resolve_im_app_context", return_value=context):
            result, status = method(api, "tenant-1", "slack")

        assert status == 200
        assert result["provider"] == "slack"
        assert result["install_mode"] == "isv"
        assert result["scope_type"] == "tenant"
        assert result["scope_id"] == "tenant-1"
        assert result["install_status"] == "installed"
        assert result["token_status"] == "valid"
        assert result["event_mode"] is None
        assert result["app_id_configured"] is False

    def test_get_serializes_tenant_self_built_context_without_exposing_credentials(self, app: Flask):
        api = WorkspaceIMAppApi()
        method = unwrap(api.get)
        context = IMAppContext(
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.TENANT,
            scope_id="tenant-1",
            status=IMAppConfigStatus.CONFIGURED,
            token_status=IMTokenStatus.NOT_APPLICABLE,
            install_status=IMInstallStatus.NOT_APPLICABLE,
            event_mode=IMEventMode.LONG_CONNECTION,
            app_id="tenant-cli_a",
            app_secret="tenant-secret",
            app_secret_configured=True,
            verification_token="tenant-verification-token",
            encrypt_key="tenant-encrypt-key",
            provider_workspace_id="feishu-workspace-1",
            errors=[],
        )

        from unittest.mock import patch

        with patch("controllers.console.workspace.im_apps.resolve_im_app_context", return_value=context):
            result, status = method(api, "tenant-1", "feishu")

        assert status == 200
        assert result["provider"] == "feishu"
        assert result["install_mode"] == "self_built"
        assert result["scope_type"] == "tenant"
        assert result["scope_id"] == "tenant-1"
        assert result["status"] == "configured"
        assert result["token_status"] == "not_applicable"
        assert result["install_status"] == "not_applicable"
        assert result["event_mode"] == "long_connection"
        assert result["app_id_configured"] is True
        assert result["app_secret_configured"] is True
        assert "app_id" not in result
        assert "app_secret" not in result
        assert "verification_token" not in result
        assert "encrypt_key" not in result
        assert "provider_workspace_id" not in result

    def test_get_invalid_provider_returns_400(self, app: Flask):
        api = WorkspaceIMAppApi()
        method = unwrap(api.get)

        with pytest.raises(BadRequest):
            method(api, "tenant-1", "unknown-provider")

    def test_get_self_built_config_success(self, app: Flask):
        api = module.WorkspaceIMSelfBuiltTenantConfigApi()
        method = unwrap(api.get)
        record = IMSelfBuiltTenantConfigRecord(
            id="cfg-1",
            tenant_id="tenant-1",
            provider=IMProvider.FEISHU,
            scope_type=IMScopeType.TENANT,
            scope_id="tenant-1",
            provider_workspace_id="ws-1",
            app_id="cli_a",
            app_secret_configured=True,
            verification_token_configured=True,
            encrypt_key_configured=False,
            event_mode="long_connection",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )

        from unittest.mock import patch

        with patch(
            "controllers.console.workspace.im_apps.get_tenant_self_built_config",
            return_value=record,
        ) as get_mock:
            result, status = method(api, "tenant-1", "feishu")

        assert status == 200
        assert result["data"]["id"] == "cfg-1"
        assert result["data"]["scope_type"] == "tenant"
        assert result["data"]["app_secret_configured"] is True
        assert "app_secret" not in result["data"]
        get_mock.assert_called_once_with(
            session=module.db.session,
            tenant_id="tenant-1",
            provider=IMProvider.FEISHU,
        )

    def test_put_self_built_config_success(self, app: Flask):
        api = module.WorkspaceIMSelfBuiltTenantConfigApi()
        method = unwrap(api.put)
        payload = {
            "provider_workspace_id": "ws-1",
            "app_id": "cli_a",
            "app_secret": "secret",
            "verification_token": "token",
            "encrypt_key": "encrypt",
            "event_mode": "long_connection",
        }
        record = IMSelfBuiltTenantConfigRecord(
            id="cfg-1",
            tenant_id="tenant-1",
            provider=IMProvider.FEISHU,
            scope_type=IMScopeType.TENANT,
            scope_id="tenant-1",
            provider_workspace_id="ws-1",
            app_id="cli_a",
            app_secret_configured=True,
            verification_token_configured=True,
            encrypt_key_configured=True,
            event_mode="long_connection",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )

        from unittest.mock import PropertyMock, patch

        with (
            app.test_request_context("/", json=payload),
            patch.object(type(module.console_ns), "payload", new_callable=PropertyMock, return_value=payload),
            patch(
                "controllers.console.workspace.im_apps.upsert_tenant_self_built_config",
                return_value=record,
            ) as put_mock,
            patch("controllers.console.workspace.im_apps.db.session.commit") as commit_mock,
        ):
            result, status = method(api, "tenant-1", "feishu")

        assert status == 200
        assert result["id"] == "cfg-1"
        assert result["provider_workspace_id"] == "ws-1"
        put_mock.assert_called_once()
        commit_mock.assert_called_once()

    def test_put_self_built_config_rejects_blank_payload(self, app: Flask):
        api = module.WorkspaceIMSelfBuiltTenantConfigApi()
        method = unwrap(api.put)
        payload = {}

        from unittest.mock import PropertyMock, patch

        with (
            app.test_request_context("/", json=payload),
            patch.object(type(module.console_ns), "payload", new_callable=PropertyMock, return_value=payload),
            patch("controllers.console.workspace.im_apps.db.session.commit") as commit_mock,
        ):
            with pytest.raises(UnprocessableEntity):
                method(api, "tenant-1", "feishu")

        commit_mock.assert_not_called()

    def test_put_self_built_config_rejects_service_validation_error(self, app: Flask):
        api = module.WorkspaceIMSelfBuiltTenantConfigApi()
        method = unwrap(api.put)
        payload = {"app_id": "cli_a"}

        from unittest.mock import PropertyMock, patch

        with (
            app.test_request_context("/", json=payload),
            patch.object(type(module.console_ns), "payload", new_callable=PropertyMock, return_value=payload),
            patch(
                "controllers.console.workspace.im_apps.upsert_tenant_self_built_config",
                side_effect=IMAppConfigValidationError("bad config"),
            ),
            patch("controllers.console.workspace.im_apps.db.session.commit") as commit_mock,
        ):
            with pytest.raises(UnprocessableEntity):
                method(api, "tenant-1", "feishu")

        commit_mock.assert_not_called()

    def test_delete_self_built_config_success(self, app: Flask):
        api = module.WorkspaceIMSelfBuiltTenantConfigApi()
        method = unwrap(api.delete)

        from unittest.mock import patch

        with (
            patch("controllers.console.workspace.im_apps.delete_tenant_self_built_config") as delete_mock,
            patch("controllers.console.workspace.im_apps.db.session.commit") as commit_mock,
        ):
            result, status = method(api, "tenant-1", "feishu")

        assert status == 200
        assert result["result"] == "success"
        delete_mock.assert_called_once_with(
            session=module.db.session,
            tenant_id="tenant-1",
            provider=IMProvider.FEISHU,
        )
        commit_mock.assert_called_once()

    def test_get_installation_success(self, app: Flask):
        api = module.WorkspaceIMAppInstallationApi()
        method = unwrap(api.get)
        record = IMAppInstallationRecord(
            id="inst-1",
            tenant_id="tenant-1",
            provider=IMProvider.SLACK,
            install_mode=IMInstallMode.ISV,
            scope_type=IMScopeType.TENANT,
            scope_id="tenant-1",
            install_status=IMInstallStatus.INSTALLED,
            token_status=IMTokenStatus.VALID,
            provider_workspace_id="team-1",
            access_token_configured=True,
            refresh_token_configured=True,
            access_token_expires_at=None,
            token_refreshed_at=None,
            token_refresh_error=None,
            installed_at=None,
            uninstalled_at=None,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )

        from unittest.mock import patch

        with patch(
            "controllers.console.workspace.im_apps.get_app_installation",
            return_value=record,
        ) as get_mock:
            result, status = method(api, "tenant-1", "slack", "isv")

        assert status == 200
        assert result["data"]["id"] == "inst-1"
        assert result["data"]["provider"] == "slack"
        assert result["data"]["install_mode"] == "isv"
        assert result["data"]["token_status"] == "valid"
        assert result["data"]["access_token_configured"] is True
        assert "encrypted_access_token" not in result["data"]
        get_mock.assert_called_once_with(
            session=module.db.session,
            tenant_id="tenant-1",
            provider=IMProvider.SLACK,
            install_mode=IMInstallMode.ISV,
        )
