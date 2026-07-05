"""Provider-neutral IM provider registry for phase-1 HITL foundations."""

from __future__ import annotations

from services.human_input_im.app_config_service import IMAppContext, resolve_im_app_context
from services.human_input_im.provider_types import HumanInputIMProvider
from models.im_integration import IMProvider


class HumanInputIMProviderRegistry:
    """Resolve provider app context and registered provider implementation."""

    def __init__(self, providers: dict[IMProvider, HumanInputIMProvider] | None = None) -> None:
        self._providers = providers or {}

    def get_provider(self, provider: IMProvider) -> HumanInputIMProvider | None:
        return self._providers.get(provider)

    def resolve_app_context(self, *, provider: IMProvider, tenant_id: str) -> IMAppContext:
        return resolve_im_app_context(provider=provider, tenant_id=tenant_id)
