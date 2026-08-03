"""WeCom public composition and root-owned context requirements."""

from __future__ import annotations

import inspect

import pytest

from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    CredentialTestSuccess,
    DirectorySnapshot,
    MessageAccepted,
    PermissionFact,
    WeComAdapter,
    WeComAdapterConfig,
    WeComMessageReference,
    WeComUserDestination,
)
from core.human_input_v2.im_provider import adapters as adapter_composition
from core.human_input_v2.im_provider.client_roles import _ProviderClientContext


def _config() -> WeComAdapterConfig:
    return WeComAdapterConfig(
        corp_id="ww-corp-test",
        agent_id="1000005",
        corp_secret="secret-test",
    )


class _RootOwnedClient:
    close_calls: int

    def __init__(self) -> None:
        self.close_calls = 0

    def test_credentials(self) -> CredentialTestSuccess:
        return CredentialTestSuccess(
            provider=IMProvider.WE_COM,
            provider_tenant_id="ww-corp-test",
            permissions=(PermissionFact("agent.visibility.read", True),),
        )

    def read_directory(self) -> DirectorySnapshot:
        return DirectorySnapshot(IMProvider.WE_COM, "ww-corp-test", ())

    def test_destination(self, destination: WeComUserDestination) -> None:
        return None

    def send_text(
        self,
        destination: WeComUserDestination,
        body: str,
    ) -> MessageAccepted[WeComMessageReference]:
        return MessageAccepted(WeComMessageReference("message-test"), None)

    def close(self) -> None:
        self.close_calls += 1


class _ContextFactory:
    calls: list[WeComAdapterConfig]
    client: _RootOwnedClient

    def __init__(self) -> None:
        self.calls = []
        self.client = _RootOwnedClient()

    def __call__(
        self,
        config: WeComAdapterConfig,
    ) -> _ProviderClientContext[WeComUserDestination, WeComMessageReference]:
        self.calls.append(config)
        return _ProviderClientContext(
            credentials=self.client,
            directory=self.client,
            messaging=self.client,
            card=None,
            webhook=None,
            stream=None,
            owned_resources=(self.client,),
        )


def test_wecom_public_adapter_lazily_reuses_one_root_owned_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _ContextFactory()
    monkeypatch.setattr(adapter_composition, "_create_wecom_client_context", factory, raising=False)

    adapter = WeComAdapter(_config())
    directory = adapter.directory
    messaging = adapter.messaging

    assert adapter.directory is directory
    assert adapter.messaging is messaging
    assert adapter.dynamic_card_messaging is None
    assert adapter.webhook_events is None
    assert adapter.stream_events is None
    assert factory.calls == []

    credential_result = adapter.test_credentials()
    directory_result = directory.read_snapshot()
    destination_result = messaging.test_destination(WeComUserDestination("user-visible"))

    assert isinstance(credential_result, CredentialTestSuccess)
    assert isinstance(directory_result, DirectorySnapshot)
    assert destination_result is None
    assert factory.calls == [_config()]

    adapter.close()
    assert factory.client.close_calls == 1


def test_wecom_public_adapter_constructor_does_not_expose_context_factory() -> None:
    assert tuple(inspect.signature(WeComAdapter).parameters) == ("config",)
