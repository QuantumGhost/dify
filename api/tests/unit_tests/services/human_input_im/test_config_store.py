from __future__ import annotations

import pytest

from services.human_input_im.config_store import (
    EnvBackedProviderConfigStore,
    HumanInputIMIngressMode,
    HumanInputIMProvider,
)


def test_env_backed_provider_config_store_returns_feishu_config(monkeypatch):
    monkeypatch.setenv("LARK_APP_ID", "app-id")
    monkeypatch.setenv("LARK_APP_SECRET", "app-secret")
    monkeypatch.setenv("LARK_EVENT_MODE", "webhook")

    store = EnvBackedProviderConfigStore()

    config = store.get_active_config(tenant_id="tenant-1")

    assert config is not None
    assert config.provider == HumanInputIMProvider.FEISHU
    assert config.ingress_mode == HumanInputIMIngressMode.WEBHOOK
    assert config.app_id == "app-id"
    assert config.app_secret == "app-secret"
    assert config.tenant_id is None
    assert config.verification_token is None
    assert config.encrypt_key is None


def test_env_backed_provider_config_store_returns_none_when_credentials_missing(monkeypatch):
    monkeypatch.delenv("LARK_APP_ID", raising=False)
    monkeypatch.delenv("LARK_APP_SECRET", raising=False)
    monkeypatch.delenv("LARK_EVENT_MODE", raising=False)

    store = EnvBackedProviderConfigStore()

    assert store.get_active_config(tenant_id="tenant-1") is None


def test_env_backed_provider_config_store_supports_stream_mode(monkeypatch):
    monkeypatch.setenv("LARK_APP_ID", "app-id")
    monkeypatch.setenv("LARK_APP_SECRET", "app-secret")
    monkeypatch.setenv("LARK_EVENT_MODE", "stream")

    store = EnvBackedProviderConfigStore()

    config = store.get_active_config(tenant_id="tenant-1")

    assert config is not None
    assert config.ingress_mode == HumanInputIMIngressMode.STREAM


def test_env_backed_provider_config_store_rejects_polling_mode(monkeypatch):
    monkeypatch.setenv("LARK_APP_ID", "app-id")
    monkeypatch.setenv("LARK_APP_SECRET", "app-secret")
    monkeypatch.setenv("LARK_EVENT_MODE", "polling")

    store = EnvBackedProviderConfigStore()

    with pytest.raises(ValueError, match="Unsupported LARK_EVENT_MODE"):
        store.get_active_config(tenant_id="tenant-1")


def test_env_backed_provider_config_store_rejects_other_tenants(monkeypatch):
    monkeypatch.setenv("LARK_APP_ID", "app-id")
    monkeypatch.setenv("LARK_APP_SECRET", "app-secret")
    monkeypatch.setenv("LARK_EVENT_MODE", "webhook")
    monkeypatch.setenv("LARK_TENANT_ID", "tenant-1")

    store = EnvBackedProviderConfigStore()

    assert store.get_active_config(tenant_id="tenant-2") is None
    config = store.get_active_config(tenant_id="tenant-1")
    assert config is not None
    assert config.tenant_id == "tenant-1"
