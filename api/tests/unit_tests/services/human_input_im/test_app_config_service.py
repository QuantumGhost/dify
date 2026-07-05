from services.human_input_im.app_config_service import (
    IMAppConfigStatus,
    IMEventMode,
    IMInstallMode,
    IMProvider,
    IMScopeType,
    IMTokenStatus,
    resolve_im_app_context,
)


def test_resolve_im_app_context_reports_missing_credentials(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", None)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", None)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", None)

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.MISSING
    assert context.install_mode == IMInstallMode.SELF_BUILT
    assert context.scope_type == IMScopeType.DEPLOYMENT
    assert context.token_status == IMTokenStatus.NOT_APPLICABLE
    assert "missing LARK_APP_ID" in context.errors
    assert "missing LARK_APP_SECRET" in context.errors
    assert "missing LARK_EVENT_MODE" in context.errors


def test_resolve_im_app_context_requires_long_connection_for_phase_1(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "webhook")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.INVALID
    assert context.event_mode == IMEventMode.WEBHOOK
    assert context.errors == ["phase-1 demo requires LARK_EVENT_MODE=long_connection"]


def test_resolve_im_app_context_reports_partially_missing_credentials(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", None)
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.MISSING
    assert context.event_mode == IMEventMode.LONG_CONNECTION
    assert context.app_id == "cli_a"
    assert context.app_secret_configured is False
    assert context.errors == ["missing LARK_APP_SECRET"]


def test_resolve_im_app_context_reports_invalid_unsupported_event_mode(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "socket_mode")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.INVALID
    assert context.event_mode is None
    assert context.errors == ["invalid LARK_EVENT_MODE: socket_mode"]


def test_resolve_im_app_context_returns_configured_self_built_feishu(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")

    context = resolve_im_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.status == IMAppConfigStatus.CONFIGURED
    assert context.event_mode == IMEventMode.LONG_CONNECTION
    assert context.app_id == "cli_a"
    assert context.app_secret_configured is True
    assert context.errors == []
