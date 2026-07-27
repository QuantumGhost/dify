"""Application orchestration for Human Input IM integration and manual sync.

The service owns credential encryption, provider adapter selection, sync-run
deduplication, and reconciliation orchestration. Controllers never consume SDK
models, and workers carry only a persisted sync-run identifier.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from celery.exceptions import CeleryError
from kombu.exceptions import KombuError
from sqlalchemy.exc import SQLAlchemyError

from core.helper import encrypter
from core.human_input_v2.entities import (
    IMIntegrationStatus,
    IMProvider,
    IMSyncResultType,
    IMSyncRunStatus,
)
from core.human_input_v2.im_integration import (
    ActiveRunDecisionKind,
    IMIntegration,
    IMSyncRun,
    IntegrationRevisionToken,
    StaleRevision,
    SyncReconciler,
    SyncResultFact,
)
from core.human_input_v2.shared import AccountId, IMSyncRunId, IntegrationId, UtcTimestamp, WorkspaceId
from libs.rsa import PrivkeyNotFoundError
from libs.uuid_utils import uuidv7
from repositories.human_input_v2.im_integration import (
    IMIntegrationCreationError,
    SQLAlchemyIMControlPlaneRepository,
)

from .im_provider import (
    InvalidProviderCredentialsError,
    ProviderAdapterError,
    ProviderConnectionDiagnostic,
    ProviderCredentials,
    UnsupportedProviderError,
    create_provider_client,
    create_provider_credentials,
    decrypt_provider_credentials,
    encrypt_provider_credentials,
)

logger = logging.getLogger(__name__)


class IMSyncManagementError(Exception):
    """Safe application error mapped by the console transport."""

    code: str

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


type SyncRunDispatcher = Callable[[str], object]


@dataclass(frozen=True, slots=True)
class SyncResultPage:
    """One latest-run canonical result page."""

    items: tuple[SyncResultFact, ...]
    total: int
    page: int
    limit: int


class IMSyncManagementService:
    """Coordinate workspace-owned integration configuration and manual sync.

    Repository reads may return a deployment-wide EE fallback. This service
    exposes that fallback for status reads but rejects operations that need a
    workspace encryption owner until deployment-owned credential storage has an
    explicit, durable owner identifier.
    """

    _repository: SQLAlchemyIMControlPlaneRepository
    _dispatch_sync_run: SyncRunDispatcher

    def __init__(
        self,
        repository: SQLAlchemyIMControlPlaneRepository,
        dispatch_sync_run: SyncRunDispatcher,
    ) -> None:
        self._repository = repository
        self._dispatch_sync_run = dispatch_sync_run

    def get_integration(self, workspace_id: str) -> IMIntegration | None:
        return self._repository.find_current_integration(WorkspaceId(workspace_id))

    def prepare_credentials(
        self,
        provider: IMProvider,
        values: Mapping[str, object],
    ) -> ProviderCredentials:
        """Validate request credentials against the provider registry."""

        try:
            return create_provider_credentials(provider, values)
        except UnsupportedProviderError as error:
            raise IMSyncManagementError("unsupported_provider", str(error)) from error
        except InvalidProviderCredentialsError as error:
            raise IMSyncManagementError("invalid_credentials", str(error)) from error

    def load_plaintext_credentials(self, workspace_id: str) -> ProviderCredentials | None:
        """Decrypt the current configuration for preserve-value writes."""

        integration = self.get_integration(workspace_id)
        if integration is None:
            return None
        _ensure_workspace_owned(integration)
        try:
            return decrypt_provider_credentials(
                integration.provider_tenant.provider,
                integration.encrypted_credentials.to_mapping(),
                lambda value: encrypter.decrypt_token(workspace_id, value),
            )
        except UnsupportedProviderError as error:
            raise IMSyncManagementError("unsupported_provider", str(error)) from error
        except (InvalidProviderCredentialsError, ValueError) as error:
            raise IMSyncManagementError(
                "invalid_credentials",
                "The stored IM integration credentials are invalid.",
            ) from error

    def test_connection(self, credentials: ProviderCredentials) -> ProviderConnectionDiagnostic:
        return create_provider_client(credentials).test_connection()

    def upsert_integration(
        self,
        *,
        workspace_id: str,
        account_id: str,
        credentials: ProviderCredentials,
        expected_revision: IntegrationRevisionToken | None,
    ) -> IMIntegration:
        """Confirm the provider tenant, then create or CAS-update configuration."""

        current = self.get_integration(workspace_id)
        if current is not None:
            _ensure_workspace_owned(current)
        diagnostic = self.test_connection(credentials)
        if not diagnostic.connected or diagnostic.provider_tenant is None:
            raise IMSyncManagementError("provider_connection_failed", diagnostic.message)

        now = UtcTimestamp.now()
        encrypted = encrypt_provider_credentials(
            credentials,
            lambda value: encrypter.encrypt_token(workspace_id, value),
        )
        if current is None:
            if expected_revision is not None:
                raise IMSyncManagementError("stale_revision", "The IM integration configuration changed.")
            configured = IMIntegration.create(
                integration_id=IntegrationId(str(uuidv7())),
                workspace_id=WorkspaceId(workspace_id),
                provider_tenant=diagnostic.provider_tenant,
                encrypted_credentials=encrypted,
                configured_by_account_id=AccountId(account_id),
                callback_url=None,
                now=now,
            ).record_diagnostics(
                status=IMIntegrationStatus.CONNECTED,
                safe_status_reason=None,
                checked_at=now,
            )
            try:
                return self._repository.create_integration(configured)
            except IMIntegrationCreationError as error:
                raise IMSyncManagementError(
                    "stale_revision",
                    "The IM integration configuration changed.",
                ) from error

        if expected_revision is None or expected_revision != current.revision:
            raise IMSyncManagementError("stale_revision", "The IM integration configuration changed.")
        replacement_id = (
            IntegrationId(str(uuidv7())) if diagnostic.provider_tenant != current.provider_tenant else current.id
        )
        transition = current.reconfigure(
            expected_revision=expected_revision,
            provider_tenant=diagnostic.provider_tenant,
            encrypted_credentials=encrypted,
            configured_by_account_id=AccountId(account_id),
            callback_url=None,
            now=now,
            replacement_integration_id=replacement_id,
        )
        if isinstance(transition, StaleRevision):
            raise IMSyncManagementError("stale_revision", "The IM integration configuration changed.")
        transition = replace(
            transition,
            integration=transition.integration.record_diagnostics(
                status=IMIntegrationStatus.CONNECTED,
                safe_status_reason=None,
                checked_at=now,
            ),
        )
        saved = self._repository.compare_and_swap_configuration(transition)
        if isinstance(saved, StaleRevision):
            raise IMSyncManagementError("stale_revision", "The IM integration configuration changed.")
        return saved

    def delete_integration(
        self,
        *,
        workspace_id: str,
        expected_revision: IntegrationRevisionToken,
    ) -> None:
        """Delete the current workspace-owned integration under complete CAS."""

        current = self.get_integration(workspace_id)
        if current is None:
            raise IMSyncManagementError("stale_revision", "The IM integration configuration changed.")
        _ensure_workspace_owned(current)
        deletion = current.plan_deletion(expected_revision)
        if isinstance(deletion, StaleRevision):
            raise IMSyncManagementError("stale_revision", "The IM integration configuration changed.")
        deleted = self._repository.compare_and_swap_delete(deletion)
        if isinstance(deleted, StaleRevision):
            raise IMSyncManagementError("stale_revision", "The IM integration configuration changed.")

    def trigger_sync(self, *, workspace_id: str, account_id: str) -> IMSyncRun:
        """Create or reuse an active run, re-dispatching recoverable queued work."""

        integration = self.get_integration(workspace_id)
        if integration is None:
            raise IMSyncManagementError("integration_not_configured", "No IM integration is configured.")
        _ensure_workspace_owned(integration)
        decision = self._repository.create_or_get_active_run(
            integration.revision,
            sync_run_id=IMSyncRunId(str(uuidv7())),
            started_by_account_id=AccountId(account_id),
            now=UtcTimestamp.now(),
        )
        if decision.kind is ActiveRunDecisionKind.STALE_REVISION or decision.run is None:
            raise IMSyncManagementError("stale_revision", "The IM integration configuration changed.")
        if decision.run.status is IMSyncRunStatus.QUEUED:
            try:
                self._dispatch_sync_run(str(decision.run.id))
            except (CeleryError, KombuError, RuntimeError) as error:
                logger.exception("Unable to dispatch IM sync run, sync_run_id=%s", decision.run.id)
                raise IMSyncManagementError(
                    "sync_dispatch_failed",
                    "Unable to schedule the IM directory sync.",
                ) from error
        return decision.run

    def get_latest_sync_run(self, workspace_id: str) -> IMSyncRun:
        self._ensure_workspace_data_access(workspace_id)
        run = self._repository.get_latest_sync_run(WorkspaceId(workspace_id))
        if run is None:
            raise IMSyncManagementError("sync_run_not_found", "No IM sync run exists.")
        return run

    def list_latest_results(
        self,
        *,
        workspace_id: str,
        result_type: IMSyncResultType,
        page: int,
        limit: int,
    ) -> SyncResultPage:
        self._ensure_workspace_data_access(workspace_id)
        items, total = self._repository.list_latest_sync_results(
            WorkspaceId(workspace_id),
            result_type=result_type,
            offset=(page - 1) * limit,
            limit=limit,
        )
        return SyncResultPage(items, total, page, limit)

    def _ensure_workspace_data_access(self, workspace_id: str) -> None:
        integration = self.get_integration(workspace_id)
        if integration is not None:
            _ensure_workspace_owned(integration)

    def execute_sync(self, sync_run_id: str) -> None:
        """Execute one claimed run and terminally persist safe credential/provider failures."""

        run_id = IMSyncRunId(sync_run_id)
        claimed = self._repository.mark_sync_run_running(run_id, now=UtcTimestamp.now())
        if claimed is None:
            return
        try:
            integration = self._repository.find_integration(claimed.integration_revision.integration_id)
            if integration is None or integration.revision != claimed.integration_revision:
                raise IMSyncManagementError(
                    "stale_integration_revision",
                    "The IM integration configuration changed before synchronization.",
                )
            _ensure_workspace_owned(integration)
            workspace_id = str(integration.workspace_id)
            credentials = _decrypt_credentials(workspace_id, integration)
            entries = create_provider_client(credentials).list_directory_entries()
            snapshot = self._repository.load_reconciliation_snapshot(run_id)
            plan = SyncReconciler.reconcile(
                sync_run_id=run_id,
                integration_revision=integration.revision,
                provider=integration.provider_tenant.provider,
                entries=entries,
                snapshot=snapshot,
            )
            self._repository.apply_reconciliation(plan, now=UtcTimestamp.now())
        except IMSyncManagementError as error:
            self._repository.fail_sync_run(
                run_id,
                error_code=error.code,
                error_message=str(error),
                now=UtcTimestamp.now(),
            )
            raise
        except PrivkeyNotFoundError as error:
            message = "Stored IM provider credentials are unavailable."
            self._repository.fail_sync_run(
                run_id,
                error_code="provider_credentials_unavailable",
                error_message=message,
                now=UtcTimestamp.now(),
            )
            raise IMSyncManagementError(
                "provider_credentials_unavailable",
                message,
            ) from error
        except (ProviderAdapterError, ValueError) as error:
            self._repository.fail_sync_run(
                run_id,
                error_code="provider_directory_sync_failed",
                error_message="Unable to synchronize the IM provider directory.",
                now=UtcTimestamp.now(),
            )
            raise IMSyncManagementError(
                "provider_directory_sync_failed",
                "Unable to synchronize the IM provider directory.",
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            logger.exception("Unexpected IM directory sync failure, sync_run_id=%s", sync_run_id)
            self._repository.fail_sync_run(
                run_id,
                error_code="im_directory_sync_failed",
                error_message="Unable to synchronize the IM provider directory.",
                now=UtcTimestamp.now(),
            )
            raise IMSyncManagementError(
                "im_directory_sync_failed",
                "Unable to synchronize the IM provider directory.",
            ) from error


def _ensure_workspace_owned(integration: IMIntegration) -> None:
    if integration.workspace_id is None:
        raise IMSyncManagementError(
            "deployment_integration_unsupported",
            "Deployment-wide IM integrations are not supported by this workspace-scoped operation.",
        )


def _decrypt_credentials(workspace_id: str, integration: IMIntegration) -> ProviderCredentials:
    return decrypt_provider_credentials(
        integration.provider_tenant.provider,
        integration.encrypted_credentials.to_mapping(),
        lambda value: encrypter.decrypt_token(workspace_id, value),
    )


__all__ = [
    "IMSyncManagementError",
    "IMSyncManagementService",
    "SyncResultPage",
]
