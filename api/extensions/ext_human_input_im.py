import logging

from configs import dify_config
from dify_app import DifyApp
from services.human_input_im.config_store import EnvBackedProviderConfigStore, HumanInputIMIngressMode
from services.human_input_im.feishu_long_connection_service import FeishuLongConnectionService

logger = logging.getLogger(__name__)

_long_connection_service = FeishuLongConnectionService(config_store=EnvBackedProviderConfigStore())


def is_enabled() -> bool:
    return bool(dify_config.LARK_APP_ID and dify_config.LARK_APP_SECRET)


def init_app(app: DifyApp):
    config_store = EnvBackedProviderConfigStore()
    owner_tenant_id = config_store.get_owner_tenant_id() or ""
    config = config_store.get_active_config(owner_tenant_id)
    if config is None:
        return

    if config.ingress_mode == HumanInputIMIngressMode.STREAM:
        started = _long_connection_service.start()
        if started:
            logger.info("Feishu stream ingress started")
        return
