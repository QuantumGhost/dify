from __future__ import annotations

from types import SimpleNamespace

from extensions import ext_human_input_im
from services.human_input_im.config_store import (
    HumanInputIMIngressMode,
    HumanInputIMProvider,
    HumanInputIMProviderConfig,
)


def test_ext_human_input_im_starts_long_connection(monkeypatch):
    started = []

    monkeypatch.setattr(
        ext_human_input_im,
        "EnvBackedProviderConfigStore",
        lambda: SimpleNamespace(
            get_owner_tenant_id=lambda: "tenant-1",
            get_active_config=lambda tenant_id: HumanInputIMProviderConfig(
                provider=HumanInputIMProvider.FEISHU,
                ingress_mode=HumanInputIMIngressMode.STREAM,
                app_id="app-id",
                app_secret="app-secret",
                tenant_id="tenant-1",
            ),
        ),
    )
    monkeypatch.setattr(
        ext_human_input_im,
        "_long_connection_service",
        SimpleNamespace(start=lambda: started.append(True) or True),
    )

    ext_human_input_im.init_app(SimpleNamespace())

    assert started == [True]
