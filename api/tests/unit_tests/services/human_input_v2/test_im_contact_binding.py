"""Unit tests for contact-scoped IM identity and binding management."""

from datetime import UTC, datetime
from functools import partial
from unittest.mock import MagicMock

import pytest

from core.human_input_v2.contact_directory import (
    Contact,
    ContactDirectoryError,
    ContactDirectorySnapshot,
    ContactRejection,
    ContactRejectionCode,
    ContactResolution,
)
from core.human_input_v2.entities import IMBindingScope, IMIdentityBindingStatus, IMProvider
from core.human_input_v2.im_integration import (
    BindingResolutionKind,
    BindingResolutionResult,
    EncryptedCredentials,
    IMIdentity,
    IMIntegration,
    ProviderTenantIdentity,
)
from core.human_input_v2.shared import (
    AccountId,
    ContactId,
    IMBindingId,
    IMIdentityId,
    IntegrationId,
    UtcTimestamp,
    WorkspaceId,
)
from repositories.human_input_v2.im_integration.repository import IMBindingMutationError, IMIdentitySearchRow
from services.human_input_v2.im_contact_binding import ContactIMBindingError, ContactIMBindingService

_NOW = UtcTimestamp(datetime(2026, 7, 27, 8, tzinfo=UTC))
_WORKSPACE_ID = WorkspaceId("workspace-1")
_ACCOUNT_ID = AccountId("account-1")
_CONTACT_ID = ContactId("contact-1")


def _identity() -> IMIdentity:
    return IMIdentity.create(
        identity_id=IMIdentityId("identity-1"),
        integration_id=IntegrationId("integration-1"),
        provider=IMProvider.FEISHU,
        provider_user_id="provider-user-1",
        display_name="Reviewer",
        email="reviewer@example.com",
        raw_payload={},
        last_seen_sync_run_id=None,
        last_seen_at=_NOW,
        now=_NOW,
    )


def _integration(*, workspace_id: WorkspaceId | None = _WORKSPACE_ID) -> IMIntegration:
    return IMIntegration.create(
        integration_id=IntegrationId("integration-1"),
        workspace_id=workspace_id,
        provider_tenant=ProviderTenantIdentity(IMProvider.FEISHU, "tenant-1"),
        encrypted_credentials=EncryptedCredentials.from_mapping(
            {"app_id": "app-id", "encrypted_app_secret": "encrypted-secret"}
        ),
        configured_by_account_id=_ACCOUNT_ID,
        callback_url=None,
        now=_NOW,
    )


def _workspace_contact() -> Contact:
    return Contact.workspace_member(
        contact_id=_CONTACT_ID,
        workspace_id=_WORKSPACE_ID,
        account_id=_ACCOUNT_ID,
        name="Workspace Reviewer",
        email="reviewer@example.com",
        now=_NOW,
    )


def _platform_contact() -> Contact:
    return Contact.organization_account(
        contact_id=_CONTACT_ID,
        account_id=_ACCOUNT_ID,
        name="Platform Reviewer",
        email="reviewer@example.com",
        now=_NOW,
    )


def _snapshot(contact: Contact, resolution: ContactResolution) -> ContactDirectorySnapshot:
    return ContactDirectorySnapshot(
        workspace_id=_WORKSPACE_ID,
        contacts=(contact,),
        member_account_ids=(frozenset({_ACCOUNT_ID}) if resolution is ContactResolution.WORKSPACE else frozenset()),
        platform_contact_ids=(frozenset({_CONTACT_ID}) if resolution is ContactResolution.PLATFORM else frozenset()),
    )


def _service(
    *,
    snapshot: ContactDirectorySnapshot | None = None,
    workspace_overrides_enabled: bool = True,
) -> tuple[ContactIMBindingService, MagicMock, MagicMock]:
    im_repository = MagicMock()
    contact_repository = MagicMock()
    contact_repository.load_snapshot.return_value = snapshot or ContactDirectorySnapshot(_WORKSPACE_ID)
    im_repository.find_current_integration.return_value = _integration()
    im_repository.resolve_effective_binding.return_value = BindingResolutionResult(
        BindingResolutionKind.NOT_AVAILABLE,
        None,
    )
    return (
        ContactIMBindingService(
            im_repository,
            contact_repository,
            workspace_overrides_enabled=workspace_overrides_enabled,
        ),
        im_repository,
        contact_repository,
    )


def test_list_identities_projects_workspace_scoped_binding_status_and_page() -> None:
    service, im_repository, _ = _service()
    identity = _identity()
    im_repository.list_current_identities.return_value = (
        (
            IMIdentitySearchRow(identity, True),
            IMIdentitySearchRow(identity, False),
        ),
        7,
    )

    page = service.list_identities(
        workspace_id="workspace-1",
        keyword=" reviewer ",
        page=2,
        limit=3,
    )

    assert [item.binding_status for item in page.items] == [
        IMIdentityBindingStatus.BOUND,
        IMIdentityBindingStatus.UNBOUND,
    ]
    assert (page.total, page.page, page.limit) == (7, 2, 3)
    im_repository.list_current_identities.assert_called_once_with(
        _WORKSPACE_ID,
        keyword=" reviewer ",
        offset=3,
        limit=3,
    )


def test_list_identities_rejects_deployment_fallback_before_repository_data_access() -> None:
    service, im_repository, _ = _service()
    im_repository.find_current_integration.return_value = _integration(workspace_id=None)

    with pytest.raises(ContactIMBindingError, match="not available") as error:
        service.list_identities(
            workspace_id="workspace-1",
            keyword=None,
            page=1,
            limit=20,
        )

    assert error.value.code == "deployment_integration_unsupported"
    im_repository.list_current_identities.assert_not_called()


@pytest.mark.parametrize(
    ("contact", "resolution"),
    [
        (_workspace_contact(), ContactResolution.WORKSPACE),
        (_platform_contact(), ContactResolution.PLATFORM),
    ],
)
def test_create_and_delete_binding_accept_current_non_external_contacts(
    contact: Contact,
    resolution: ContactResolution,
) -> None:
    service, im_repository, _ = _service(snapshot=_snapshot(contact, resolution))

    view = service.create_binding(
        workspace_id="workspace-1",
        contact_id="contact-1",
        identity_id="identity-1",
        account_id="account-1",
    )
    service.delete_binding(
        workspace_id="workspace-1",
        contact_id="contact-1",
        binding_id="binding-1",
    )

    assert view.contact == contact
    assert view.resolution is resolution
    im_repository.set_contact_binding.assert_called_once()
    assert im_repository.set_contact_binding.call_args.kwargs["scope"] is IMBindingScope.ORGANIZATION
    im_repository.delete_contact_binding.assert_called_once_with(
        workspace_id=_WORKSPACE_ID,
        contact_id=_CONTACT_ID,
        scope=IMBindingScope.ORGANIZATION,
        binding_id=IMBindingId("binding-1"),
    )


@pytest.mark.parametrize("subject", ["external", "absent", "deleted"])
def test_binding_rejects_ineligible_contact_without_mutation(subject: str) -> None:
    if subject == "external":
        contact = Contact.external(
            contact_id=_CONTACT_ID,
            workspace_id=_WORKSPACE_ID,
            name="External Reviewer",
            email="reviewer@example.com",
            now=_NOW,
        )
        snapshot = ContactDirectorySnapshot(_WORKSPACE_ID, contacts=(contact,))
        expected_code = "external_contact_not_supported"
    else:
        snapshot = ContactDirectorySnapshot(_WORKSPACE_ID)
        expected_code = "contact_not_found"
    service, im_repository, _ = _service(snapshot=snapshot)

    with pytest.raises(ContactIMBindingError) as error:
        service.create_binding(
            workspace_id="workspace-1",
            contact_id="contact-1",
            identity_id="identity-1",
            account_id="account-1",
        )

    assert error.value.code == expected_code
    im_repository.set_contact_binding.assert_not_called()
    im_repository.delete_contact_binding.assert_not_called()


def test_contact_directory_failure_is_safe_and_has_no_binding_side_effect() -> None:
    service, im_repository, contact_repository = _service()
    contact_repository.load_snapshot.side_effect = ContactDirectoryError(
        ContactRejection(ContactRejectionCode.PERSISTENCE_FAILURE)
    )

    with pytest.raises(ContactIMBindingError, match="unavailable") as error:
        service.delete_binding(
            workspace_id="workspace-1",
            contact_id="contact-1",
            binding_id="binding-1",
        )

    assert error.value.code == "contact_unavailable"
    im_repository.delete_contact_binding.assert_not_called()


def test_workspace_override_set_and_reset_never_mutate_organization_binding() -> None:
    contact = _workspace_contact()
    service, im_repository, _ = _service(snapshot=_snapshot(contact, ContactResolution.WORKSPACE))
    organization_resolution = BindingResolutionResult(BindingResolutionKind.ORGANIZATION_BINDING, None)
    im_repository.resolve_effective_binding.side_effect = [
        BindingResolutionResult(BindingResolutionKind.WORKSPACE_OVERRIDE, None),
        organization_resolution,
    ]

    set_view = service.set_override(
        workspace_id="workspace-1",
        contact_id="contact-1",
        identity_id="identity-1",
        account_id="account-1",
    )
    reset_view = service.reset_override(
        workspace_id="workspace-1",
        contact_id="contact-1",
    )

    assert set_view.effective_binding.kind is BindingResolutionKind.WORKSPACE_OVERRIDE
    assert reset_view.effective_binding is organization_resolution
    assert im_repository.set_contact_binding.call_args.kwargs["scope"] is IMBindingScope.WORKSPACE
    im_repository.delete_contact_binding.assert_called_once_with(
        workspace_id=_WORKSPACE_ID,
        contact_id=_CONTACT_ID,
        scope=IMBindingScope.WORKSPACE,
        binding_id=None,
    )


@pytest.mark.parametrize("operation", ["set", "reset"])
def test_workspace_override_is_rejected_when_edition_does_not_support_it(operation: str) -> None:
    contact = _workspace_contact()
    service, im_repository, contact_repository = _service(
        snapshot=_snapshot(contact, ContactResolution.WORKSPACE),
        workspace_overrides_enabled=False,
    )
    invoke = (
        partial(
            service.set_override,
            workspace_id="workspace-1",
            contact_id="contact-1",
            identity_id="identity-1",
            account_id="account-1",
        )
        if operation == "set"
        else partial(service.reset_override, workspace_id="workspace-1", contact_id="contact-1")
    )

    with pytest.raises(ContactIMBindingError, match="Enterprise Edition") as error:
        invoke()

    assert error.value.code == "workspace_override_unsupported"
    contact_repository.load_snapshot.assert_not_called()
    im_repository.set_contact_binding.assert_not_called()
    im_repository.delete_contact_binding.assert_not_called()


@pytest.mark.parametrize(
    ("repository_code", "application_code"),
    [
        ("integration_not_configured", "integration_not_configured"),
        ("deployment_integration_unsupported", "deployment_integration_unsupported"),
        ("identity_not_found", "identity_not_found"),
        ("identity_already_bound", "identity_already_bound"),
        ("binding_conflict", "binding_conflict"),
        ("binding_not_found", "binding_not_found"),
        ("unknown", "unknown"),
    ],
)
def test_repository_binding_rejections_are_mapped_to_safe_application_errors(
    repository_code: str,
    application_code: str,
) -> None:
    contact = _workspace_contact()
    service, im_repository, _ = _service(snapshot=_snapshot(contact, ContactResolution.WORKSPACE))
    im_repository.set_contact_binding.side_effect = IMBindingMutationError(repository_code)

    with pytest.raises(ContactIMBindingError) as error:
        service.create_binding(
            workspace_id="workspace-1",
            contact_id="contact-1",
            identity_id="identity-1",
            account_id="account-1",
        )

    assert error.value.code == application_code
    assert repository_code not in str(error.value)
