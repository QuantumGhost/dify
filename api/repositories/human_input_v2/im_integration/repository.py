"""SQLAlchemy IM Control Plane adapter.

Configuration transitions, active-run creation, and reconciliation apply each
own their complete transaction. Integration locks serialize single-active-run
decisions. First creation locks the stable ``Tenant`` or ``DifySetup`` owner
before checking its singleton. ORM records never cross this boundary, and
aggregate relationships are loaded explicitly because their model relationships
use ``lazy="raise"``.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from core.human_input_v2.contact_directory import (
    Contact,
    ContactDirectoryPolicy,
    ContactResolution,
    ContactSnapshot,
)
from core.human_input_v2.entities import (
    IMBindingScope,
    IMProvider,
    IMSyncRemovalReason,
    IMSyncResultType,
    IMSyncRunStatus,
)
from core.human_input_v2.im_integration import (
    ActiveRunDecision,
    ActiveRunDecisionKind,
    ApplyReconciliationResult,
    ApplyReconciliationStatus,
    BindingResolutionKind,
    BindingResolutionResult,
    ConfigurationTransition,
    ConfigurationTransitionKind,
    EffectiveBindingResolver,
    IMBinding,
    IMIdentity,
    IMIntegration,
    IMIntegrationState,
    IMSyncRun,
    IntegrationDeletion,
    IntegrationRevisionToken,
    MatchKind,
    ReconciliationAction,
    ReconciliationPlan,
    ReconciliationSnapshot,
    StaleRevision,
    SyncContactSnapshot,
    SyncIdentitySnapshot,
    SyncResultFact,
)
from core.human_input_v2.shared import (
    AccountId,
    ContactId,
    IMBindingId,
    IMIdentityId,
    IMSyncResultId,
    IMSyncRunId,
    IntegrationId,
    NormalizedEmail,
    UtcTimestamp,
    WorkspaceId,
)
from libs.uuid_utils import uuidv7
from models.account import Tenant
from models.human_input_v2 import (
    HumanInputIMBinding,
    HumanInputIMIdentity,
    HumanInputIMIntegration,
    HumanInputIMSyncResult,
    HumanInputIMSyncRun,
)
from models.model import DifySetup
from repositories.human_input_v2.contact_directory.repository import load_contact_directory_snapshot

from .mappers import (
    binding_from_record,
    binding_to_record,
    identity_from_record,
    identity_to_record,
    integration_from_record,
    integration_to_record,
    sync_result_from_record,
    sync_result_to_record,
    sync_run_from_record,
    sync_run_to_record,
)


@dataclass(frozen=True, slots=True)
class IMIdentitySearchRow:
    """Provider identity plus its current binding state for management search."""

    identity: IMIdentity
    is_bound: bool


class IMBindingMutationError(ValueError):
    """Stable repository rejection for contact-scoped binding mutations."""

    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class IMIntegrationCreationError(ValueError):
    """Stable repository rejection for first-configuration conflicts."""

    code: str

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SQLAlchemyIMControlPlaneRepository:
    """Transactional adapter for configuration, sync, and binding invariants."""

    _session_maker: sessionmaker[Session]

    def __init__(self, session_maker: sessionmaker[Session]) -> None:
        self._session_maker = session_maker

    def find_current_integration(self, workspace_id: WorkspaceId) -> IMIntegration | None:
        """Load the tenant integration or its deployment-wide EE fallback."""

        with self._session_maker() as session, session.begin():
            record = session.scalar(
                select(HumanInputIMIntegration)
                .where(
                    sa.or_(
                        HumanInputIMIntegration.tenant_id == str(workspace_id),
                        HumanInputIMIntegration.tenant_id.is_(None),
                    )
                )
                .order_by(
                    sa.case((HumanInputIMIntegration.tenant_id == str(workspace_id), 0), else_=1),
                    HumanInputIMIntegration.created_at.desc(),
                )
                .limit(1)
            )
            return integration_from_record(record) if record is not None else None

    def get_integration_for_sync_run(self, sync_run_id: IMSyncRunId) -> IMIntegration:
        """Load the exact Integration captured by a persisted sync run."""

        with self._session_maker() as session, session.begin():
            record = session.scalar(
                select(HumanInputIMIntegration)
                .join(
                    HumanInputIMSyncRun,
                    HumanInputIMSyncRun.integration_id == HumanInputIMIntegration.id,
                )
                .where(HumanInputIMSyncRun.id == str(sync_run_id))
            )
            if record is None:
                raise ValueError("integration for sync run not found")
            return integration_from_record(record)

    def find_integration(self, integration_id: IntegrationId) -> IMIntegration | None:
        """Load the current row for an exact persisted integration identity."""

        with self._session_maker() as session, session.begin():
            record = session.get(HumanInputIMIntegration, str(integration_id))
            return integration_from_record(record) if record is not None else None

    def compare_and_swap_diagnostics(self, integration: IMIntegration) -> IMIntegration | StaleRevision:
        """Persist connection diagnostics without advancing config revision."""

        with self._session_maker() as session, session.begin():
            record = session.scalar(self._locked_integration_statement(integration.revision))
            if record is None:
                return StaleRevision(
                    integration.revision,
                    self._current_revision(session, integration.id),
                )
            record.status = integration.status
            record.safe_status_reason = integration.safe_status_reason
            record.last_checked_at = (
                integration.last_checked_at.value if integration.last_checked_at is not None else None
            )
            record.updated_at = integration.updated_at.value
            session.flush()
            return integration_from_record(record)

    def get_latest_sync_run(self, workspace_id: WorkspaceId) -> IMSyncRun | None:
        """Return only the newest run owned by the current workspace."""

        with self._session_maker() as session, session.begin():
            integration_id = self._tenant_integration_id_statement(workspace_id).scalar_subquery()
            record = session.scalar(
                select(HumanInputIMSyncRun)
                .where(HumanInputIMSyncRun.integration_id == integration_id)
                .order_by(HumanInputIMSyncRun.created_at.desc(), HumanInputIMSyncRun.id.desc())
                .limit(1)
            )
            return sync_run_from_record(record) if record is not None else None

    def list_latest_sync_results(
        self,
        workspace_id: WorkspaceId,
        *,
        result_type: IMSyncResultType,
        offset: int,
        limit: int,
    ) -> tuple[tuple[SyncResultFact, ...], int]:
        """Page one canonical result bucket from the latest workspace-owned run."""

        if offset < 0 or limit < 1:
            raise ValueError("invalid result page")
        with self._session_maker() as session, session.begin():
            integration_id = self._tenant_integration_id_statement(workspace_id).scalar_subquery()
            latest_run_id = session.scalar(
                select(HumanInputIMSyncRun.id)
                .where(HumanInputIMSyncRun.integration_id == integration_id)
                .order_by(HumanInputIMSyncRun.created_at.desc(), HumanInputIMSyncRun.id.desc())
                .limit(1)
            )
            if latest_run_id is None:
                return (), 0
            predicates = (
                HumanInputIMSyncResult.sync_run_id == latest_run_id,
                HumanInputIMSyncResult.result_type == result_type,
            )
            total = session.scalar(select(sa.func.count(HumanInputIMSyncResult.id)).where(*predicates)) or 0
            records = session.scalars(
                select(HumanInputIMSyncResult)
                .where(*predicates)
                .order_by(HumanInputIMSyncResult.created_at, HumanInputIMSyncResult.id)
                .offset(offset)
                .limit(limit)
            ).all()
            return tuple(sync_result_from_record(record) for record in records), total

    def list_current_identities(
        self,
        workspace_id: WorkspaceId,
        *,
        keyword: str | None,
        offset: int,
        limit: int,
    ) -> tuple[tuple[IMIdentitySearchRow, ...], int]:
        """Page synced identities from only the workspace-owned integration."""

        if offset < 0 or limit < 1:
            raise ValueError("invalid identity page")
        with self._session_maker() as session, session.begin():
            integration_id = self._tenant_integration_id_statement(workspace_id).scalar_subquery()
            predicates: list[sa.ColumnElement[bool]] = [HumanInputIMIdentity.integration_id == integration_id]
            normalized_keyword = keyword.strip().casefold() if keyword is not None else ""
            if normalized_keyword:
                predicates.append(
                    sa.or_(
                        sa.func.lower(HumanInputIMIdentity.provider_user_id).contains(
                            normalized_keyword,
                            autoescape=True,
                        ),
                        HumanInputIMIdentity.normalized_name.contains(normalized_keyword, autoescape=True),
                        HumanInputIMIdentity.normalized_email.contains(normalized_keyword, autoescape=True),
                    )
                )
            total = session.scalar(select(sa.func.count(HumanInputIMIdentity.id)).where(*predicates)) or 0
            is_bound = sa.exists().where(
                HumanInputIMBinding.integration_id == HumanInputIMIdentity.integration_id,
                HumanInputIMBinding.im_identity_id == HumanInputIMIdentity.id,
                HumanInputIMBinding.provider == HumanInputIMIdentity.provider,
                sa.or_(
                    sa.and_(
                        HumanInputIMBinding.scope == IMBindingScope.ORGANIZATION,
                        HumanInputIMBinding.scope_id == HumanInputIMIdentity.integration_id,
                    ),
                    sa.and_(
                        HumanInputIMBinding.scope == IMBindingScope.WORKSPACE,
                        HumanInputIMBinding.scope_id == str(workspace_id),
                    ),
                ),
            )
            rows = session.execute(
                select(HumanInputIMIdentity, is_bound.label("is_bound"))
                .where(*predicates)
                .order_by(
                    sa.func.coalesce(
                        HumanInputIMIdentity.normalized_name,
                        sa.func.lower(HumanInputIMIdentity.provider_user_id),
                    ),
                    HumanInputIMIdentity.id,
                )
                .offset(offset)
                .limit(limit)
            ).all()
            return (
                tuple(
                    IMIdentitySearchRow(
                        identity=identity_from_record(record),
                        is_bound=is_bound_value,
                    )
                    for record, is_bound_value in rows
                ),
                total,
            )

    def set_contact_binding(
        self,
        *,
        workspace_id: WorkspaceId,
        contact_id: ContactId,
        identity_id: IMIdentityId,
        scope: IMBindingScope,
        bound_by_account_id: AccountId,
        now: UtcTimestamp,
    ) -> IMBinding:
        """Create or replace one scoped binding without modifying the other scope."""

        try:
            with self._session_maker() as session, session.begin():
                integration = self._load_current_integration_record(session, workspace_id, for_update=True)
                if integration is None:
                    raise IMBindingMutationError("integration_not_configured")
                if integration.tenant_id is None:
                    raise IMBindingMutationError("deployment_integration_unsupported")
                self._require_current_contact(session, workspace_id, contact_id)
                identity = session.scalar(
                    select(HumanInputIMIdentity)
                    .where(
                        HumanInputIMIdentity.id == str(identity_id),
                        HumanInputIMIdentity.integration_id == integration.id,
                        HumanInputIMIdentity.provider == integration.provider,
                    )
                    .with_for_update()
                )
                if identity is None:
                    raise IMBindingMutationError("identity_not_found")

                scope_id = integration.id if scope is IMBindingScope.ORGANIZATION else str(workspace_id)
                identity_binding = session.scalar(
                    select(HumanInputIMBinding)
                    .where(
                        HumanInputIMBinding.integration_id == integration.id,
                        HumanInputIMBinding.scope == scope,
                        HumanInputIMBinding.scope_id == scope_id,
                        HumanInputIMBinding.im_identity_id == identity.id,
                    )
                    .with_for_update()
                )
                if identity_binding is not None and identity_binding.contact_id != str(contact_id):
                    raise IMBindingMutationError("identity_already_bound")

                contact_binding = session.scalar(
                    select(HumanInputIMBinding)
                    .where(
                        HumanInputIMBinding.integration_id == integration.id,
                        HumanInputIMBinding.scope == scope,
                        HumanInputIMBinding.scope_id == scope_id,
                        HumanInputIMBinding.contact_id == str(contact_id),
                        HumanInputIMBinding.provider == integration.provider,
                    )
                    .with_for_update()
                )
                if contact_binding is None:
                    contact_binding = HumanInputIMBinding(
                        integration_id=integration.id,
                        scope=scope,
                        scope_id=scope_id,
                        contact_id=str(contact_id),
                        im_identity_id=identity.id,
                        provider=integration.provider,
                        bound_by_account_id=str(bound_by_account_id),
                    )
                    session.add(contact_binding)
                else:
                    contact_binding.im_identity_id = identity.id
                    contact_binding.bound_by_account_id = str(bound_by_account_id)
                    contact_binding.updated_at = now.value
                session.flush()
                return binding_from_record(contact_binding)
        except IMBindingMutationError:
            raise
        except IntegrityError as error:
            raise IMBindingMutationError("binding_conflict") from error

    def delete_contact_binding(
        self,
        *,
        workspace_id: WorkspaceId,
        contact_id: ContactId,
        scope: IMBindingScope,
        binding_id: IMBindingId | None = None,
    ) -> None:
        """Delete one organization binding or the current workspace override only."""

        if scope is IMBindingScope.ORGANIZATION and binding_id is None:
            raise ValueError("organization binding deletion requires binding_id")
        with self._session_maker() as session, session.begin():
            integration = self._load_current_integration_record(session, workspace_id, for_update=True)
            if integration is None:
                raise IMBindingMutationError("integration_not_configured")
            if integration.tenant_id is None:
                raise IMBindingMutationError("deployment_integration_unsupported")
            self._require_current_contact(session, workspace_id, contact_id)
            scope_id = integration.id if scope is IMBindingScope.ORGANIZATION else str(workspace_id)
            predicates: list[sa.ColumnElement[bool]] = [
                HumanInputIMBinding.integration_id == integration.id,
                HumanInputIMBinding.scope == scope,
                HumanInputIMBinding.scope_id == scope_id,
                HumanInputIMBinding.contact_id == str(contact_id),
                HumanInputIMBinding.provider == integration.provider,
            ]
            if binding_id is not None:
                predicates.append(HumanInputIMBinding.id == str(binding_id))
            record = session.scalar(select(HumanInputIMBinding).where(*predicates).with_for_update())
            if record is None:
                if scope is IMBindingScope.WORKSPACE and binding_id is None:
                    return
                raise IMBindingMutationError("binding_not_found")
            session.delete(record)

    def create_integration(self, integration: IMIntegration) -> IMIntegration:
        """Create the first configuration after serializing its owner scope."""

        with self._session_maker() as session, session.begin():
            if integration.workspace_id is None:
                self._lock_deployment_owner(session)
                owner_predicate = HumanInputIMIntegration.tenant_id.is_(None)
                conflict_message = "deployment-wide IM integration already exists"
            else:
                self._lock_workspace_owner(session, integration.workspace_id)
                owner_predicate = HumanInputIMIntegration.tenant_id == str(integration.workspace_id)
                conflict_message = "workspace IM integration already exists"
            existing_integration_id = session.scalar(select(HumanInputIMIntegration.id).where(owner_predicate).limit(1))
            if existing_integration_id is not None:
                raise IMIntegrationCreationError("integration_already_configured", conflict_message)
            record = integration_to_record(integration)
            session.add(record)
            session.flush()
            return integration_from_record(record)

    def compare_and_swap_configuration(self, transition: ConfigurationTransition) -> IMIntegration | StaleRevision:
        """Apply a complete-token rotation or replacement in one transaction."""

        with self._session_maker() as session, session.begin():
            current = session.scalar(self._locked_integration_statement(transition.expected_revision))
            if current is None:
                return StaleRevision(
                    transition.expected_revision,
                    self._current_revision(session, transition.expected_revision.integration_id),
                )

            if transition.kind is ConfigurationTransitionKind.CREDENTIAL_ROTATION:
                self._copy_integration_values(current, transition.integration)
                session.flush()
                return integration_from_record(current)

            session.execute(
                sa.delete(HumanInputIMBinding).where(
                    HumanInputIMBinding.integration_id == str(transition.expected_revision.integration_id)
                )
            )
            session.execute(
                sa.delete(HumanInputIMIdentity).where(
                    HumanInputIMIdentity.integration_id == str(transition.expected_revision.integration_id)
                )
            )
            session.delete(current)
            session.flush()
            replacement = integration_to_record(transition.integration)
            session.add(replacement)
            session.flush()
            return integration_from_record(replacement)

    def compare_and_swap_delete(self, deletion: IntegrationDeletion | StaleRevision) -> None | StaleRevision:
        """Delete current configuration and current children under complete CAS."""

        if isinstance(deletion, StaleRevision):
            return deletion
        with self._session_maker() as session, session.begin():
            current = session.scalar(self._locked_integration_statement(deletion.expected_revision))
            if current is None:
                return StaleRevision(
                    deletion.expected_revision,
                    self._current_revision(session, deletion.expected_revision.integration_id),
                )
            integration_id = str(deletion.expected_revision.integration_id)
            session.execute(sa.delete(HumanInputIMBinding).where(HumanInputIMBinding.integration_id == integration_id))
            session.execute(
                sa.delete(HumanInputIMIdentity).where(HumanInputIMIdentity.integration_id == integration_id)
            )
            session.delete(current)
        return None

    def create_or_get_active_run(
        self,
        integration_revision: IntegrationRevisionToken,
        *,
        sync_run_id: IMSyncRunId,
        started_by_account_id: AccountId | None,
        now: UtcTimestamp,
    ) -> ActiveRunDecision:
        """Serialize trigger decisions by locking the owning Integration row."""

        with self._session_maker() as session, session.begin():
            integration = session.scalar(self._locked_integration_statement(integration_revision))
            if integration is None:
                return ActiveRunDecision(
                    kind=ActiveRunDecisionKind.STALE_REVISION,
                    run=None,
                    stale_revision=StaleRevision(
                        integration_revision,
                        self._current_revision(session, integration_revision.integration_id),
                    ),
                )
            existing = session.scalar(
                select(HumanInputIMSyncRun)
                .where(
                    HumanInputIMSyncRun.integration_id == str(integration_revision.integration_id),
                    HumanInputIMSyncRun.status.in_((IMSyncRunStatus.QUEUED, IMSyncRunStatus.RUNNING)),
                )
                .order_by(HumanInputIMSyncRun.created_at, HumanInputIMSyncRun.id)
                .limit(1)
            )
            if existing is not None:
                return ActiveRunDecision(ActiveRunDecisionKind.EXISTING_ACTIVE, sync_run_from_record(existing))
            run = IMSyncRun.create(
                sync_run_id=sync_run_id,
                integration_revision=integration_revision,
                provider=integration.provider,
                started_by_account_id=started_by_account_id,
                now=now,
            )
            record = sync_run_to_record(run)
            session.add(record)
            session.flush()
            return ActiveRunDecision(ActiveRunDecisionKind.CREATED, sync_run_from_record(record))

    def mark_sync_run_running(self, sync_run_id: IMSyncRunId, *, now: UtcTimestamp) -> IMSyncRun | None:
        """Atomically claim a queued run, or return ``None`` if already claimed."""

        with self._session_maker() as session, session.begin():
            record = session.scalar(
                select(HumanInputIMSyncRun).where(HumanInputIMSyncRun.id == str(sync_run_id)).with_for_update()
            )
            if record is None:
                raise ValueError("sync run not found")
            if record.status is not IMSyncRunStatus.QUEUED:
                return None
            run = sync_run_from_record(record).start(now)
            record.status = run.status
            record.started_at = run.started_at.value if run.started_at is not None else None
            record.updated_at = run.updated_at.value
            session.flush()
            return sync_run_from_record(record)

    def fail_sync_run(
        self,
        sync_run_id: IMSyncRunId,
        *,
        error_code: str,
        error_message: str,
        now: UtcTimestamp,
    ) -> IMSyncRun:
        """Finish one active run with a safe terminal error and diagnostic fact."""

        with self._session_maker() as session, session.begin():
            record = session.scalar(
                select(HumanInputIMSyncRun).where(HumanInputIMSyncRun.id == str(sync_run_id)).with_for_update()
            )
            if record is None:
                raise ValueError("sync run not found")
            if record.status in (IMSyncRunStatus.SUCCEEDED, IMSyncRunStatus.FAILED):
                return sync_run_from_record(record)
            fact = SyncResultFact(
                id=IMSyncResultId(str(uuidv7())),
                integration_id=IntegrationId(record.integration_id),
                sync_run_id=sync_run_id,
                result_type=IMSyncResultType.FAILED,
                provider_user_id=None,
                display_name=None,
                email=None,
                normalized_email=None,
                contact_id=None,
                identity_id=None,
                binding_id=None,
                removal_reason=None,
                reason_code=error_code,
                reason_message=error_message,
                directory_entry_payload=None,
                contact_snapshot=None,
                identity_snapshot=None,
                created_at=now,
                updated_at=now,
            )
            self._append_result_record(session, fact)
            record.status = IMSyncRunStatus.FAILED
            record.failed_count = 1
            record.started_at = record.started_at or now.value
            record.finished_at = now.value
            record.error_code = error_code
            record.error_message = error_message
            record.updated_at = now.value
            session.flush()
            return sync_run_from_record(record)

    def load_reconciliation_snapshot(self, sync_run_id: IMSyncRunId) -> ReconciliationSnapshot:
        """Load current identities, bindings, and owner-scoped Contact facts."""

        with self._session_maker() as session, session.begin():
            run = session.get_one(HumanInputIMSyncRun, str(sync_run_id))
            integration = session.get_one(HumanInputIMIntegration, run.integration_id)
            identity_records = session.scalars(
                select(HumanInputIMIdentity).where(
                    HumanInputIMIdentity.integration_id == run.integration_id,
                    HumanInputIMIdentity.provider == run.provider,
                )
            ).all()
            binding_records = session.scalars(
                select(HumanInputIMBinding).where(HumanInputIMBinding.integration_id == run.integration_id)
            ).all()
            contacts: tuple[ContactSnapshot, ...] = ()
            if integration.tenant_id is not None:
                directory = load_contact_directory_snapshot(session, WorkspaceId(integration.tenant_id))
                contacts = tuple(
                    ContactSnapshot(
                        contact,
                        ContactDirectoryPolicy.resolve_for_workspace(directory, contact.id)
                        in (ContactResolution.WORKSPACE, ContactResolution.PLATFORM),
                    )
                    for contact in directory.contacts
                )
            return ReconciliationSnapshot(
                identities=tuple(identity_from_record(record) for record in identity_records),
                bindings=tuple(binding_from_record(record) for record in binding_records),
                contacts=contacts,
            )

    def apply_reconciliation(self, plan: ReconciliationPlan, *, now: UtcTimestamp) -> ApplyReconciliationResult:
        """Idempotently apply one plan using the persisted run capture as authority."""

        with self._session_maker() as session, session.begin():
            run_record = session.scalar(
                select(HumanInputIMSyncRun).where(HumanInputIMSyncRun.id == str(plan.sync_run_id)).with_for_update()
            )
            if run_record is None:
                raise ValueError("sync run not found")
            captured_revision = IntegrationRevisionToken(
                IntegrationId(run_record.integration_id),
                run_record.integration_config_version,
            )
            if plan.integration_revision != captured_revision:
                raise ValueError("sync run revision does not match plan")
            if plan.provider is not run_record.provider:
                raise ValueError("sync run provider does not match plan")

            existing_results = self._load_result_records(session, plan.sync_run_id)
            if run_record.status in (IMSyncRunStatus.SUCCEEDED, IMSyncRunStatus.FAILED):
                return ApplyReconciliationResult(
                    ApplyReconciliationStatus.ALREADY_APPLIED,
                    sync_run_from_record(run_record),
                    tuple(sync_result_from_record(record) for record in existing_results),
                )

            integration_record = session.scalar(self._locked_integration_statement(captured_revision))
            if integration_record is None or integration_record.provider is not run_record.provider:
                stale_result = self._stale_result(plan, now)
                self._append_result_record(session, stale_result)
                run_record.status = IMSyncRunStatus.FAILED
                run_record.failed_count = 1
                run_record.started_at = run_record.started_at or now.value
                run_record.finished_at = now.value
                run_record.error_code = "stale_integration_revision"
                run_record.error_message = "Integration configuration changed before reconciliation apply."
                run_record.updated_at = now.value
                session.flush()
                return ApplyReconciliationResult(
                    ApplyReconciliationStatus.STALE_REVISION,
                    sync_run_from_record(run_record),
                    (stale_result,),
                )

            results: list[SyncResultFact] = []
            workspace_id = (
                WorkspaceId(integration_record.tenant_id) if integration_record.tenant_id is not None else None
            )
            for action in plan.actions:
                result = self._apply_action(session, plan, action, now, workspace_id=workspace_id)
                self._append_result_record(session, result)
                results.append(result)
            for identity_id in plan.removed_identity_ids:
                removal_results = self._remove_identity(
                    session,
                    plan,
                    identity_id,
                    now,
                    workspace_id=workspace_id,
                )
                for removal_result in removal_results:
                    self._append_result_record(session, removal_result)
                    results.append(removal_result)

            run_record.status = IMSyncRunStatus.SUCCEEDED
            run_record.added_count = sum(result.result_type is IMSyncResultType.ADDED for result in results)
            run_record.not_matched_count = sum(result.result_type is IMSyncResultType.NOT_MATCHED for result in results)
            run_record.failed_count = sum(result.result_type is IMSyncResultType.FAILED for result in results)
            run_record.removed_count = sum(result.result_type is IMSyncResultType.REMOVED for result in results)
            run_record.skipped_count = sum(result.result_type is IMSyncResultType.SKIPPED for result in results)
            run_record.started_at = run_record.started_at or now.value
            run_record.finished_at = now.value
            run_record.updated_at = now.value
            session.flush()
            return ApplyReconciliationResult(
                ApplyReconciliationStatus.APPLIED,
                sync_run_from_record(run_record),
                tuple(results),
            )

    def load_integration_state(self, integration_id: IntegrationId) -> IMIntegrationState:
        """Eagerly load and map an Integration with all modeled child relationships."""

        with self._session_maker() as session, session.begin():
            record = session.scalar(
                select(HumanInputIMIntegration)
                .where(HumanInputIMIntegration.id == str(integration_id))
                .options(
                    selectinload(HumanInputIMIntegration.identities).selectinload(HumanInputIMIdentity.bindings),
                    selectinload(HumanInputIMIntegration.sync_runs).selectinload(HumanInputIMSyncRun.results),
                )
            )
            if record is None:
                raise ValueError("integration not found")
            identity_records = tuple(record.identities)
            run_records = tuple(record.sync_runs)
            return IMIntegrationState(
                integration=integration_from_record(record),
                identities=tuple(identity_from_record(item) for item in identity_records),
                bindings=tuple(
                    binding_from_record(binding) for identity in identity_records for binding in identity.bindings
                ),
                sync_runs=tuple(sync_run_from_record(item) for item in run_records),
                sync_results=tuple(sync_result_from_record(result) for run in run_records for result in run.results),
            )

    def resolve_effective_binding(
        self,
        *,
        integration_id: IntegrationId,
        provider: IMProvider,
        workspace_id: WorkspaceId,
        contact_id: ContactId,
    ) -> BindingResolutionResult:
        """Validate Integration ownership before loading consumer-safe binding facts."""

        with self._session_maker() as session, session.begin():
            integration_record = session.scalar(
                select(HumanInputIMIntegration).where(
                    HumanInputIMIntegration.id == str(integration_id),
                    sa.or_(
                        HumanInputIMIntegration.tenant_id == str(workspace_id),
                        HumanInputIMIntegration.tenant_id.is_(None),
                    ),
                )
            )
            if integration_record is None or integration_record.provider is not provider:
                return BindingResolutionResult(BindingResolutionKind.INVALID_BINDING, None)
            integration = integration_from_record(integration_record)
            contact, resolution = self._load_current_contact(
                session,
                workspace_id,
                contact_id,
                for_update=False,
            )
            if contact is None or resolution not in (ContactResolution.WORKSPACE, ContactResolution.PLATFORM):
                return BindingResolutionResult(BindingResolutionKind.NOT_AVAILABLE, None)
            identities = tuple(
                identity_from_record(record)
                for record in session.scalars(
                    select(HumanInputIMIdentity).where(
                        HumanInputIMIdentity.integration_id == str(integration_id),
                        HumanInputIMIdentity.provider == provider,
                    )
                ).all()
            )
            bindings = tuple(
                binding_from_record(record)
                for record in session.scalars(
                    select(HumanInputIMBinding).where(
                        HumanInputIMBinding.integration_id == str(integration_id),
                        HumanInputIMBinding.provider == provider,
                    )
                ).all()
            )
            return EffectiveBindingResolver.resolve(
                integration_revision=integration.revision,
                provider_tenant=integration.provider_tenant,
                workspace_id=workspace_id,
                contact=ContactSnapshot(contact, True),
                identities=identities,
                bindings=bindings,
            )

    def append_sync_results(self, results: tuple[SyncResultFact, ...]) -> None:
        """Append diagnostic facts in their own explicit transaction."""

        with self._session_maker() as session, session.begin():
            for result in results:
                self._append_result_record(session, result)

    @staticmethod
    def _locked_integration_statement(
        revision: IntegrationRevisionToken,
    ) -> sa.Select[tuple[HumanInputIMIntegration]]:
        """Build the complete CAS predicate and row lock used by write paths."""

        return (
            select(HumanInputIMIntegration)
            .where(
                HumanInputIMIntegration.id == str(revision.integration_id),
                HumanInputIMIntegration.config_version == revision.config_version,
            )
            .with_for_update()
        )

    @staticmethod
    def _effective_current_integration_id_statement(
        workspace_id: WorkspaceId,
    ) -> sa.Select[tuple[str]]:
        """Mirror current-integration precedence inside latest-run queries."""

        return (
            select(HumanInputIMIntegration.id)
            .where(
                sa.or_(
                    HumanInputIMIntegration.tenant_id == str(workspace_id),
                    HumanInputIMIntegration.tenant_id.is_(None),
                )
            )
            .order_by(
                sa.case((HumanInputIMIntegration.tenant_id == str(workspace_id), 0), else_=1),
                HumanInputIMIntegration.created_at.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def _tenant_integration_id_statement(
        workspace_id: WorkspaceId,
    ) -> sa.Select[tuple[str]]:
        """Select only the tenant-owned integration for console data routes."""

        return select(HumanInputIMIntegration.id).where(HumanInputIMIntegration.tenant_id == str(workspace_id)).limit(1)

    def _load_current_integration_record(
        self,
        session: Session,
        workspace_id: WorkspaceId,
        *,
        for_update: bool,
    ) -> HumanInputIMIntegration | None:
        statement = select(HumanInputIMIntegration).where(
            HumanInputIMIntegration.id
            == self._effective_current_integration_id_statement(workspace_id).scalar_subquery()
        )
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)

    @staticmethod
    def _load_current_contact(
        session: Session,
        workspace_id: WorkspaceId,
        contact_id: ContactId,
        *,
        for_update: bool,
    ) -> tuple[Contact | None, ContactResolution]:
        directory = load_contact_directory_snapshot(
            session,
            workspace_id,
            contact_id=contact_id,
            for_update=for_update,
        )
        contact = directory.find(contact_id)
        if contact is None:
            return None, ContactResolution.ABSENT
        return contact, ContactDirectoryPolicy.resolve_for_workspace(directory, contact_id)

    @classmethod
    def _require_current_contact(
        cls,
        session: Session,
        workspace_id: WorkspaceId,
        contact_id: ContactId,
    ) -> Contact:
        contact, resolution = cls._load_current_contact(
            session,
            workspace_id,
            contact_id,
            for_update=True,
        )
        if contact is None or resolution is ContactResolution.ABSENT:
            raise IMBindingMutationError("contact_not_found")
        if resolution is ContactResolution.EXTERNAL:
            raise IMBindingMutationError("external_contact_not_supported")
        if resolution not in (ContactResolution.WORKSPACE, ContactResolution.PLATFORM):
            raise IMBindingMutationError("contact_not_found")
        return contact

    @staticmethod
    def _current_revision(session: Session, integration_id: IntegrationId) -> IntegrationRevisionToken | None:
        record = session.get(HumanInputIMIntegration, str(integration_id))
        if record is None:
            return None
        return IntegrationRevisionToken(IntegrationId(record.id), record.config_version)

    @staticmethod
    def _lock_deployment_owner(session: Session) -> None:
        """Serialize EE singleton decisions on the deployment's stable owner."""

        setup_version = session.scalars(select(DifySetup.version).with_for_update()).one_or_none()
        if setup_version is None:
            raise ValueError("deployment setup row is required for deployment-wide IM integration")

    @staticmethod
    def _lock_workspace_owner(session: Session, workspace_id: WorkspaceId) -> None:
        """Serialize workspace singleton decisions on the stable Tenant row."""

        tenant_id = session.scalar(select(Tenant.id).where(Tenant.id == str(workspace_id)).with_for_update())
        if tenant_id is None:
            raise IMIntegrationCreationError(
                "workspace_not_found",
                "workspace owner for IM integration not found",
            )

    @staticmethod
    def _copy_integration_values(record: HumanInputIMIntegration, integration: IMIntegration) -> None:
        mapped = integration_to_record(integration)
        record.provider = mapped.provider
        record.encrypted_credentials = mapped.encrypted_credentials
        record.tenant_id = mapped.tenant_id
        record.provider_tenant_id = mapped.provider_tenant_id
        record.status = mapped.status
        record.config_version = mapped.config_version
        record.configured_by_account_id = mapped.configured_by_account_id
        record.callback_url = mapped.callback_url
        record.safe_status_reason = mapped.safe_status_reason
        record.last_checked_at = mapped.last_checked_at
        record.updated_at = mapped.updated_at

    @staticmethod
    def _load_result_records(session: Session, sync_run_id: IMSyncRunId) -> list[HumanInputIMSyncResult]:
        return list(
            session.scalars(
                select(HumanInputIMSyncResult)
                .where(HumanInputIMSyncResult.sync_run_id == str(sync_run_id))
                .order_by(HumanInputIMSyncResult.created_at, HumanInputIMSyncResult.id)
            ).all()
        )

    def _apply_action(
        self,
        session: Session,
        plan: ReconciliationPlan,
        action: ReconciliationAction,
        now: UtcTimestamp,
        *,
        workspace_id: WorkspaceId | None,
    ) -> SyncResultFact:
        identity_record: HumanInputIMIdentity | None = None
        binding_record: HumanInputIMBinding | None = None
        contact: Contact | None = None
        contact_is_available = False
        if action.contact_id is not None and workspace_id is not None:
            contact, resolution = self._load_current_contact(
                session,
                workspace_id,
                action.contact_id,
                for_update=True,
            )
            contact_is_available = resolution in (ContactResolution.WORKSPACE, ContactResolution.PLATFORM)

        if action.identity_id is not None:
            identity_record = session.scalar(
                select(HumanInputIMIdentity).where(
                    HumanInputIMIdentity.id == str(action.identity_id),
                    HumanInputIMIdentity.integration_id == str(plan.integration_revision.integration_id),
                )
            )
            if identity_record is None:
                raise ValueError("matched identity no longer exists")
            self._copy_entry_to_identity(identity_record, action, plan, now)
            if action.binding_id is not None:
                binding_record = session.scalar(
                    select(HumanInputIMBinding).where(
                        HumanInputIMBinding.id == str(action.binding_id),
                        HumanInputIMBinding.integration_id == str(plan.integration_revision.integration_id),
                        HumanInputIMBinding.im_identity_id == identity_record.id,
                        HumanInputIMBinding.provider == plan.provider,
                    )
                )
        elif action.match_kind is MatchKind.NORMALIZED_EMAIL and action.contact_id is not None and contact_is_available:
            identity = IMIdentity.create(
                identity_id=IMIdentityId(str(uuidv7())),
                integration_id=plan.integration_revision.integration_id,
                provider=plan.provider,
                provider_user_id=action.entry.provider_user_id,
                display_name=action.entry.display_name,
                email=action.entry.email,
                raw_payload=action.entry.raw_payload.to_mapping(),
                last_seen_sync_run_id=plan.sync_run_id,
                last_seen_at=now,
                now=now,
            )
            identity_record = identity_to_record(identity)
            session.add(identity_record)
            binding = IMBinding.create(
                binding_id=IMBindingId(str(uuidv7())),
                integration_id=plan.integration_revision.integration_id,
                scope=IMBindingScope.ORGANIZATION,
                scope_id=str(plan.integration_revision.integration_id),
                contact_id=action.contact_id,
                identity_id=identity.id,
                provider=plan.provider,
                bound_by_account_id=None,
                now=now,
            )
            binding_record = binding_to_record(binding)
            session.add(binding_record)

        effective_match_kind = (
            MatchKind.UNMATCHED
            if action.match_kind is MatchKind.NORMALIZED_EMAIL and not contact_is_available
            else action.match_kind
        )
        result_type = (
            IMSyncResultType.NOT_MATCHED
            if effective_match_kind is MatchKind.UNMATCHED
            else IMSyncResultType.ADDED
            if effective_match_kind is MatchKind.NORMALIZED_EMAIL
            else IMSyncResultType.SKIPPED
        )
        return SyncResultFact(
            id=IMSyncResultId(str(uuidv7())),
            integration_id=plan.integration_revision.integration_id,
            sync_run_id=plan.sync_run_id,
            result_type=result_type,
            provider_user_id=action.entry.provider_user_id,
            display_name=action.entry.display_name,
            email=action.entry.email,
            normalized_email=action.entry.normalized_email,
            contact_id=action.contact_id if contact_is_available else None,
            identity_id=IMIdentityId(identity_record.id) if identity_record is not None else None,
            binding_id=IMBindingId(binding_record.id) if binding_record is not None else None,
            removal_reason=None,
            reason_code=(
                "existing_provider_identity"
                if result_type is IMSyncResultType.SKIPPED
                else "contact_unavailable"
                if action.match_kind is MatchKind.NORMALIZED_EMAIL and not contact_is_available
                else None
            ),
            reason_message=None,
            directory_entry_payload=action.entry.raw_payload,
            contact_snapshot=(
                SyncContactSnapshot(
                    contact_id=contact.id,
                    name=contact.name,
                    email=contact.email,
                    avatar_file_id=contact.avatar_file_id,
                )
                if contact is not None and contact_is_available
                else None
            ),
            identity_snapshot=None,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _copy_entry_to_identity(
        record: HumanInputIMIdentity,
        action: ReconciliationAction,
        plan: ReconciliationPlan,
        now: UtcTimestamp,
    ) -> None:
        record.provider_user_id = action.entry.provider_user_id
        record.display_name = action.entry.display_name
        record.normalized_name = action.entry.display_name.casefold() if action.entry.display_name else None
        record.email = action.entry.email
        record.normalized_email = str(action.entry.normalized_email) if action.entry.normalized_email else None
        from models.human_input_v2 import IMIdentityRawPayload

        record.raw_payload = IMIdentityRawPayload(action.entry.raw_payload.to_mapping())
        record.last_seen_sync_run_id = str(plan.sync_run_id)
        record.last_seen_at = now.value
        record.updated_at = now.value

    def _remove_identity(
        self,
        session: Session,
        plan: ReconciliationPlan,
        identity_id: IMIdentityId,
        now: UtcTimestamp,
        *,
        workspace_id: WorkspaceId | None,
    ) -> tuple[SyncResultFact, ...]:
        """Remove current state while exposing only currently available contacts."""

        record = session.scalar(
            select(HumanInputIMIdentity).where(
                HumanInputIMIdentity.id == str(identity_id),
                HumanInputIMIdentity.integration_id == str(plan.integration_revision.integration_id),
            )
        )
        if record is None:
            return ()
        binding_records = tuple(
            session.scalars(
                select(HumanInputIMBinding)
                .where(
                    HumanInputIMBinding.integration_id == str(plan.integration_revision.integration_id),
                    HumanInputIMBinding.im_identity_id == record.id,
                )
                .order_by(HumanInputIMBinding.created_at, HumanInputIMBinding.id)
            ).all()
        )
        bindings_for_results: tuple[HumanInputIMBinding | None, ...] = binding_records or (None,)
        results: list[SyncResultFact] = []
        for binding in bindings_for_results:
            contact: Contact | None = None
            contact_is_available = False
            if binding is not None and workspace_id is not None:
                contact, resolution = self._load_current_contact(
                    session,
                    workspace_id,
                    ContactId(binding.contact_id),
                    for_update=True,
                )
                contact_is_available = resolution in (ContactResolution.WORKSPACE, ContactResolution.PLATFORM)
            results.append(
                SyncResultFact(
                    id=IMSyncResultId(str(uuidv7())),
                    integration_id=plan.integration_revision.integration_id,
                    sync_run_id=plan.sync_run_id,
                    result_type=IMSyncResultType.REMOVED,
                    provider_user_id=record.provider_user_id,
                    display_name=record.display_name,
                    email=record.email,
                    normalized_email=(
                        NormalizedEmail(record.normalized_email) if record.normalized_email is not None else None
                    ),
                    contact_id=(
                        ContactId(binding.contact_id) if binding is not None and contact_is_available else None
                    ),
                    identity_id=identity_id,
                    binding_id=IMBindingId(binding.id) if binding is not None else None,
                    removal_reason=IMSyncRemovalReason.NOT_PRESENT_IN_DIRECTORY,
                    reason_code="not_present_in_directory",
                    reason_message=None,
                    directory_entry_payload=None,
                    contact_snapshot=(
                        SyncContactSnapshot(
                            contact_id=contact.id,
                            name=contact.name,
                            email=contact.email,
                            avatar_file_id=contact.avatar_file_id,
                        )
                        if contact is not None and contact_is_available
                        else None
                    ),
                    identity_snapshot=SyncIdentitySnapshot(
                        identity_id=identity_id,
                        provider=record.provider,
                        provider_user_id=record.provider_user_id,
                        display_name=record.display_name,
                        email=record.email,
                    ),
                    created_at=now,
                    updated_at=now,
                )
            )
        for binding in binding_records:
            session.delete(binding)
        session.delete(record)
        return tuple(results)

    @staticmethod
    def _stale_result(plan: ReconciliationPlan, now: UtcTimestamp) -> SyncResultFact:
        return SyncResultFact(
            id=IMSyncResultId(str(uuidv7())),
            integration_id=plan.integration_revision.integration_id,
            sync_run_id=plan.sync_run_id,
            result_type=IMSyncResultType.FAILED,
            provider_user_id=None,
            display_name=None,
            email=None,
            normalized_email=None,
            contact_id=None,
            identity_id=None,
            binding_id=None,
            removal_reason=None,
            reason_code="stale_integration_revision",
            reason_message="Integration configuration changed before reconciliation apply.",
            directory_entry_payload=None,
            contact_snapshot=None,
            identity_snapshot=None,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _append_result_record(session: Session, result: SyncResultFact) -> None:
        session.add(sync_result_to_record(result))
