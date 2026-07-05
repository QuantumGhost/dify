from models.im_integration import IMProvider
from services.human_input_im.app_config_service import IMAppConfigStatus, IMEventMode
from services.human_input_im.provider_registry import HumanInputIMProviderRegistry


def test_provider_registry_resolves_app_context(monkeypatch) -> None:
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_ID", "cli_a")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_APP_SECRET", "secret")
    monkeypatch.setattr("services.human_input_im.app_config_service.dify_config.LARK_EVENT_MODE", "long_connection")

    registry = HumanInputIMProviderRegistry()
    context = registry.resolve_app_context(provider=IMProvider.FEISHU, tenant_id="tenant-1")

    assert context.provider == IMProvider.FEISHU
    assert context.status == IMAppConfigStatus.CONFIGURED
    assert context.event_mode == IMEventMode.LONG_CONNECTION
