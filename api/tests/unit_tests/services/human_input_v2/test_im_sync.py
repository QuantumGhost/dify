"""Unit tests for IM integration and manual-sync application orchestration."""

from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from unittest.mock import MagicMock, patch

import pytest

from core.human_input_v2.entities import IMIntegrationStatus, IMProvider, IMSyncResultType
from core.human_input_v2.im_integration import (
    ActiveRunDecision,
    ActiveRunDecisionKind,
    EncryptedCredentials,
    IMIntegration,
    IMSyncRun,
    IntegrationRevisionToken,
    ProviderDirectoryEntry,
    ProviderTenantIdentity,
    ReconciliationSnapshot,
    StaleRevision,
)
from core.human_input_v2.shared import AccountId, IMSyncRunId, IntegrationId, UtcTimestamp, WorkspaceId
from libs.rsa import PrivkeyNotFoundError
from repositories.human_input_v2.im_integration import IMIntegrationCreationError
from services.human_input_v2.im_provider import (
    ProviderAdapterError,
    ProviderConnectionDiagnostic,
    ProviderCredentials,
    create_provider_credentials,
)
from services.human_input_v2.im_sync import IMSyncManagementError, IMSyncManagementService

_NOW = UtcTimestamp(datetime(2026, 7, 26, 8, tzinfo=UTC))
_WORKSPACE_ID = WorkspaceId("workspace-1")
_PROVIDER_TENANT = ProviderTenantIdentity(IMProvider.FEISHU, "tenant-1")


def _credentials(provider: IMProvider = IMProvider.FEISHU) -> ProviderCredentials:
    return create_provider_credentials(
        provider,
        {
            "app_id": " app-id ",
            "app_secret": "secret",
            "verification_token": "verification",
            "encrypt_key": "encrypt",
        },
    )


def _integration(
    provider: IMProvider = IMProvider.FEISHU,
    *,
    workspace_id: WorkspaceId | None = _WORKSPACE_ID,
) -> IMIntegration:
    return IMIntegration.create(
        integration_id=IntegrationId("integration-1"),
        workspace_id=workspace_id,
        provider_tenant=ProviderTenantIdentity(provider, "tenant-1"),
        encrypted_credentials=EncryptedCredentials.from_mapping(
            {
                "app_id": "app-id",
                "encrypted_app_secret": "encrypted-secret",
                "encrypted_verification_token": "encrypted-verification",
                "encrypted_encrypt_key": "encrypted-encrypt",
            }
        ),
        configured_by_account_id=AccountId("account-1"),
        callback_url=None,
        now=_NOW,
    )


def _run(integration: IMIntegration | None = None) -> IMSyncRun:
    current = integration or _integration()
    return IMSyncRun.create(
        sync_run_id=IMSyncRunId("run-1"),
        integration_revision=current.revision,
        provider=current.provider_tenant.provider,
        started_by_account_id=AccountId("account-1"),
        now=_NOW,
    )


def _configure_claim(repository: MagicMock, integration: IMIntegration) -> IMSyncRun:
    claimed = _run(integration)
    repository.mark_sync_run_running.return_value = claimed
    repository.find_integration.return_value = integration
    return claimed


def _diagnostic(
    status: IMIntegrationStatus = IMIntegrationStatus.CONNECTED,
    provider_tenant: ProviderTenantIdentity | None = _PROVIDER_TENANT,
) -> ProviderConnectionDiagnostic:
    return ProviderConnectionDiagnostic(status=status, message="diagnostic", provider_tenant=provider_tenant)


def test_prepare_credentials_maps_registry_validation_to_application_errors() -> None:
    service = IMSyncManagementService(MagicMock(), MagicMock())

    credentials = service.prepare_credentials(
        IMProvider.FEISHU,
        {"app_id": " app-id ", "app_secret": "secret"},
    )

    assert credentials.to_mapping() == {
        "app_id": "app-id",
        "app_secret": "secret",
        "verification_token": None,
        "encrypt_key": None,
    }
    with pytest.raises(IMSyncManagementError) as unsupported:
        service.prepare_credentials(IMProvider.SLACK, {"bot_token": "secret"})
    assert unsupported.value.code == "unsupported_provider"
    with pytest.raises(IMSyncManagementError) as invalid:
        service.prepare_credentials(IMProvider.FEISHU, {"app_id": " ", "app_secret": "secret"})
    assert invalid.value.code == "invalid_credentials"


def test_load_plaintext_credentials_decrypts_optional_values() -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = _integration()
    service = IMSyncManagementService(repository, MagicMock())

    with patch(
        "services.human_input_v2.im_sync.encrypter.decrypt_token",
        side_effect=lambda workspace_id, value: f"{workspace_id}:{value}",
    ) as decrypt:
        credentials = service.load_plaintext_credentials("workspace-1")

    assert credentials == create_provider_credentials(
        IMProvider.FEISHU,
        {
            "app_id": "app-id",
            "app_secret": "workspace-1:encrypted-secret",
            "verification_token": "workspace-1:encrypted-verification",
            "encrypt_key": "workspace-1:encrypted-encrypt",
        },
    )
    assert decrypt.call_count == 3


def test_load_plaintext_credentials_handles_missing_and_unsupported_integration() -> None:
    repository = MagicMock()
    service = IMSyncManagementService(repository, MagicMock())
    repository.find_current_integration.return_value = None
    assert service.load_plaintext_credentials("workspace-1") is None

    repository.find_current_integration.return_value = _integration(IMProvider.SLACK)
    with pytest.raises(IMSyncManagementError, match="not supported") as error:
        service.load_plaintext_credentials("workspace-1")
    assert error.value.code == "unsupported_provider"


def test_test_connection_uses_provider_factory() -> None:
    provider_client = MagicMock()
    provider_client.test_connection.return_value = _diagnostic()
    service = IMSyncManagementService(MagicMock(), MagicMock())

    with patch("services.human_input_v2.im_sync.create_provider_client", return_value=provider_client) as factory:
        result = service.test_connection(_credentials())

    assert result.connected is True
    factory.assert_called_once_with(_credentials())


def test_deployment_fallback_allows_stateless_connection_test_but_rejects_secret_preservation() -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = _integration(workspace_id=None)
    provider_client = MagicMock()
    provider_client.test_connection.return_value = _diagnostic()
    service = IMSyncManagementService(repository, MagicMock())

    with patch("services.human_input_v2.im_sync.create_provider_client", return_value=provider_client) as factory:
        diagnostic = service.test_connection(_credentials())

    assert diagnostic.connected is True
    factory.assert_called_once_with(_credentials())
    with pytest.raises(IMSyncManagementError) as preserve_error:
        service.load_plaintext_credentials("workspace-1")
    assert preserve_error.value.code == "deployment_integration_unsupported"


def test_create_integration_encrypts_credentials_after_connection_test() -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = None
    repository.create_integration.side_effect = lambda integration: integration
    service = IMSyncManagementService(repository, MagicMock())

    with (
        patch.object(service, "test_connection", return_value=_diagnostic()),
        patch(
            "services.human_input_v2.im_sync.encrypter.encrypt_token",
            side_effect=lambda owner, value: f"{owner}:{value}",
        ),
    ):
        result = service.upsert_integration(
            workspace_id="workspace-1",
            account_id="account-1",
            credentials=_credentials(),
            expected_revision=None,
        )

    assert result.status is IMIntegrationStatus.CONNECTED
    assert result.workspace_id == WorkspaceId("workspace-1")
    assert result.encrypted_credentials.to_mapping() == {
        "app_id": "app-id",
        "encrypted_app_secret": "workspace-1:secret",
        "encrypted_encrypt_key": "workspace-1:encrypt",
        "encrypted_verification_token": "workspace-1:verification",
    }


def test_upsert_rejects_failed_connection_and_stale_create() -> None:
    repository = MagicMock()
    service = IMSyncManagementService(repository, MagicMock())
    with patch.object(
        service,
        "test_connection",
        return_value=_diagnostic(IMIntegrationStatus.CONNECTION_ERROR, None),
    ):
        with pytest.raises(IMSyncManagementError, match="diagnostic") as connection_error:
            service.upsert_integration(
                workspace_id="workspace-1",
                account_id="account-1",
                credentials=_credentials(),
                expected_revision=None,
            )
    assert connection_error.value.code == "provider_connection_failed"

    repository.find_current_integration.return_value = None
    with (
        patch.object(service, "test_connection", return_value=_diagnostic()),
        patch("services.human_input_v2.im_sync.encrypter.encrypt_token", return_value="encrypted"),
        pytest.raises(IMSyncManagementError, match="configuration changed") as stale_error,
    ):
        service.upsert_integration(
            workspace_id="workspace-1",
            account_id="account-1",
            credentials=_credentials(),
            expected_revision=IntegrationRevisionToken(IntegrationId("missing"), 1),
        )
    assert stale_error.value.code == "stale_revision"


def test_first_create_conflict_maps_to_stale_revision_without_raw_persistence_details() -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = None
    repository.create_integration.side_effect = IMIntegrationCreationError(
        "integration_already_configured",
        "raw database conflict details",
    )
    service = IMSyncManagementService(repository, MagicMock())

    with (
        patch.object(service, "test_connection", return_value=_diagnostic()),
        patch("services.human_input_v2.im_sync.encrypter.encrypt_token", return_value="encrypted"),
        pytest.raises(IMSyncManagementError, match="configuration changed") as error,
    ):
        service.upsert_integration(
            workspace_id="workspace-1",
            account_id="account-1",
            credentials=_credentials(),
            expected_revision=None,
        )

    assert error.value.code == "stale_revision"
    assert "raw database conflict details" not in str(error.value)
    assert isinstance(error.value.__cause__, IMIntegrationCreationError)


def test_update_integration_persists_configuration_and_connected_diagnostics_in_one_cas() -> None:
    repository = MagicMock()
    current = _integration()
    repository.find_current_integration.return_value = current
    repository.compare_and_swap_configuration.side_effect = lambda transition: transition.integration
    service = IMSyncManagementService(repository, MagicMock())

    with (
        patch.object(service, "test_connection", return_value=_diagnostic()),
        patch("services.human_input_v2.im_sync.encrypter.encrypt_token", return_value="encrypted"),
    ):
        updated = service.upsert_integration(
            workspace_id="workspace-1",
            account_id="account-2",
            credentials=_credentials(),
            expected_revision=current.revision,
        )

    assert updated.id == current.id
    assert updated.config_version == 2
    assert updated.status is IMIntegrationStatus.CONNECTED
    transition = repository.compare_and_swap_configuration.call_args.args[0]
    assert transition.integration.status is IMIntegrationStatus.CONNECTED
    assert transition.integration.safe_status_reason is None
    assert transition.integration.last_checked_at is not None
    repository.compare_and_swap_configuration.assert_called_once_with(transition)
    repository.compare_and_swap_diagnostics.assert_not_called()


def test_update_integration_replaces_identity_when_provider_tenant_changes() -> None:
    repository = MagicMock()
    current = _integration()
    repository.find_current_integration.return_value = current
    repository.compare_and_swap_configuration.side_effect = lambda transition: transition.integration
    service = IMSyncManagementService(repository, MagicMock())
    replacement_tenant = ProviderTenantIdentity(IMProvider.FEISHU, "tenant-2")

    with (
        patch.object(service, "test_connection", return_value=_diagnostic(provider_tenant=replacement_tenant)),
        patch("services.human_input_v2.im_sync.encrypter.encrypt_token", return_value="encrypted"),
        patch("services.human_input_v2.im_sync.uuidv7", return_value="integration-2"),
    ):
        updated = service.upsert_integration(
            workspace_id="workspace-1",
            account_id="account-2",
            credentials=_credentials(),
            expected_revision=current.revision,
        )

    assert updated.id == IntegrationId("integration-2")
    assert updated.provider_tenant == replacement_tenant
    repository.compare_and_swap_configuration.assert_called_once()
    repository.compare_and_swap_diagnostics.assert_not_called()


def test_update_integration_requires_current_revision() -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = _integration()
    service = IMSyncManagementService(repository, MagicMock())

    with (
        patch.object(service, "test_connection", return_value=_diagnostic()),
        patch("services.human_input_v2.im_sync.encrypter.encrypt_token", return_value="encrypted"),
        pytest.raises(IMSyncManagementError) as error,
    ):
        service.upsert_integration(
            workspace_id="workspace-1",
            account_id="account-1",
            credentials=_credentials(),
            expected_revision=None,
        )

    assert error.value.code == "stale_revision"
    repository.compare_and_swap_configuration.assert_not_called()


def test_update_integration_maps_repository_configuration_cas_failure() -> None:
    repository = MagicMock()
    current = _integration()
    repository.find_current_integration.return_value = current
    stale = StaleRevision(current.revision, current.revision)
    repository.compare_and_swap_configuration.return_value = stale
    service = IMSyncManagementService(repository, MagicMock())

    with (
        patch.object(service, "test_connection", return_value=_diagnostic()),
        patch("services.human_input_v2.im_sync.encrypter.encrypt_token", return_value="encrypted"),
        pytest.raises(IMSyncManagementError, match="configuration changed") as error,
    ):
        service.upsert_integration(
            workspace_id="workspace-1",
            account_id="account-1",
            credentials=_credentials(),
            expected_revision=current.revision,
        )
    assert error.value.code == "stale_revision"
    repository.compare_and_swap_configuration.assert_called_once()
    repository.compare_and_swap_diagnostics.assert_not_called()


def test_delete_integration_applies_complete_cas() -> None:
    repository = MagicMock()
    current = _integration()
    repository.find_current_integration.return_value = current
    service = IMSyncManagementService(repository, MagicMock())

    service.delete_integration(
        workspace_id="workspace-1",
        expected_revision=current.revision,
    )

    repository.compare_and_swap_delete.assert_called_once()
    assert repository.compare_and_swap_delete.call_args.args[0].expected_revision == current.revision


@pytest.mark.parametrize("stale_stage", ["missing", "domain", "repository"])
def test_delete_integration_maps_each_stale_revision_stage(stale_stage: str) -> None:
    repository = MagicMock()
    current = _integration()
    repository.find_current_integration.return_value = None if stale_stage == "missing" else current
    expected_revision = IntegrationRevisionToken(current.id, 9) if stale_stage == "domain" else current.revision
    if stale_stage == "repository":
        repository.compare_and_swap_delete.return_value = StaleRevision(current.revision, current.revision)
    service = IMSyncManagementService(repository, MagicMock())

    with pytest.raises(IMSyncManagementError) as error:
        service.delete_integration(
            workspace_id="workspace-1",
            expected_revision=expected_revision,
        )

    assert error.value.code == "stale_revision"


def test_trigger_sync_dispatches_only_new_run_and_reuses_active_run() -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = _integration()
    dispatcher = MagicMock()
    service = IMSyncManagementService(repository, dispatcher)
    run = _run()
    repository.create_or_get_active_run.return_value = ActiveRunDecision(ActiveRunDecisionKind.CREATED, run)

    assert service.trigger_sync(workspace_id="workspace-1", account_id="account-1") == run
    dispatcher.assert_called_once_with("run-1")

    repository.create_or_get_active_run.return_value = ActiveRunDecision(ActiveRunDecisionKind.EXISTING_ACTIVE, run)
    assert service.trigger_sync(workspace_id="workspace-1", account_id="account-1") == run
    assert dispatcher.call_args_list == [(("run-1",), {}), (("run-1",), {})]


def test_trigger_sync_preserves_queued_run_after_dispatch_failure_for_retry() -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = _integration()
    dispatcher = MagicMock(side_effect=RuntimeError("broker unavailable"))
    service = IMSyncManagementService(repository, dispatcher)
    run = _run()
    repository.create_or_get_active_run.return_value = ActiveRunDecision(ActiveRunDecisionKind.CREATED, run)

    with pytest.raises(IMSyncManagementError, match="Unable to schedule") as error:
        service.trigger_sync(workspace_id="workspace-1", account_id="account-1")

    assert error.value.code == "sync_dispatch_failed"
    dispatcher.assert_called_once_with("run-1")
    repository.fail_sync_run.assert_not_called()
    assert run.status.value == "queued"

    dispatcher.side_effect = None
    repository.create_or_get_active_run.return_value = ActiveRunDecision(ActiveRunDecisionKind.EXISTING_ACTIVE, run)
    assert service.trigger_sync(workspace_id="workspace-1", account_id="account-1") == run
    assert dispatcher.call_count == 2


def test_trigger_sync_does_not_redispatch_running_active_run() -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = _integration()
    dispatcher = MagicMock()
    service = IMSyncManagementService(repository, dispatcher)
    running = _run().start(_NOW)
    repository.create_or_get_active_run.return_value = ActiveRunDecision(
        ActiveRunDecisionKind.EXISTING_ACTIVE,
        running,
    )

    assert service.trigger_sync(workspace_id="workspace-1", account_id="account-1") == running

    dispatcher.assert_not_called()


def test_trigger_sync_rejects_missing_integration_and_stale_decision() -> None:
    repository = MagicMock()
    service = IMSyncManagementService(repository, MagicMock())
    repository.find_current_integration.return_value = None
    with pytest.raises(IMSyncManagementError) as missing:
        service.trigger_sync(workspace_id="workspace-1", account_id="account-1")
    assert missing.value.code == "integration_not_configured"

    repository.find_current_integration.return_value = _integration()
    repository.create_or_get_active_run.return_value = ActiveRunDecision(ActiveRunDecisionKind.STALE_REVISION, None)
    with pytest.raises(IMSyncManagementError) as stale:
        service.trigger_sync(workspace_id="workspace-1", account_id="account-1")
    assert stale.value.code == "stale_revision"


def test_latest_run_and_result_page_delegate_with_workspace_scope() -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = _integration()
    service = IMSyncManagementService(repository, MagicMock())
    run = _run()
    repository.get_latest_sync_run.return_value = run
    repository.list_latest_sync_results.return_value = (("fact",), 7)

    assert service.get_latest_sync_run("workspace-1") == run
    page = service.list_latest_results(
        workspace_id="workspace-1",
        result_type=IMSyncResultType.NOT_MATCHED,
        page=3,
        limit=20,
    )

    assert page.items == ("fact",)
    assert (page.total, page.page, page.limit) == (7, 3, 20)
    repository.list_latest_sync_results.assert_called_once_with(
        WorkspaceId("workspace-1"),
        result_type=IMSyncResultType.NOT_MATCHED,
        offset=40,
        limit=20,
    )

    repository.get_latest_sync_run.return_value = None
    with pytest.raises(IMSyncManagementError) as missing:
        service.get_latest_sync_run("workspace-1")
    assert missing.value.code == "sync_run_not_found"


@pytest.mark.parametrize("operation", ["latest", "results"])
def test_workspace_data_reads_reject_deployment_fallback_before_repository_access(operation: str) -> None:
    repository = MagicMock()
    repository.find_current_integration.return_value = _integration(workspace_id=None)
    service = IMSyncManagementService(repository, MagicMock())
    invoke = (
        partial(service.get_latest_sync_run, "workspace-1")
        if operation == "latest"
        else partial(
            service.list_latest_results,
            workspace_id="workspace-1",
            result_type=IMSyncResultType.FAILED,
            page=1,
            limit=20,
        )
    )

    with pytest.raises(IMSyncManagementError, match="Deployment-wide") as error:
        invoke()

    assert error.value.code == "deployment_integration_unsupported"
    repository.get_latest_sync_run.assert_not_called()
    repository.list_latest_sync_results.assert_not_called()


def test_execute_sync_normalizes_reconciles_and_applies() -> None:
    repository = MagicMock()
    integration = _integration()
    _configure_claim(repository, integration)
    snapshot = ReconciliationSnapshot()
    repository.load_reconciliation_snapshot.return_value = snapshot
    provider_client = MagicMock()
    entries = (
        ProviderDirectoryEntry.create(
            provider_user_id="provider-user-1",
            display_name="Reviewer",
            email="reviewer@example.com",
            raw_payload={},
        ),
    )
    provider_client.list_directory_entries.return_value = entries
    service = IMSyncManagementService(repository, MagicMock())

    with (
        patch("services.human_input_v2.im_sync.encrypter.decrypt_token", return_value="plain"),
        patch("services.human_input_v2.im_sync.create_provider_client", return_value=provider_client),
        patch("services.human_input_v2.im_sync.SyncReconciler.reconcile", return_value="plan") as reconcile,
    ):
        service.execute_sync("run-1")

    repository.mark_sync_run_running.assert_called_once()
    reconcile.assert_called_once_with(
        sync_run_id=IMSyncRunId("run-1"),
        integration_revision=integration.revision,
        provider=IMProvider.FEISHU,
        entries=entries,
        snapshot=snapshot,
    )
    repository.apply_reconciliation.assert_called_once()
    repository.fail_sync_run.assert_not_called()


def test_execute_sync_duplicate_delivery_exits_when_atomic_claim_is_lost() -> None:
    repository = MagicMock()
    repository.mark_sync_run_running.return_value = None
    service = IMSyncManagementService(repository, MagicMock())

    service.execute_sync("run-1")

    repository.mark_sync_run_running.assert_called_once()
    repository.find_integration.assert_not_called()
    repository.load_reconciliation_snapshot.assert_not_called()
    repository.apply_reconciliation.assert_not_called()
    repository.fail_sync_run.assert_not_called()


def test_execute_sync_terminally_fences_stale_captured_revision_before_provider_access() -> None:
    repository = MagicMock()
    captured = _integration()
    _configure_claim(repository, captured)
    current = replace(captured, config_version=2)
    repository.find_integration.return_value = current
    service = IMSyncManagementService(repository, MagicMock())

    with (
        patch("services.human_input_v2.im_sync.encrypter.decrypt_token") as decrypt,
        patch("services.human_input_v2.im_sync.create_provider_client") as provider_factory,
        pytest.raises(IMSyncManagementError, match="configuration changed") as error,
    ):
        service.execute_sync("run-1")

    assert error.value.code == "stale_integration_revision"
    repository.fail_sync_run.assert_called_once()
    assert repository.fail_sync_run.call_args.kwargs["error_code"] == "stale_integration_revision"
    decrypt.assert_not_called()
    provider_factory.assert_not_called()
    repository.load_reconciliation_snapshot.assert_not_called()
    repository.apply_reconciliation.assert_not_called()
    repository.compare_and_swap_configuration.assert_not_called()
    repository.compare_and_swap_diagnostics.assert_not_called()
    assert repository.find_integration.return_value is current


def test_execute_sync_terminally_maps_missing_private_key_before_provider_access() -> None:
    repository = MagicMock()
    integration = _integration()
    _configure_claim(repository, integration)
    service = IMSyncManagementService(repository, MagicMock())

    with (
        patch(
            "services.human_input_v2.im_sync.encrypter.decrypt_token",
            side_effect=PrivkeyNotFoundError("private key details"),
        ),
        patch("services.human_input_v2.im_sync.create_provider_client") as provider_factory,
        patch("services.human_input_v2.im_sync.SyncReconciler.reconcile") as reconcile,
        pytest.raises(IMSyncManagementError, match="Stored IM provider credentials are unavailable") as error,
    ):
        service.execute_sync("run-1")

    assert error.value.code == "provider_credentials_unavailable"
    repository.fail_sync_run.assert_called_once()
    assert repository.fail_sync_run.call_args.kwargs["error_code"] == "provider_credentials_unavailable"
    assert (
        repository.fail_sync_run.call_args.kwargs["error_message"] == "Stored IM provider credentials are unavailable."
    )
    assert "private key details" not in str(error.value)
    provider_factory.assert_not_called()
    reconcile.assert_not_called()
    repository.load_reconciliation_snapshot.assert_not_called()
    repository.apply_reconciliation.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (ProviderAdapterError("provider secret"), "provider_directory_sync_failed"),
        (ValueError("invalid provider payload"), "provider_directory_sync_failed"),
        (RuntimeError("database details"), "im_directory_sync_failed"),
    ],
)
def test_execute_sync_terminally_records_safe_failure(failure: Exception, expected_code: str) -> None:
    repository = MagicMock()
    integration = _integration()
    _configure_claim(repository, integration)
    provider_client = MagicMock()
    provider_client.list_directory_entries.side_effect = failure
    service = IMSyncManagementService(repository, MagicMock())

    with (
        patch("services.human_input_v2.im_sync.encrypter.decrypt_token", return_value="plain"),
        patch("services.human_input_v2.im_sync.create_provider_client", return_value=provider_client),
        pytest.raises(IMSyncManagementError, match="Unable to synchronize") as error,
    ):
        service.execute_sync("run-1")

    assert error.value.code == expected_code
    repository.fail_sync_run.assert_called_once()
    assert repository.fail_sync_run.call_args.kwargs["error_code"] == expected_code
    assert repository.fail_sync_run.call_args.kwargs["error_message"] == (
        "Unable to synchronize the IM provider directory."
    )


def test_execute_sync_rejects_deployment_owned_credentials_safely() -> None:
    repository = MagicMock()
    integration = _integration(workspace_id=None)
    _configure_claim(repository, integration)
    service = IMSyncManagementService(repository, MagicMock())

    with pytest.raises(IMSyncManagementError) as error:
        service.execute_sync("run-1")

    assert error.value.code == "deployment_integration_unsupported"
    repository.fail_sync_run.assert_called_once()


@pytest.mark.parametrize(
    "integration",
    [
        _integration(IMProvider.SLACK),
        IMIntegration.create(
            integration_id=IntegrationId("integration-1"),
            workspace_id=_WORKSPACE_ID,
            provider_tenant=_PROVIDER_TENANT,
            encrypted_credentials=EncryptedCredentials.from_mapping({"app_id": "app-id"}),
            configured_by_account_id=AccountId("account-1"),
            callback_url=None,
            now=_NOW,
        ),
    ],
)
def test_execute_sync_terminally_rejects_unsupported_or_incomplete_credentials(
    integration: IMIntegration,
) -> None:
    repository = MagicMock()
    _configure_claim(repository, integration)
    service = IMSyncManagementService(repository, MagicMock())

    with pytest.raises(IMSyncManagementError) as error:
        service.execute_sync("run-1")

    assert error.value.code == "provider_directory_sync_failed"
    repository.fail_sync_run.assert_called_once()
