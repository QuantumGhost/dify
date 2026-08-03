"""TLS policy regressions for concrete outbound Provider clients."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import httpx
import pytest

from configs import dify_config
from core.human_input_v2.im_provider import SlackAdapterConfig
from core.human_input_v2.im_provider.providers import feishu_lark as feishu_provider
from core.human_input_v2.im_provider.providers import microsoft_teams as teams_provider
from core.human_input_v2.im_provider.providers import slack as slack_provider


def _build_slack_client() -> httpx.Client:
    return slack_provider._build_http_client(
        SlackAdapterConfig(
            bot_token="xoxb-test",
            signing_secret="signing-secret",
            app_token="xapp-test",
        )
    )


@pytest.mark.parametrize(
    ("provider_module", "build_client"),
    [
        (slack_provider, _build_slack_client),
        (feishu_provider, feishu_provider._build_http_client),
        (teams_provider, teams_provider._build_http_client),
    ],
    ids=("slack", "feishu_lark", "microsoft_teams"),
)
def test_provider_http_clients_keep_tls_verification_when_generic_setting_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    provider_module: ModuleType,
    build_client: Callable[[], httpx.Client],
) -> None:
    client_options: dict[str, object] = {}

    def capture_client_options(**kwargs: object) -> httpx.Client:
        client_options.update(kwargs)
        return httpx.Client()

    monkeypatch.setattr(dify_config, "HTTP_REQUEST_NODE_SSL_VERIFY", False)
    monkeypatch.setattr(provider_module, "create_ssrf_protected_client", capture_client_options)

    client = build_client()

    assert client_options["verify"] is True
    client.close()
