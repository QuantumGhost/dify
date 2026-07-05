"""Provider-neutral IM orchestration service for phase-1 HITL foundations.

This module composes app config resolution, provider registry lookup, and
binding lifecycle helpers. Provider-specific transport and callback handling
should later prefer official SDKs when available.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.im_integration import IMProvider
from services.entities.im_binding_entities import IMBindingRecord, IMBindingSessionRecord
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.binding_service import (
    complete_binding_session,
    create_binding_session,
    get_active_binding,
    revoke_active_binding,
)
from services.human_input_im.provider_registry import HumanInputIMProviderRegistry


class HumanInputIMOrchestrationService:
    def __init__(self, registry: HumanInputIMProviderRegistry | None = None) -> None:
        self._registry = registry or HumanInputIMProviderRegistry()

    def resolve_app_context(self, *, provider: IMProvider, tenant_id: str):
        return self._registry.resolve_app_context(provider=provider, tenant_id=tenant_id)

    def get_provider_or_raise(self, provider: IMProvider):
        resolved_provider = self._registry.get_provider(provider)
        if resolved_provider is None:
            raise IMBindingValidationError(f"IM provider is not registered: {provider.value}")
        return resolved_provider

    def start_binding_session(
        self,
        *,
        session: Session,
        account_id: str,
        tenant_id: str,
        provider: IMProvider,
    ) -> IMBindingSessionRecord:
        app_context = self.resolve_app_context(provider=provider, tenant_id=tenant_id)
        return create_binding_session(session=session, account_id=account_id, app_context=app_context)

    def inspect_active_binding(self, *, session: Session, account_id: str) -> IMBindingRecord | None:
        return get_active_binding(session=session, account_id=account_id)

    def revoke_active_binding(self, *, session: Session, account_id: str) -> IMBindingRecord | None:
        return revoke_active_binding(session=session, account_id=account_id)

    def complete_binding_session(
        self,
        *,
        session: Session,
        token: str,
        provider_workspace_id: str,
        provider_user_id: str,
        provider_union_id: str | None = None,
        provider_user_display_name: str | None = None,
        provider_user_avatar_url: str | None = None,
    ) -> IMBindingRecord:
        return complete_binding_session(
            session=session,
            token=token,
            provider_workspace_id=provider_workspace_id,
            provider_user_id=provider_user_id,
            provider_union_id=provider_union_id,
            provider_user_display_name=provider_user_display_name,
            provider_user_avatar_url=provider_user_avatar_url,
        )
