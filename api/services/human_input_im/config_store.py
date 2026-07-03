from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class HumanInputIMProvider(StrEnum):
    FEISHU = "feishu"


class HumanInputIMIngressMode(StrEnum):
    WEBHOOK = "webhook"
    STREAM = "stream"


@dataclass(frozen=True)
class HumanInputIMProviderConfig:
    provider: HumanInputIMProvider
    ingress_mode: HumanInputIMIngressMode
    app_id: str
    app_secret: str
    tenant_id: str | None = None
    verification_token: str | None = None
    encrypt_key: str | None = None


class ProviderConfigStore(Protocol):
    def get_active_config(self, tenant_id: str) -> HumanInputIMProviderConfig | None: ...

    def get_owner_tenant_id(self) -> str | None: ...


class EnvBackedProviderConfigStore:
    """Temporary config source for demos before tenant-scoped storage exists.

    NOTE(QuantumGhost): callers must still depend on ProviderConfigStore, not on
    direct env reads, so production can swap in a tenant-scoped store later.
    """

    def get_active_config(self, tenant_id: str) -> HumanInputIMProviderConfig | None:
        app_id = os.getenv("LARK_APP_ID", "").strip()
        app_secret = os.getenv("LARK_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            return None

        configured_tenant_id = _optional_env("LARK_TENANT_ID")
        if configured_tenant_id is not None and tenant_id and configured_tenant_id != tenant_id:
            return None

        ingress_mode = _parse_ingress_mode(os.getenv("LARK_EVENT_MODE", "webhook"))
        return HumanInputIMProviderConfig(
            provider=HumanInputIMProvider.FEISHU,
            ingress_mode=ingress_mode,
            app_id=app_id,
            app_secret=app_secret,
            tenant_id=configured_tenant_id,
            verification_token=_optional_env("LARK_VERIFICATION_TOKEN"),
            encrypt_key=_optional_env("LARK_ENCRYPT_KEY"),
        )

    def get_owner_tenant_id(self) -> str | None:
        return _optional_env("LARK_TENANT_ID")


def _parse_ingress_mode(raw_value: str) -> HumanInputIMIngressMode:
    normalized_value = raw_value.strip().lower().replace("-", "_")
    if normalized_value == HumanInputIMIngressMode.STREAM:
        return HumanInputIMIngressMode.STREAM
    if normalized_value == HumanInputIMIngressMode.WEBHOOK:
        return HumanInputIMIngressMode.WEBHOOK
    raise ValueError(
        "Unsupported LARK_EVENT_MODE. Expected 'webhook' or 'stream'."
    )


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


__all__ = [
    "EnvBackedProviderConfigStore",
    "HumanInputIMIngressMode",
    "HumanInputIMProvider",
    "HumanInputIMProviderConfig",
    "ProviderConfigStore",
]
