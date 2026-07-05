"""Provider-neutral IM provider registry for phase-1 HITL foundations.

The Feishu self-built adapter is the default production implementation for the
phase-1 demo. Legacy placeholder providers may still exist for isolated tests
or local debugging, but they are no longer wired into the runtime registry.
"""

from __future__ import annotations

from services.human_input_im.provider_types import HumanInputIMProvider
from models.im_integration import IMProvider
from services.human_input_im.app_config_service import IMAppContext, resolve_im_app_context
from services.human_input_im.feishu_provider import FeishuHumanInputIMProvider


class HumanInputIMProviderRegistry:
    """Resolve provider app context and registered provider implementation."""

    def __init__(self, providers: dict[IMProvider, HumanInputIMProvider] | None = None) -> None:
        self._providers = providers or {IMProvider.FEISHU: FeishuHumanInputIMProvider()}

    def get_provider(self, provider: IMProvider) -> HumanInputIMProvider | None:
        return self._providers.get(provider)

    def resolve_app_context(self, *, provider: IMProvider, tenant_id: str) -> IMAppContext:
        return resolve_im_app_context(provider=provider, tenant_id=tenant_id)
