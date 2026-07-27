"""Transaction contract tests for the SQLAlchemy IM Control Plane adapter."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.human_input_v2.contact_directory import Contact, ContactDirectoryPolicy, ContactResolution
from core.human_input_v2.entities import (
    IMBindingScope,
    IMIntegrationStatus,
    IMProvider,
    IMSyncResultType,
    IMSyncRunStatus,
)
from core.human_input_v2.im_integration import (
    ActiveRunDecisionKind,
    ApplyReconciliationResult,
    ApplyReconciliationStatus,
    BindingResolutionKind,
    ConfigurationTransition,
    EncryptedCredentials,
    IMBinding,
    IMIdentity,
    IMIntegration,
    IntegrationDeletion,
    IntegrationRevisionToken,
    MatchKind,
    ProviderDirectoryEntry,
    ProviderTenantIdentity,
    ReconciliationAction,
    ReconciliationPlan,
    StaleRevision,
)
from core.human_input_v2.shared import (
    AccountId,
    ContactId,
    IMBindingId,
    IMIdentityId,
    IMSyncResultId,
    IMSyncRunId,
    IntegrationId,
    UtcTimestamp,
    WorkspaceId,
)
from models.account import Account, AccountStatus, Tenant, TenantAccountJoin, TenantAccountRole
from models.human_input_v2 import (
    HumanInputContact,
    HumanInputIMBinding,
    HumanInputIMIdentity,
    HumanInputIMIntegration,
    HumanInputIMSyncResult,
    HumanInputIMSyncRun,
    HumanInputPlatformContactWorkspaceEntry,
)
from models.model import DifySetup
from repositories.human_input_v2.contact_directory.mappers import contact_to_record
from repositories.human_input_v2.contact_directory.repository import SQLAlchemyContactDirectoryRepository
from repositories.human_input_v2.im_integration.mappers import binding_to_record, identity_to_record
from repositories.human_input_v2.im_integration.repository import (
    IMBindingMutationError,
    IMIntegrationCreationError,
    SQLAlchemyIMControlPlaneRepository,
)

_NOW = UtcTimestamp(datetime(2026, 7, 25, 8, tzinfo=UTC))
_LATER = UtcTimestamp(datetime(2026, 7, 25, 9, tzinfo=UTC))
_WORKSPACE_ID = WorkspaceId("workspace-1")


@pytest.fixture
def repository_context(
    sqlite_engine: Engine,
) -> Iterator[tuple[SQLAlchemyIMControlPlaneRepository, sessionmaker[Session]]]:
    tables = [
        DifySetup.__table__,
        Account.__table__,
        Tenant.__table__,
        TenantAccountJoin.__table__,
        HumanInputContact.__table__,
        HumanInputPlatformContactWorkspaceEntry.__table__,
        HumanInputIMIntegration.__table__,
        HumanInputIMIdentity.__table__,
        HumanInputIMBinding.__table__,
        HumanInputIMSyncRun.__table__,
        HumanInputIMSyncResult.__table__,
    ]
    HumanInputIMIntegration.metadata.create_all(sqlite_engine, tables=tables)
    session_maker = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    with session_maker.begin() as session:
        session.add(DifySetup(version="test-deployment"))
        for workspace_id in (
            "workspace-1",
            "workspace-2",
            "workspace-tenant-1",
            "workspace-tenant-2",
        ):
            tenant = Tenant(name=workspace_id)
            tenant.id = workspace_id
            session.add(tenant)
        for account_id in ("account-1", "account-2"):
            account = Account(
                name=account_id,
                email=f"{account_id}@example.com",
                status=AccountStatus.ACTIVE,
            )
            account.id = account_id
            session.add(account)
            session.add(
                TenantAccountJoin(
                    tenant_id=str(_WORKSPACE_ID),
                    account_id=account_id,
                    role=TenantAccountRole.NORMAL,
                )
            )
    return SQLAlchemyIMControlPlaneRepository(session_maker), session_maker


def _credentials(secret: str = "ciphertext") -> EncryptedCredentials:
    return EncryptedCredentials.from_mapping({"app_id": "app-1", "encrypted_app_secret": secret})


def _integration(
    integration_id: str = "integration-1",
    *,
    workspace_id: WorkspaceId | None = _WORKSPACE_ID,
) -> IMIntegration:
    return IMIntegration.create(
        integration_id=IntegrationId(integration_id),
        workspace_id=workspace_id,
        provider_tenant=ProviderTenantIdentity(IMProvider.FEISHU, "provider-tenant-1"),
        encrypted_credentials=_credentials(),
        configured_by_account_id=AccountId("account-1"),
        callback_url=None,
        now=_NOW,
    )


def _persist_current_contact(
    session_maker: sessionmaker[Session],
    invalidation: str,
) -> tuple[Contact, str]:
    account_id = f"account-race-{invalidation}"
    account = Account(
        name=account_id,
        email=f"{account_id}@example.com",
        status=AccountStatus.ACTIVE,
    )
    account.id = account_id
    if invalidation == "platform_detach":
        contact = Contact.organization_account(
            contact_id=ContactId("contact-race"),
            account_id=AccountId(account_id),
            name="Race Reviewer",
            email="race@example.com",
            now=_NOW,
        )
    else:
        contact = Contact.workspace_member(
            contact_id=ContactId("contact-race"),
            workspace_id=_WORKSPACE_ID,
            account_id=AccountId(account_id),
            name="Race Reviewer",
            email="race@example.com",
            now=_NOW,
        )
    with session_maker.begin() as session:
        session.add(account)
        session.add(contact_to_record(contact))
        if invalidation == "platform_detach":
            session.add(
                HumanInputPlatformContactWorkspaceEntry(
                    tenant_id=str(_WORKSPACE_ID),
                    contact_id=str(contact.id),
                    added_by_account_id="account-1",
                )
            )
        else:
            session.add(
                TenantAccountJoin(
                    tenant_id=str(_WORKSPACE_ID),
                    account_id=account_id,
                    role=TenantAccountRole.NORMAL,
                )
            )
    return contact, account_id


def _invalidate_current_contact(
    session_maker: sessionmaker[Session],
    invalidation: str,
    *,
    contact: Contact,
    account_id: str,
) -> None:
    with session_maker.begin() as session:
        if invalidation == "membership_removed":
            session.execute(
                sa.delete(TenantAccountJoin).where(
                    TenantAccountJoin.tenant_id == str(_WORKSPACE_ID),
                    TenantAccountJoin.account_id == account_id,
                )
            )
        elif invalidation == "hard_deleted":
            session.execute(sa.delete(HumanInputContact).where(HumanInputContact.id == str(contact.id)))
        elif invalidation == "platform_detach":
            session.execute(
                sa.delete(HumanInputPlatformContactWorkspaceEntry).where(
                    HumanInputPlatformContactWorkspaceEntry.tenant_id == str(_WORKSPACE_ID),
                    HumanInputPlatformContactWorkspaceEntry.contact_id == str(contact.id),
                )
            )
        elif invalidation == "account_disabled":
            session.get_one(Account, account_id).status = AccountStatus.BANNED
        else:
            raise AssertionError(f"unsupported invalidation: {invalidation}")


def test_deployment_integration_creation_is_singleton_while_tenant_integrations_remain_scoped(
    repository_context,
) -> None:
    repository, session_maker = repository_context

    deployment_integration = repository.create_integration(_integration(workspace_id=None))
    first_tenant = repository.create_integration(
        _integration("integration-tenant-1", workspace_id=WorkspaceId("workspace-tenant-1"))
    )
    second_tenant = repository.create_integration(
        _integration("integration-tenant-2", workspace_id=WorkspaceId("workspace-tenant-2"))
    )

    with pytest.raises(IMIntegrationCreationError, match="deployment-wide IM integration already exists") as conflict:
        repository.create_integration(_integration("integration-deployment-2", workspace_id=None))

    assert conflict.value.code == "integration_already_configured"
    assert deployment_integration.workspace_id is None
    assert first_tenant.workspace_id == WorkspaceId("workspace-tenant-1")
    assert second_tenant.workspace_id == WorkspaceId("workspace-tenant-2")
    with session_maker() as session:
        assert (
            session.scalar(
                select(sa.func.count(HumanInputIMIntegration.id)).where(HumanInputIMIntegration.tenant_id.is_(None))
            )
            == 1
        )


def test_workspace_first_creation_rechecks_existing_configuration_under_owner_scope(
    repository_context,
) -> None:
    repository, session_maker = repository_context
    first = repository.create_integration(_integration())

    with pytest.raises(IMIntegrationCreationError, match="workspace IM integration already exists") as conflict:
        repository.create_integration(_integration("integration-loser"))

    assert conflict.value.code == "integration_already_configured"
    with session_maker() as session:
        records = session.scalars(
            select(HumanInputIMIntegration).where(
                HumanInputIMIntegration.tenant_id == str(_WORKSPACE_ID),
            )
        ).all()
    assert [record.id for record in records] == [str(first.id)]


def test_deployment_integration_creation_requires_stable_setup_owner(repository_context) -> None:
    repository, session_maker = repository_context
    with session_maker.begin() as session:
        session.execute(sa.delete(DifySetup))

    with pytest.raises(ValueError, match="setup row"):
        repository.create_integration(_integration(workspace_id=None))


def test_latest_run_and_results_prefer_workspace_integration_over_newer_deployment_fallback(
    repository_context,
) -> None:
    repository, _ = repository_context
    deployment = repository.create_integration(
        _integration("integration-deployment", workspace_id=None),
    )
    workspace = repository.create_integration(
        _integration("integration-workspace", workspace_id=_WORKSPACE_ID),
    )
    workspace_decision = repository.create_or_get_active_run(
        workspace.revision,
        sync_run_id=IMSyncRunId("run-workspace"),
        started_by_account_id=None,
        now=_NOW,
    )
    deployment_decision = repository.create_or_get_active_run(
        deployment.revision,
        sync_run_id=IMSyncRunId("run-deployment"),
        started_by_account_id=None,
        now=_LATER,
    )
    assert workspace_decision.run is not None
    assert deployment_decision.run is not None
    repository.fail_sync_run(
        workspace_decision.run.id,
        error_code="workspace_failure",
        error_message="Workspace failure",
        now=_LATER,
    )
    repository.fail_sync_run(
        deployment_decision.run.id,
        error_code="deployment_failure",
        error_message="Deployment failure",
        now=_LATER,
    )

    latest = repository.get_latest_sync_run(_WORKSPACE_ID)
    results, total = repository.list_latest_sync_results(
        _WORKSPACE_ID,
        result_type=IMSyncResultType.FAILED,
        offset=0,
        limit=20,
    )

    assert latest is not None
    assert latest.id == IMSyncRunId("run-workspace")
    assert total == 1
    assert [result.reason_code for result in results] == ["workspace_failure"]


@pytest.mark.parametrize("workspace_id", [_WORKSPACE_ID, WorkspaceId("workspace-2")])
def test_latest_run_and_results_hide_deployment_fallback_data(
    repository_context,
    workspace_id: WorkspaceId,
) -> None:
    repository, session_maker = repository_context
    deployment = repository.create_integration(_integration("integration-deployment", workspace_id=None))
    decision = repository.create_or_get_active_run(
        deployment.revision,
        sync_run_id=IMSyncRunId("run-deployment"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert decision.run is not None
    repository.fail_sync_run(
        decision.run.id,
        error_code="deployment_failure",
        error_message="Deployment failure",
        now=_LATER,
    )
    with session_maker() as session:
        assert session.scalar(select(sa.func.count(HumanInputIMSyncResult.id))) == 1

    latest = repository.get_latest_sync_run(workspace_id)
    results = repository.list_latest_sync_results(
        workspace_id,
        result_type=IMSyncResultType.FAILED,
        offset=0,
        limit=20,
    )

    assert latest is None
    assert results == ((), 0)


def test_integration_lookup_diagnostics_and_sync_run_lifecycle(repository_context) -> None:
    repository, _ = repository_context
    assert repository.find_current_integration(_WORKSPACE_ID) is None
    assert repository.get_latest_sync_run(_WORKSPACE_ID) is None
    assert repository.list_latest_sync_results(
        _WORKSPACE_ID,
        result_type=IMSyncResultType.FAILED,
        offset=0,
        limit=20,
    ) == ((), 0)
    with pytest.raises(ValueError, match="invalid result page"):
        repository.list_latest_sync_results(
            _WORKSPACE_ID,
            result_type=IMSyncResultType.FAILED,
            offset=-1,
            limit=20,
        )

    integration = repository.create_integration(_integration())
    assert repository.find_current_integration(_WORKSPACE_ID) == integration
    connected = integration.record_diagnostics(
        status=IMIntegrationStatus.CONNECTED,
        safe_status_reason="Connected",
        checked_at=_LATER,
    )
    assert repository.compare_and_swap_diagnostics(connected) == connected
    stale_diagnostics = repository.compare_and_swap_diagnostics(replace(connected, config_version=9))
    assert isinstance(stale_diagnostics, StaleRevision)

    decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-lifecycle"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert decision.run is not None
    assert repository.get_integration_for_sync_run(decision.run.id) == connected
    with pytest.raises(ValueError, match="integration for sync run"):
        repository.get_integration_for_sync_run(IMSyncRunId("run-missing"))
    with pytest.raises(ValueError, match="sync run not found"):
        repository.mark_sync_run_running(IMSyncRunId("run-missing"), now=_LATER)
    with pytest.raises(ValueError, match="sync run not found"):
        repository.fail_sync_run(
            IMSyncRunId("run-missing"),
            error_code="failure",
            error_message="Failure",
            now=_LATER,
        )

    running = repository.mark_sync_run_running(decision.run.id, now=_LATER)
    assert running is not None
    assert running.status is IMSyncRunStatus.RUNNING
    assert repository.mark_sync_run_running(decision.run.id, now=_LATER) is None
    failed = repository.fail_sync_run(
        decision.run.id,
        error_code="provider_failure",
        error_message="Provider failure",
        now=_LATER,
    )
    assert failed.status is IMSyncRunStatus.FAILED
    assert (
        repository.fail_sync_run(
            decision.run.id,
            error_code="ignored",
            error_message="Ignored",
            now=_LATER,
        )
        == failed
    )
    results, total = repository.list_latest_sync_results(
        _WORKSPACE_ID,
        result_type=IMSyncResultType.FAILED,
        offset=0,
        limit=20,
    )
    assert total == 1
    repository.append_sync_results((replace(results[0], id=IMSyncResultId("result-appended")),))
    assert (
        repository.list_latest_sync_results(
            _WORKSPACE_ID,
            result_type=IMSyncResultType.FAILED,
            offset=0,
            limit=20,
        )[1]
        == 2
    )


def _identity(
    integration_id: IntegrationId,
    *,
    identity_id: str = "identity-1",
    provider_user_id: str = "provider-user-1",
    display_name: str = "Reviewer",
    email: str = "reviewer@example.com",
) -> IMIdentity:
    return IMIdentity.create(
        identity_id=IMIdentityId(identity_id),
        integration_id=integration_id,
        provider=IMProvider.FEISHU,
        provider_user_id=provider_user_id,
        display_name=display_name,
        email=email,
        raw_payload={},
        last_seen_sync_run_id=None,
        last_seen_at=_NOW,
        now=_NOW,
    )


def _binding(integration_id: IntegrationId) -> IMBinding:
    return IMBinding.create(
        binding_id=IMBindingId("binding-1"),
        integration_id=integration_id,
        scope=IMBindingScope.ORGANIZATION,
        scope_id=str(integration_id),
        contact_id=ContactId("contact-1"),
        identity_id=IMIdentityId("identity-1"),
        provider=IMProvider.FEISHU,
        bound_by_account_id=None,
        now=_NOW,
    )


def _persist_current_children(session_maker: sessionmaker[Session], integration_id: IntegrationId) -> None:
    with session_maker.begin() as session:
        session.add(identity_to_record(_identity(integration_id)))
        session.add(binding_to_record(_binding(integration_id)))


def test_configuration_cas_rotation_preserves_children_and_rejects_stale_revision(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    _persist_current_children(session_maker, integration.id)
    decision = integration.reconfigure(
        expected_revision=integration.revision,
        provider_tenant=integration.provider_tenant,
        encrypted_credentials=_credentials("rotated"),
        configured_by_account_id=AccountId("account-2"),
        callback_url=None,
        now=_LATER,
    )
    assert isinstance(decision, ConfigurationTransition)

    updated = repository.compare_and_swap_configuration(decision)

    assert isinstance(updated, IMIntegration)
    assert updated.revision == IntegrationRevisionToken(integration.id, 2)
    with session_maker() as session:
        assert session.scalar(sa.select(sa.func.count(HumanInputIMIdentity.id))) == 1
        assert session.scalar(sa.select(sa.func.count(HumanInputIMBinding.id))) == 1

    stale = repository.compare_and_swap_configuration(decision)
    assert stale == StaleRevision(expected=integration.revision, actual=updated.revision)


def test_provider_replacement_invalidates_current_children_in_same_transaction(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    _persist_current_children(session_maker, integration.id)
    contact = Contact.organization_account(
        contact_id=ContactId("contact-1"),
        account_id=AccountId("account-1"),
        name="Reviewer",
        email="different@example.com",
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(contact_to_record(contact))
    before_replacement = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )
    decision = integration.reconfigure(
        expected_revision=integration.revision,
        provider_tenant=ProviderTenantIdentity(IMProvider.SLACK, "slack-workspace"),
        encrypted_credentials=EncryptedCredentials.from_mapping(
            {
                "client_id": "client-1",
                "encrypted_client_secret": "secret",
                "encrypted_signing_secret": "signing",
                "encrypted_bot_token": "token",
            }
        ),
        configured_by_account_id=AccountId("account-2"),
        callback_url=None,
        now=_LATER,
        replacement_integration_id=IntegrationId("integration-2"),
    )
    assert isinstance(decision, ConfigurationTransition)

    replacement = repository.compare_and_swap_configuration(decision)
    old_effective = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )
    replacement_effective = repository.resolve_effective_binding(
        integration_id=replacement.id,
        provider=IMProvider.SLACK,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )

    assert isinstance(replacement, IMIntegration)
    assert replacement.id == IntegrationId("integration-2")
    assert before_replacement.kind is BindingResolutionKind.ORGANIZATION_BINDING
    assert old_effective.kind is BindingResolutionKind.INVALID_BINDING
    assert replacement_effective.kind is BindingResolutionKind.NOT_AVAILABLE
    with session_maker() as session:
        assert session.get(HumanInputIMIntegration, "integration-1") is None
        assert session.get(HumanInputIMIntegration, "integration-2") is not None
        assert session.scalar(sa.select(sa.func.count(HumanInputIMIdentity.id))) == 0
        assert session.scalar(sa.select(sa.func.count(HumanInputIMBinding.id))) == 0


def test_delete_requires_complete_current_revision(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())

    stale = repository.compare_and_swap_delete(integration.plan_deletion(IntegrationRevisionToken(integration.id, 9)))
    assert isinstance(stale, StaleRevision)
    assert repository.compare_and_swap_delete(integration.plan_deletion(integration.revision)) is None
    with session_maker() as session:
        assert session.get(HumanInputIMIntegration, str(integration.id)) is None


def test_delete_reports_missing_current_integration(repository_context) -> None:
    repository, _ = repository_context
    revision = IntegrationRevisionToken(IntegrationId("integration-missing"), 1)

    result = repository.compare_and_swap_delete(IntegrationDeletion(revision))

    assert result == StaleRevision(expected=revision, actual=None)


def test_active_run_creation_returns_existing_state_and_rejects_stale_trigger(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())

    first = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=AccountId("account-1"),
        now=_NOW,
    )
    second = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-2"),
        started_by_account_id=AccountId("account-2"),
        now=_LATER,
    )
    stale = repository.create_or_get_active_run(
        IntegrationRevisionToken(integration.id, 9),
        sync_run_id=IMSyncRunId("run-3"),
        started_by_account_id=None,
        now=_LATER,
    )

    assert first.kind is ActiveRunDecisionKind.CREATED
    assert second.kind is ActiveRunDecisionKind.EXISTING_ACTIVE
    assert second.run == first.run
    assert stale.kind is ActiveRunDecisionKind.STALE_REVISION
    with session_maker() as session:
        assert session.scalar(sa.select(sa.func.count(HumanInputIMSyncRun.id))) == 1


def test_reconciliation_apply_is_idempotent_and_eager_state_is_mapped(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=AccountId("account-1"),
        now=_NOW,
    )
    assert run_decision.run is not None
    contact = Contact.organization_account(
        contact_id=ContactId("contact-1"),
        account_id=AccountId("account-1"),
        name="Reviewer",
        email="reviewer@example.com",
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(contact_to_record(contact))
    entry = ProviderDirectoryEntry.create(
        provider_user_id="provider-user-1",
        display_name="Reviewer",
        email="reviewer@example.com",
        raw_payload={"provider": "value"},
    )
    plan = ReconciliationPlan(
        sync_run_id=run_decision.run.id,
        integration_revision=integration.revision,
        provider=IMProvider.FEISHU,
        actions=(
            ReconciliationAction(
                entry=entry,
                match_kind=MatchKind.NORMALIZED_EMAIL,
                identity_id=None,
                binding_id=None,
                contact_id=contact.id,
            ),
        ),
        removed_identity_ids=(),
    )

    applied = repository.apply_reconciliation(plan, now=_LATER)
    retried = repository.apply_reconciliation(plan, now=_LATER)
    state = repository.load_integration_state(integration.id)

    assert applied.status is ApplyReconciliationStatus.APPLIED
    assert applied.run.status is IMSyncRunStatus.SUCCEEDED
    assert retried.status is ApplyReconciliationStatus.ALREADY_APPLIED
    assert retried.results == applied.results
    assert len(state.identities) == 1
    assert len(state.bindings) == 1
    assert len(state.sync_runs) == 1
    assert len(state.sync_results) == 1
    with session_maker() as session:
        assert session.scalar(sa.select(sa.func.count(HumanInputIMIdentity.id))) == 1
        assert session.scalar(sa.select(sa.func.count(HumanInputIMBinding.id))) == 1
        assert session.scalar(sa.select(sa.func.count(HumanInputIMSyncResult.id))) == 1


def test_stale_reconciliation_appends_diagnostic_without_current_state_mutation(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert run_decision.run is not None
    rotation = integration.reconfigure(
        expected_revision=integration.revision,
        provider_tenant=integration.provider_tenant,
        encrypted_credentials=_credentials("rotated"),
        configured_by_account_id=None,
        callback_url=None,
        now=_LATER,
    )
    assert isinstance(rotation, ConfigurationTransition)
    repository.compare_and_swap_configuration(rotation)
    plan = ReconciliationPlan(
        sync_run_id=run_decision.run.id,
        integration_revision=integration.revision,
        provider=IMProvider.FEISHU,
        actions=(),
        removed_identity_ids=(),
    )

    result = repository.apply_reconciliation(plan, now=_LATER)

    assert result.status is ApplyReconciliationStatus.STALE_REVISION
    assert result.results[0].reason_code == "stale_integration_revision"
    with session_maker() as session:
        assert session.scalar(sa.select(sa.func.count(HumanInputIMIdentity.id))) == 0
        assert session.scalar(sa.select(sa.func.count(HumanInputIMBinding.id))) == 0
        assert session.scalar(sa.select(sa.func.count(HumanInputIMSyncResult.id))) == 1


@pytest.mark.parametrize(
    ("integration_revision", "provider", "message"),
    [
        (IntegrationRevisionToken(IntegrationId("integration-1"), 2), IMProvider.FEISHU, "revision"),
        (IntegrationRevisionToken(IntegrationId("integration-1"), 1), IMProvider.SLACK, "provider"),
    ],
)
def test_reconciliation_plan_must_match_persisted_run_capture(
    repository_context,
    integration_revision: IntegrationRevisionToken,
    provider: IMProvider,
    message: str,
) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert run_decision.run is not None
    plan = ReconciliationPlan(
        sync_run_id=run_decision.run.id,
        integration_revision=integration_revision,
        provider=provider,
        actions=(),
        removed_identity_ids=(),
    )

    with pytest.raises(ValueError, match=message):
        repository.apply_reconciliation(plan, now=_LATER)

    with session_maker() as session:
        run = session.get_one(HumanInputIMSyncRun, str(run_decision.run.id))
        assert run.status is IMSyncRunStatus.QUEUED
        assert session.scalar(select(sa.func.count(HumanInputIMSyncResult.id))) == 0


def test_reconciliation_requires_persisted_run(repository_context) -> None:
    repository, _ = repository_context
    plan = ReconciliationPlan(
        sync_run_id=IMSyncRunId("run-missing"),
        integration_revision=IntegrationRevisionToken(IntegrationId("integration-missing"), 1),
        provider=IMProvider.FEISHU,
        actions=(),
        removed_identity_ids=(),
    )

    with pytest.raises(ValueError, match="sync run not found"):
        repository.apply_reconciliation(plan, now=_NOW)


def test_reconciliation_rejects_current_provider_that_differs_from_persisted_run(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert run_decision.run is not None
    with session_maker.begin() as session:
        session.get_one(HumanInputIMIntegration, str(integration.id)).provider = IMProvider.SLACK
    plan = ReconciliationPlan(
        sync_run_id=run_decision.run.id,
        integration_revision=run_decision.run.integration_revision,
        provider=run_decision.run.provider,
        actions=(),
        removed_identity_ids=(),
    )

    result = repository.apply_reconciliation(plan, now=_LATER)

    assert result.status is ApplyReconciliationStatus.STALE_REVISION
    assert result.results[0].reason_code == "stale_integration_revision"


def test_snapshot_load_and_effective_binding_use_mapped_owner_scoped_facts(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert run_decision.run is not None
    contact = Contact.organization_account(
        contact_id=ContactId("contact-1"),
        account_id=AccountId("account-1"),
        name="Reviewer",
        email="reviewer@example.com",
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(contact_to_record(contact))
        session.add(identity_to_record(_identity(integration.id)))
        session.add(binding_to_record(_binding(integration.id)))

    snapshot = repository.load_reconciliation_snapshot(run_decision.run.id)
    effective = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )

    assert len(snapshot.identities) == 1
    assert len(snapshot.bindings) == 1
    assert {item.contact.id for item in snapshot.contacts} == {contact.id}
    assert effective.kind is BindingResolutionKind.ORGANIZATION_BINDING
    assert effective.binding is not None
    assert effective.binding.provider_user_id == "provider-user-1"


def test_missing_integration_state_and_contact_are_reported(repository_context) -> None:
    repository, _ = repository_context
    with pytest.raises(ValueError, match="integration not found"):
        repository.load_integration_state(IntegrationId("integration-missing"))

    integration = repository.create_integration(_integration())
    effective = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=ContactId("contact-missing"),
    )

    assert effective.kind is BindingResolutionKind.NOT_AVAILABLE


def test_identity_search_hides_deployment_fallback_identity_from_all_workspaces(repository_context) -> None:
    repository, session_maker = repository_context
    deployment = repository.create_integration(_integration("integration-deployment", workspace_id=None))
    identity = _identity(deployment.id)
    other_workspace_id = WorkspaceId("workspace-2")
    other_workspace_override = IMBinding.create(
        binding_id=IMBindingId("binding-workspace-2"),
        integration_id=deployment.id,
        scope=IMBindingScope.WORKSPACE,
        scope_id=str(other_workspace_id),
        contact_id=ContactId("contact-2"),
        identity_id=identity.id,
        provider=IMProvider.FEISHU,
        bound_by_account_id=None,
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(identity_to_record(identity))
        session.add(binding_to_record(other_workspace_override))

    workspace_one_rows, workspace_one_total = repository.list_current_identities(
        _WORKSPACE_ID,
        keyword=None,
        offset=0,
        limit=20,
    )
    workspace_two_rows, workspace_two_total = repository.list_current_identities(
        other_workspace_id,
        keyword=None,
        offset=0,
        limit=20,
    )

    assert (workspace_one_rows, workspace_one_total) == ((), 0)
    assert (workspace_two_rows, workspace_two_total) == ((), 0)


def test_identity_search_matches_provider_id_display_name_and_email_with_stable_paging(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    identities = (
        _identity(
            integration.id,
            identity_id="identity-alpha",
            provider_user_id="OPEN-ALPHA",
            display_name="Alpha Reviewer",
            email="alpha@example.com",
        ),
        _identity(
            integration.id,
            identity_id="identity-beta",
            provider_user_id="open-beta",
            display_name="Beta Operator",
            email="beta@example.com",
        ),
        _identity(
            integration.id,
            identity_id="identity-gamma",
            provider_user_id="open-gamma",
            display_name="Gamma Reviewer",
            email="gamma-search@example.com",
        ),
    )
    with session_maker.begin() as session:
        session.add_all([identity_to_record(identity) for identity in identities])

    searches = {
        "open-alpha": IMIdentityId("identity-alpha"),
        "BETA OPERATOR": IMIdentityId("identity-beta"),
        "GAMMA-SEARCH@EXAMPLE.COM": IMIdentityId("identity-gamma"),
    }
    for keyword, expected_identity_id in searches.items():
        rows, total = repository.list_current_identities(
            _WORKSPACE_ID,
            keyword=keyword,
            offset=0,
            limit=20,
        )
        assert total == 1
        assert [row.identity.id for row in rows] == [expected_identity_id]

    second_page, total = repository.list_current_identities(
        _WORKSPACE_ID,
        keyword="reviewer",
        offset=1,
        limit=1,
    )

    assert total == 2
    assert [row.identity.id for row in second_page] == [IMIdentityId("identity-gamma")]
    with pytest.raises(ValueError, match="invalid identity page"):
        repository.list_current_identities(_WORKSPACE_ID, keyword=None, offset=0, limit=0)


def test_contact_binding_mutations_preserve_scope_precedence_and_reset_fallback(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    contact = Contact.organization_account(
        contact_id=ContactId("contact-1"),
        account_id=AccountId("account-1"),
        name="Reviewer",
        email="no-fallback@example.com",
        now=_NOW,
    )
    organization_identity = _identity(integration.id)
    override_identity = _identity(
        integration.id,
        identity_id="identity-override",
        provider_user_id="provider-user-override",
        display_name="Override Reviewer",
        email="override@example.com",
    )
    with session_maker.begin() as session:
        session.add(contact_to_record(contact))
        session.add_all(
            [
                identity_to_record(organization_identity),
                identity_to_record(override_identity),
            ]
        )

    organization_binding = repository.set_contact_binding(
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
        identity_id=organization_identity.id,
        scope=IMBindingScope.ORGANIZATION,
        bound_by_account_id=AccountId("account-1"),
        now=_NOW,
    )
    organization_effective = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )
    repository.set_contact_binding(
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
        identity_id=override_identity.id,
        scope=IMBindingScope.WORKSPACE,
        bound_by_account_id=AccountId("account-2"),
        now=_LATER,
    )
    override_effective = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )
    repository.delete_contact_binding(
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
        scope=IMBindingScope.WORKSPACE,
    )
    reset_effective = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )
    repository.delete_contact_binding(
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
        scope=IMBindingScope.ORGANIZATION,
        binding_id=organization_binding.id,
    )
    deleted_effective = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )

    assert organization_effective.kind is BindingResolutionKind.ORGANIZATION_BINDING
    assert override_effective.kind is BindingResolutionKind.WORKSPACE_OVERRIDE
    assert override_effective.binding is not None
    assert override_effective.binding.identity_id == override_identity.id
    assert reset_effective.kind is BindingResolutionKind.ORGANIZATION_BINDING
    assert reset_effective.binding is not None
    assert reset_effective.binding.binding_id == organization_binding.id
    assert deleted_effective.kind is BindingResolutionKind.NOT_AVAILABLE


def test_contact_binding_mutations_reject_invalid_current_state(repository_context) -> None:
    repository, session_maker = repository_context
    with pytest.raises(IMBindingMutationError) as no_integration:
        repository.set_contact_binding(
            workspace_id=_WORKSPACE_ID,
            contact_id=ContactId("contact-1"),
            identity_id=IMIdentityId("identity-1"),
            scope=IMBindingScope.ORGANIZATION,
            bound_by_account_id=AccountId("account-1"),
            now=_NOW,
        )
    assert no_integration.value.code == "integration_not_configured"

    integration = repository.create_integration(_integration())
    contact = Contact.organization_account(
        contact_id=ContactId("contact-1"),
        account_id=AccountId("account-1"),
        name="Reviewer",
        email="reviewer@example.com",
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(contact_to_record(contact))
    with pytest.raises(IMBindingMutationError) as no_identity:
        repository.set_contact_binding(
            workspace_id=_WORKSPACE_ID,
            contact_id=ContactId("contact-1"),
            identity_id=IMIdentityId("identity-missing"),
            scope=IMBindingScope.ORGANIZATION,
            bound_by_account_id=AccountId("account-1"),
            now=_NOW,
        )
    assert no_identity.value.code == "identity_not_found"

    identity = _identity(integration.id)
    second_contact = Contact.organization_account(
        contact_id=ContactId("contact-2"),
        account_id=AccountId("account-2"),
        name="Second Reviewer",
        email="second-reviewer@example.com",
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(identity_to_record(identity))
        session.add(contact_to_record(second_contact))
    repository.set_contact_binding(
        workspace_id=_WORKSPACE_ID,
        contact_id=ContactId("contact-1"),
        identity_id=identity.id,
        scope=IMBindingScope.ORGANIZATION,
        bound_by_account_id=AccountId("account-1"),
        now=_NOW,
    )
    with pytest.raises(IMBindingMutationError) as already_bound:
        repository.set_contact_binding(
            workspace_id=_WORKSPACE_ID,
            contact_id=ContactId("contact-2"),
            identity_id=identity.id,
            scope=IMBindingScope.ORGANIZATION,
            bound_by_account_id=AccountId("account-2"),
            now=_LATER,
        )
    assert already_bound.value.code == "identity_already_bound"

    with pytest.raises(IMBindingMutationError) as binding_missing:
        repository.delete_contact_binding(
            workspace_id=_WORKSPACE_ID,
            contact_id=ContactId("contact-1"),
            scope=IMBindingScope.ORGANIZATION,
            binding_id=IMBindingId("binding-missing"),
        )
    assert binding_missing.value.code == "binding_not_found"
    with pytest.raises(ValueError, match="requires binding_id"):
        repository.delete_contact_binding(
            workspace_id=_WORKSPACE_ID,
            contact_id=ContactId("contact-1"),
            scope=IMBindingScope.ORGANIZATION,
        )


@pytest.mark.parametrize("scope", [IMBindingScope.ORGANIZATION, IMBindingScope.WORKSPACE])
@pytest.mark.parametrize("operation", ["set", "delete"])
def test_deployment_fallback_rejects_all_binding_mutations_without_database_side_effect(
    repository_context,
    scope: IMBindingScope,
    operation: str,
) -> None:
    repository, session_maker = repository_context
    repository.create_integration(_integration(workspace_id=None))

    if operation == "set":
        with pytest.raises(IMBindingMutationError) as error:
            repository.set_contact_binding(
                workspace_id=_WORKSPACE_ID,
                contact_id=ContactId("contact-1"),
                identity_id=IMIdentityId("identity-1"),
                scope=scope,
                bound_by_account_id=AccountId("account-1"),
                now=_NOW,
            )
    else:
        binding_id = IMBindingId("binding-1") if scope is IMBindingScope.ORGANIZATION else None
        with pytest.raises(IMBindingMutationError) as error:
            repository.delete_contact_binding(
                workspace_id=_WORKSPACE_ID,
                contact_id=ContactId("contact-1"),
                scope=scope,
                binding_id=binding_id,
            )

    assert error.value.code == "deployment_integration_unsupported"
    with session_maker() as session:
        assert session.scalar(select(sa.func.count(HumanInputIMBinding.id))) == 0
        assert session.scalar(select(sa.func.count(HumanInputIMIdentity.id))) == 0


@pytest.mark.parametrize(
    "invalidation",
    ["membership_removed", "hard_deleted", "platform_detach", "account_disabled"],
)
@pytest.mark.parametrize("operation", ["set", "delete"])
def test_binding_mutation_rechecks_current_contact_after_snapshot(
    repository_context,
    invalidation: str,
    operation: str,
) -> None:
    repository, session_maker = repository_context
    contact_repository = SQLAlchemyContactDirectoryRepository(session_maker)
    integration = repository.create_integration(_integration())
    identity = _identity(integration.id)
    contact, account_id = _persist_current_contact(session_maker, invalidation)
    with session_maker.begin() as session:
        session.add(identity_to_record(identity))
    binding = None
    if operation == "delete":
        binding = repository.set_contact_binding(
            workspace_id=_WORKSPACE_ID,
            contact_id=contact.id,
            identity_id=identity.id,
            scope=IMBindingScope.ORGANIZATION,
            bound_by_account_id=AccountId("account-1"),
            now=_NOW,
        )
    snapshot = contact_repository.load_snapshot(_WORKSPACE_ID)
    assert ContactDirectoryPolicy.resolve_for_workspace(snapshot, contact.id) in (
        ContactResolution.WORKSPACE,
        ContactResolution.PLATFORM,
    )
    _invalidate_current_contact(
        session_maker,
        invalidation,
        contact=contact,
        account_id=account_id,
    )

    if operation == "set":
        with pytest.raises(IMBindingMutationError) as error:
            repository.set_contact_binding(
                workspace_id=_WORKSPACE_ID,
                contact_id=contact.id,
                identity_id=identity.id,
                scope=IMBindingScope.ORGANIZATION,
                bound_by_account_id=AccountId("account-1"),
                now=_LATER,
            )
    else:
        assert binding is not None
        with pytest.raises(IMBindingMutationError) as error:
            repository.delete_contact_binding(
                workspace_id=_WORKSPACE_ID,
                contact_id=contact.id,
                scope=IMBindingScope.ORGANIZATION,
                binding_id=binding.id,
            )

    assert error.value.code == "contact_not_found"
    with session_maker() as session:
        expected_count = 0 if operation == "set" else 1
        assert session.scalar(select(sa.func.count(HumanInputIMBinding.id))) == expected_count


@pytest.mark.parametrize(
    "invalidation",
    ["membership_removed", "hard_deleted", "platform_detach", "account_disabled"],
)
def test_effective_binding_rechecks_current_contact_availability(
    repository_context,
    invalidation: str,
) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    identity = _identity(integration.id)
    contact, account_id = _persist_current_contact(session_maker, invalidation)
    with session_maker.begin() as session:
        session.add(identity_to_record(identity))
    repository.set_contact_binding(
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
        identity_id=identity.id,
        scope=IMBindingScope.ORGANIZATION,
        bound_by_account_id=AccountId("account-1"),
        now=_NOW,
    )
    before = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )
    _invalidate_current_contact(
        session_maker,
        invalidation,
        contact=contact,
        account_id=account_id,
    )

    after = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=_WORKSPACE_ID,
        contact_id=contact.id,
    )

    assert before.kind is BindingResolutionKind.ORGANIZATION_BINDING
    assert after.kind is BindingResolutionKind.NOT_AVAILABLE
    assert after.binding is None


def test_effective_binding_rejects_cross_tenant_integration_before_email_fallback(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    other_workspace_id = WorkspaceId("workspace-2")
    contact = Contact.external(
        contact_id=ContactId("contact-other-workspace"),
        workspace_id=other_workspace_id,
        name="Other Workspace Reviewer",
        email="reviewer@example.com",
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(contact_to_record(contact))
        session.add(identity_to_record(_identity(integration.id)))

    result = repository.resolve_effective_binding(
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        workspace_id=other_workspace_id,
        contact_id=contact.id,
    )

    assert result.kind is BindingResolutionKind.INVALID_BINDING
    assert result.binding is None


def test_reconciliation_snapshot_marks_disabled_account_contact_unavailable(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert run_decision.run is not None
    account = Account(name="Disabled", email="disabled@example.com", status=AccountStatus.BANNED)
    account.id = "account-disabled"
    contact = Contact.organization_account(
        contact_id=ContactId("contact-disabled"),
        account_id=AccountId(account.id),
        name="Disabled",
        email="disabled@example.com",
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(account)
        session.add(contact_to_record(contact))

    snapshot = repository.load_reconciliation_snapshot(run_decision.run.id)

    assert len(snapshot.contacts) == 1
    assert snapshot.contacts[0].account_available is False


def test_reconciliation_updates_provider_match_and_removes_all_bindings_for_absent_identity(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert run_decision.run is not None
    contacts = (
        Contact.organization_account(
            contact_id=ContactId("contact-1"),
            account_id=AccountId("account-1"),
            name="First Reviewer",
            email="first@example.com",
            now=_NOW,
        ),
        Contact.organization_account(
            contact_id=ContactId("contact-2"),
            account_id=AccountId("account-2"),
            name="Removed Reviewer",
            email="removed@example.com",
            now=_NOW,
        ),
    )
    first_identity = _identity(integration.id)
    removed_identity = IMIdentity.create(
        identity_id=IMIdentityId("identity-removed"),
        integration_id=integration.id,
        provider=IMProvider.FEISHU,
        provider_user_id="provider-user-removed",
        display_name="Removed Reviewer",
        email="removed@example.com",
        raw_payload={},
        last_seen_sync_run_id=None,
        last_seen_at=_NOW,
        now=_NOW,
    )
    first_binding = _binding(integration.id)
    removed_binding = IMBinding.create(
        binding_id=IMBindingId("binding-removed"),
        integration_id=integration.id,
        scope=IMBindingScope.ORGANIZATION,
        scope_id=str(integration.id),
        contact_id=contacts[1].id,
        identity_id=removed_identity.id,
        provider=IMProvider.FEISHU,
        bound_by_account_id=None,
        now=_NOW,
    )
    removed_workspace_binding = IMBinding.create(
        binding_id=IMBindingId("binding-removed-workspace"),
        integration_id=integration.id,
        scope=IMBindingScope.WORKSPACE,
        scope_id=str(_WORKSPACE_ID),
        contact_id=contacts[1].id,
        identity_id=removed_identity.id,
        provider=IMProvider.FEISHU,
        bound_by_account_id=None,
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add_all([contact_to_record(contact) for contact in contacts])
        session.add_all([identity_to_record(first_identity), identity_to_record(removed_identity)])
        session.add_all(
            [
                binding_to_record(first_binding),
                binding_to_record(removed_binding),
                binding_to_record(removed_workspace_binding),
            ]
        )
    plan = ReconciliationPlan(
        sync_run_id=run_decision.run.id,
        integration_revision=integration.revision,
        provider=IMProvider.FEISHU,
        actions=(
            ReconciliationAction(
                entry=ProviderDirectoryEntry.create(
                    provider_user_id=first_identity.provider_user_id,
                    display_name="Updated Reviewer",
                    email="updated@example.com",
                    raw_payload={"updated": True},
                ),
                match_kind=MatchKind.PROVIDER_USER_ID,
                identity_id=first_identity.id,
                binding_id=first_binding.id,
                contact_id=contacts[0].id,
            ),
        ),
        removed_identity_ids=(removed_identity.id,),
    )

    result = repository.apply_reconciliation(plan, now=_LATER)

    assert result.status is ApplyReconciliationStatus.APPLIED
    assert result.run.skipped_count == 1
    assert result.run.removed_count == 2
    with session_maker() as session:
        updated = session.get_one(HumanInputIMIdentity, str(first_identity.id))
        assert updated.display_name == "Updated Reviewer"
        assert updated.last_seen_sync_run_id == str(run_decision.run.id)
        assert session.get(HumanInputIMIdentity, str(removed_identity.id)) is None
        assert (
            session.scalar(
                select(sa.func.count(HumanInputIMBinding.id)).where(
                    HumanInputIMBinding.im_identity_id == str(removed_identity.id)
                )
            )
            == 0
        )
        removed_results = session.scalars(
            select(HumanInputIMSyncResult)
            .where(HumanInputIMSyncResult.im_identity_id == str(removed_identity.id))
            .order_by(HumanInputIMSyncResult.im_binding_id)
        ).all()
        assert {item.im_binding_id for item in removed_results} == {
            str(removed_binding.id),
            str(removed_workspace_binding.id),
        }
        assert all(item.identity_snapshot is not None for item in removed_results)
        assert all(item.identity_snapshot.provider_user_id == "provider-user-removed" for item in removed_results)


def _persist_bound_identity_for_removal(
    repository: SQLAlchemyIMControlPlaneRepository,
    session_maker: sessionmaker[Session],
    contact: Contact,
) -> tuple[IMIntegration, IMSyncRunId, IMIdentity, IMBinding]:
    integration = repository.create_integration(_integration())
    decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-removal"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert decision.run is not None
    identity = _identity(
        integration.id,
        identity_id="identity-removal",
        provider_user_id="provider-user-removal",
        display_name="Removed Identity",
        email="identity-removal@example.com",
    )
    binding = IMBinding.create(
        binding_id=IMBindingId("binding-removal"),
        integration_id=integration.id,
        scope=IMBindingScope.ORGANIZATION,
        scope_id=str(integration.id),
        contact_id=contact.id,
        identity_id=identity.id,
        provider=IMProvider.FEISHU,
        bound_by_account_id=None,
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(identity_to_record(identity))
        session.add(binding_to_record(binding))
    return integration, decision.run.id, identity, binding


def _apply_identity_removal(
    repository: SQLAlchemyIMControlPlaneRepository,
    integration: IMIntegration,
    sync_run_id: IMSyncRunId,
    identity: IMIdentity,
) -> ApplyReconciliationResult:
    plan = ReconciliationPlan(
        sync_run_id=sync_run_id,
        integration_revision=integration.revision,
        provider=IMProvider.FEISHU,
        actions=(),
        removed_identity_ids=(identity.id,),
    )
    return repository.apply_reconciliation(plan, now=_LATER)


@pytest.mark.parametrize(
    ("contact_kind", "expected_resolution"),
    [
        ("workspace", ContactResolution.WORKSPACE),
        ("platform", ContactResolution.PLATFORM),
    ],
)
def test_reconciliation_removal_preserves_snapshot_for_current_contact(
    repository_context,
    contact_kind: str,
    expected_resolution: ContactResolution,
) -> None:
    repository, session_maker = repository_context
    invalidation = "membership_removed" if contact_kind == "workspace" else "platform_detach"
    contact, _ = _persist_current_contact(session_maker, invalidation)
    contact_repository = SQLAlchemyContactDirectoryRepository(session_maker)
    snapshot = contact_repository.load_snapshot(_WORKSPACE_ID)
    assert ContactDirectoryPolicy.resolve_for_workspace(snapshot, contact.id) is expected_resolution
    integration, sync_run_id, identity, binding = _persist_bound_identity_for_removal(
        repository,
        session_maker,
        contact,
    )

    result = _apply_identity_removal(repository, integration, sync_run_id, identity)

    assert result.status is ApplyReconciliationStatus.APPLIED
    assert result.run.removed_count == 1
    assert len(result.results) == 1
    fact = result.results[0]
    assert fact.result_type is IMSyncResultType.REMOVED
    assert fact.binding_id == binding.id
    assert fact.contact_id == contact.id
    assert fact.contact_snapshot is not None
    assert fact.contact_snapshot.contact_id == contact.id
    assert fact.contact_snapshot.name == contact.name
    assert fact.contact_snapshot.email == contact.email


@pytest.mark.parametrize(
    "invalidation",
    ["membership_removed", "platform_detach", "account_disabled", "hard_deleted", "cross_tenant_binding"],
)
def test_reconciliation_removal_hides_unavailable_contact_and_deletes_current_state(
    repository_context,
    invalidation: str,
) -> None:
    repository, session_maker = repository_context
    if invalidation == "cross_tenant_binding":
        contact = Contact.external(
            contact_id=ContactId("contact-cross-tenant"),
            workspace_id=WorkspaceId("workspace-2"),
            name="Cross Tenant Contact",
            email="cross-tenant-contact@example.com",
            now=_NOW,
        )
        account_id = ""
        with session_maker.begin() as session:
            session.add(contact_to_record(contact))
    else:
        contact, account_id = _persist_current_contact(session_maker, invalidation)
    integration, sync_run_id, identity, binding = _persist_bound_identity_for_removal(
        repository,
        session_maker,
        contact,
    )
    if invalidation != "cross_tenant_binding":
        _invalidate_current_contact(
            session_maker,
            invalidation,
            contact=contact,
            account_id=account_id,
        )

    result = _apply_identity_removal(repository, integration, sync_run_id, identity)

    assert result.status is ApplyReconciliationStatus.APPLIED
    assert result.run.removed_count == 1
    assert len(result.results) == 1
    fact = result.results[0]
    assert fact.result_type is IMSyncResultType.REMOVED
    assert fact.binding_id == binding.id
    assert fact.identity_id == identity.id
    assert fact.reason_code == "not_present_in_directory"
    assert fact.removal_reason is not None
    assert fact.identity_snapshot is not None
    assert fact.identity_snapshot.identity_id == identity.id
    assert fact.identity_snapshot.provider_user_id == identity.provider_user_id
    assert fact.identity_snapshot.display_name == identity.display_name
    assert fact.identity_snapshot.email == identity.email
    assert fact.contact_id is None
    assert fact.contact_snapshot is None
    with session_maker() as session:
        assert session.get(HumanInputIMIdentity, str(identity.id)) is None
        assert session.get(HumanInputIMBinding, str(binding.id)) is None
    latest, total = repository.list_latest_sync_results(
        _WORKSPACE_ID,
        result_type=IMSyncResultType.REMOVED,
        offset=0,
        limit=20,
    )
    assert total == 1
    assert latest[0].contact_id is None
    assert latest[0].contact_snapshot is None
    assert latest[0].identity_snapshot == fact.identity_snapshot


def test_reconciliation_removal_emits_fact_for_unbound_identity(repository_context) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    identity = _identity(integration.id)
    with session_maker.begin() as session:
        session.add(identity_to_record(identity))
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert run_decision.run is not None
    plan = ReconciliationPlan(
        sync_run_id=run_decision.run.id,
        integration_revision=integration.revision,
        provider=IMProvider.FEISHU,
        actions=(),
        removed_identity_ids=(identity.id,),
    )

    result = repository.apply_reconciliation(plan, now=_LATER)

    assert result.status is ApplyReconciliationStatus.APPLIED
    assert result.run.removed_count == 1
    assert len(result.results) == 1
    assert result.results[0].identity_id == identity.id
    assert result.results[0].binding_id is None
    assert result.results[0].contact_id is None
    assert result.results[0].contact_snapshot is None


def test_unmatched_reconciliation_persists_read_only_fact_without_contact_or_binding_side_effect(
    repository_context,
) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-unmatched"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert run_decision.run is not None
    existing_contact = Contact.external(
        contact_id=ContactId("contact-existing"),
        workspace_id=_WORKSPACE_ID,
        name="Existing External",
        email="existing@example.com",
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(contact_to_record(existing_contact))
    entry = ProviderDirectoryEntry.create(
        provider_user_id="provider-user-unmatched",
        display_name="Unmatched Reviewer",
        email="unmatched@example.com",
        raw_payload={},
    )
    plan = ReconciliationPlan(
        sync_run_id=run_decision.run.id,
        integration_revision=integration.revision,
        provider=IMProvider.FEISHU,
        actions=(
            ReconciliationAction(
                entry=entry,
                match_kind=MatchKind.UNMATCHED,
                identity_id=None,
                binding_id=None,
                contact_id=None,
            ),
        ),
        removed_identity_ids=(),
    )

    result = repository.apply_reconciliation(plan, now=_LATER)

    assert result.status is ApplyReconciliationStatus.APPLIED
    assert result.run.not_matched_count == 1
    assert result.results[0].result_type is IMSyncResultType.NOT_MATCHED
    assert result.results[0].contact_id is None
    with session_maker() as session:
        assert session.scalar(select(sa.func.count(HumanInputContact.id))) == 1
        assert session.scalar(select(sa.func.count(HumanInputIMIdentity.id))) == 0
        assert session.scalar(select(sa.func.count(HumanInputIMBinding.id))) == 0


@pytest.mark.parametrize(
    "invalidation",
    ["membership_removed", "hard_deleted", "platform_detach", "account_disabled"],
)
def test_reconciliation_apply_downgrades_stale_contact_match_without_current_state_side_effect(
    repository_context,
    invalidation: str,
) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-contact-race"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert decision.run is not None
    contact, account_id = _persist_current_contact(session_maker, invalidation)
    snapshot = repository.load_reconciliation_snapshot(decision.run.id)
    matching_contact = next(item for item in snapshot.contacts if item.contact.id == contact.id)
    assert matching_contact.account_available is True
    entry = ProviderDirectoryEntry.create(
        provider_user_id="provider-user-race",
        display_name="Race Reviewer",
        email="race@example.com",
        raw_payload={},
    )
    plan = ReconciliationPlan(
        sync_run_id=decision.run.id,
        integration_revision=integration.revision,
        provider=IMProvider.FEISHU,
        actions=(
            ReconciliationAction(
                entry=entry,
                match_kind=MatchKind.NORMALIZED_EMAIL,
                identity_id=None,
                binding_id=None,
                contact_id=contact.id,
            ),
        ),
        removed_identity_ids=(),
    )
    _invalidate_current_contact(
        session_maker,
        invalidation,
        contact=contact,
        account_id=account_id,
    )

    result = repository.apply_reconciliation(plan, now=_LATER)

    assert result.status is ApplyReconciliationStatus.APPLIED
    assert result.run.status is IMSyncRunStatus.SUCCEEDED
    assert result.run.added_count == 0
    assert result.run.not_matched_count == 1
    assert result.results[0].result_type is IMSyncResultType.NOT_MATCHED
    assert result.results[0].reason_code == "contact_unavailable"
    assert result.results[0].contact_id is None
    assert result.results[0].contact_snapshot is None
    with session_maker() as session:
        assert session.scalar(select(sa.func.count(HumanInputIMIdentity.id))) == 0
        assert session.scalar(select(sa.func.count(HumanInputIMBinding.id))) == 0


def test_latest_result_paging_isolated_for_all_five_canonical_buckets(repository_context) -> None:
    repository, _ = repository_context
    integration = repository.create_integration(_integration())
    decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-results"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert decision.run is not None
    repository.fail_sync_run(
        decision.run.id,
        error_code="safe_failure",
        error_message="Safe failure",
        now=_LATER,
    )
    failed_results, _ = repository.list_latest_sync_results(
        _WORKSPACE_ID,
        result_type=IMSyncResultType.FAILED,
        offset=0,
        limit=20,
    )
    template = failed_results[0]
    facts = tuple(
        replace(
            template,
            id=IMSyncResultId(f"result-{result_type.value}-{index}"),
            result_type=result_type,
        )
        for result_type in IMSyncResultType
        for index in range(2 if result_type is not IMSyncResultType.FAILED else 1)
    )
    repository.append_sync_results(facts)

    for result_type in IMSyncResultType:
        items, total = repository.list_latest_sync_results(
            _WORKSPACE_ID,
            result_type=result_type,
            offset=1,
            limit=1,
        )
        assert total == 2
        assert len(items) == 1
        assert items[0].result_type is result_type


def test_valid_reconciliation_failure_rolls_back_current_state_and_results(repository_context, monkeypatch) -> None:
    repository, session_maker = repository_context
    integration = repository.create_integration(_integration())
    run_decision = repository.create_or_get_active_run(
        integration.revision,
        sync_run_id=IMSyncRunId("run-1"),
        started_by_account_id=None,
        now=_NOW,
    )
    assert run_decision.run is not None
    contact = Contact.organization_account(
        contact_id=ContactId("contact-1"),
        account_id=AccountId("account-1"),
        name="Reviewer",
        email="reviewer@example.com",
        now=_NOW,
    )
    with session_maker.begin() as session:
        session.add(contact_to_record(contact))
    plan = ReconciliationPlan(
        sync_run_id=run_decision.run.id,
        integration_revision=integration.revision,
        provider=IMProvider.FEISHU,
        actions=(
            ReconciliationAction(
                entry=ProviderDirectoryEntry.create(
                    provider_user_id="provider-user-1",
                    display_name="Reviewer",
                    email="reviewer@example.com",
                    raw_payload={},
                ),
                match_kind=MatchKind.NORMALIZED_EMAIL,
                identity_id=None,
                binding_id=None,
                contact_id=contact.id,
            ),
        ),
        removed_identity_ids=(),
    )

    monkeypatch.setattr(
        repository, "_append_result_record", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        repository.apply_reconciliation(plan, now=_LATER)

    with session_maker() as session:
        assert session.scalar(sa.select(sa.func.count(HumanInputIMIdentity.id))) == 0
        assert session.scalar(sa.select(sa.func.count(HumanInputIMBinding.id))) == 0
        assert session.scalar(sa.select(sa.func.count(HumanInputIMSyncResult.id))) == 0
        run = session.get_one(HumanInputIMSyncRun, str(run_decision.run.id))
        assert run.status is IMSyncRunStatus.QUEUED


def test_locked_integration_statement_uses_complete_token_and_for_update() -> None:
    token = IntegrationRevisionToken(IntegrationId("integration-1"), 4)

    statement = SQLAlchemyIMControlPlaneRepository._locked_integration_statement(token)
    compiled = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "human_input_im_integrations.id = 'integration-1'" in compiled
    assert "human_input_im_integrations.config_version = 4" in compiled
    assert compiled.endswith("FOR UPDATE")


def test_workspace_first_creation_locks_stable_tenant_owner_for_update() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = str(_WORKSPACE_ID)

    SQLAlchemyIMControlPlaneRepository._lock_workspace_owner(session, _WORKSPACE_ID)

    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "FROM tenants" in compiled
    assert "tenants.id = 'workspace-1'" in compiled
    assert compiled.endswith("FOR UPDATE")


def test_workspace_data_selector_uses_tenant_only_predicate_without_deployment_fallback() -> None:
    statement = SQLAlchemyIMControlPlaneRepository._tenant_integration_id_statement(_WORKSPACE_ID)

    compiled = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "human_input_im_integrations.tenant_id = 'workspace-1'" in compiled
    assert "IS NULL" not in compiled
