"""Contact-scoped management for synchronized IM identities and bindings.

The service resolves Contact availability before every write. Organization
bindings and workspace overrides remain separate persistence scopes, while
response projections reuse the existing effective-binding resolver.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.human_input_v2.contact_directory import (
    Contact,
    ContactDirectoryError,
    ContactDirectoryPolicy,
    ContactDirectoryRepository,
    ContactResolution,
)
from core.human_input_v2.entities import IMBindingScope, IMIdentityBindingStatus
from core.human_input_v2.im_integration import BindingResolutionResult, IMIdentity
from core.human_input_v2.shared import AccountId, ContactId, IMBindingId, IMIdentityId, UtcTimestamp, WorkspaceId
from repositories.human_input_v2.im_integration.repository import (
    IMBindingMutationError,
    SQLAlchemyIMControlPlaneRepository,
)


class ContactIMBindingError(Exception):
    """Safe application error mapped by the console transport."""

    code: str

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class IMIdentityListItem:
    """One identity search result with its current binding state."""

    identity: IMIdentity
    binding_status: IMIdentityBindingStatus


@dataclass(frozen=True, slots=True)
class IMIdentityPage:
    """One page of synchronized identities from the current integration."""

    items: tuple[IMIdentityListItem, ...]
    total: int
    page: int
    limit: int


@dataclass(frozen=True, slots=True)
class ContactIMBindingView:
    """Current Contact projection plus its effective explicit IM binding."""

    contact: Contact
    resolution: ContactResolution
    effective_binding: BindingResolutionResult


class ContactIMBindingService:
    """Coordinate identity search and contact-scoped binding mutations.

    Writes accept only contacts that currently resolve as ``WORKSPACE`` or
    ``PLATFORM``. Organization bindings and workspace overrides are mutated
    independently and effective responses use the shared binding resolver.
    """

    _im_repository: SQLAlchemyIMControlPlaneRepository
    _contact_repository: ContactDirectoryRepository
    _workspace_overrides_enabled: bool

    def __init__(
        self,
        im_repository: SQLAlchemyIMControlPlaneRepository,
        contact_repository: ContactDirectoryRepository,
        *,
        workspace_overrides_enabled: bool,
    ) -> None:
        self._im_repository = im_repository
        self._contact_repository = contact_repository
        self._workspace_overrides_enabled = workspace_overrides_enabled

    def list_identities(
        self,
        *,
        workspace_id: str,
        keyword: str | None,
        page: int,
        limit: int,
    ) -> IMIdentityPage:
        integration = self._im_repository.find_current_integration(WorkspaceId(workspace_id))
        if integration is not None and integration.workspace_id is None:
            raise ContactIMBindingError(
                "deployment_integration_unsupported",
                "Deployment-wide IM integrations are not available to workspace identity search.",
            )
        rows, total = self._im_repository.list_current_identities(
            WorkspaceId(workspace_id),
            keyword=keyword,
            offset=(page - 1) * limit,
            limit=limit,
        )
        return IMIdentityPage(
            items=tuple(
                IMIdentityListItem(
                    identity=row.identity,
                    binding_status=(IMIdentityBindingStatus.BOUND if row.is_bound else IMIdentityBindingStatus.UNBOUND),
                )
                for row in rows
            ),
            total=total,
            page=page,
            limit=limit,
        )

    def create_binding(
        self,
        *,
        workspace_id: str,
        contact_id: str,
        identity_id: str,
        account_id: str,
    ) -> ContactIMBindingView:
        contact, resolution = self._eligible_contact(workspace_id, contact_id)
        self._set_binding(
            workspace_id=workspace_id,
            contact_id=contact_id,
            identity_id=identity_id,
            account_id=account_id,
            scope=IMBindingScope.ORGANIZATION,
        )
        return self._view(workspace_id, contact, resolution)

    def delete_binding(self, *, workspace_id: str, contact_id: str, binding_id: str) -> None:
        self._eligible_contact(workspace_id, contact_id)
        self._delete_binding(
            workspace_id=workspace_id,
            contact_id=contact_id,
            scope=IMBindingScope.ORGANIZATION,
            binding_id=IMBindingId(binding_id),
        )

    def set_override(
        self,
        *,
        workspace_id: str,
        contact_id: str,
        identity_id: str,
        account_id: str,
    ) -> ContactIMBindingView:
        self._ensure_workspace_overrides_enabled()
        contact, resolution = self._eligible_contact(workspace_id, contact_id)
        self._set_binding(
            workspace_id=workspace_id,
            contact_id=contact_id,
            identity_id=identity_id,
            account_id=account_id,
            scope=IMBindingScope.WORKSPACE,
        )
        return self._view(workspace_id, contact, resolution)

    def reset_override(self, *, workspace_id: str, contact_id: str) -> ContactIMBindingView:
        self._ensure_workspace_overrides_enabled()
        contact, resolution = self._eligible_contact(workspace_id, contact_id)
        self._delete_binding(
            workspace_id=workspace_id,
            contact_id=contact_id,
            scope=IMBindingScope.WORKSPACE,
            binding_id=None,
        )
        return self._view(workspace_id, contact, resolution)

    def _eligible_contact(self, workspace_id: str, contact_id: str) -> tuple[Contact, ContactResolution]:
        try:
            snapshot = self._contact_repository.load_snapshot(WorkspaceId(workspace_id))
            resolved_contact_id = ContactId(contact_id)
            resolution = ContactDirectoryPolicy.resolve_for_workspace(snapshot, resolved_contact_id)
        except ContactDirectoryError as error:
            raise ContactIMBindingError("contact_unavailable", "The contact is unavailable.") from error
        contact = snapshot.find(resolved_contact_id)
        if contact is None or resolution is ContactResolution.ABSENT:
            raise ContactIMBindingError("contact_not_found", "The contact is unavailable.")
        if resolution is ContactResolution.EXTERNAL:
            raise ContactIMBindingError("external_contact_not_supported", "External contacts are email-only.")
        if resolution not in (ContactResolution.WORKSPACE, ContactResolution.PLATFORM):
            raise ContactIMBindingError("contact_not_found", "The contact is unavailable.")
        return contact, resolution

    def _set_binding(
        self,
        *,
        workspace_id: str,
        contact_id: str,
        identity_id: str,
        account_id: str,
        scope: IMBindingScope,
    ) -> None:
        try:
            self._im_repository.set_contact_binding(
                workspace_id=WorkspaceId(workspace_id),
                contact_id=ContactId(contact_id),
                identity_id=IMIdentityId(identity_id),
                scope=scope,
                bound_by_account_id=AccountId(account_id),
                now=UtcTimestamp.now(),
            )
        except IMBindingMutationError as error:
            raise _application_error(error) from error

    def _delete_binding(
        self,
        *,
        workspace_id: str,
        contact_id: str,
        scope: IMBindingScope,
        binding_id: IMBindingId | None,
    ) -> None:
        try:
            self._im_repository.delete_contact_binding(
                workspace_id=WorkspaceId(workspace_id),
                contact_id=ContactId(contact_id),
                scope=scope,
                binding_id=binding_id,
            )
        except IMBindingMutationError as error:
            raise _application_error(error) from error

    def _view(
        self,
        workspace_id: str,
        contact: Contact,
        resolution: ContactResolution,
    ) -> ContactIMBindingView:
        integration = self._im_repository.find_current_integration(WorkspaceId(workspace_id))
        if integration is None:
            raise ContactIMBindingError("integration_not_configured", "No IM integration is configured.")
        effective_binding = self._im_repository.resolve_effective_binding(
            integration_id=integration.id,
            provider=integration.provider_tenant.provider,
            workspace_id=WorkspaceId(workspace_id),
            contact_id=contact.id,
        )
        return ContactIMBindingView(contact, resolution, effective_binding)

    def _ensure_workspace_overrides_enabled(self) -> None:
        if not self._workspace_overrides_enabled:
            raise ContactIMBindingError(
                "workspace_override_unsupported",
                "Workspace IM overrides require Enterprise Edition.",
            )


def _application_error(error: IMBindingMutationError) -> ContactIMBindingError:
    messages = {
        "integration_not_configured": "No IM integration is configured.",
        "deployment_integration_unsupported": (
            "Deployment-wide IM integrations are not supported by workspace binding operations."
        ),
        "contact_not_found": "The contact is unavailable.",
        "external_contact_not_supported": "External contacts are email-only.",
        "identity_not_found": "The synchronized IM identity was not found.",
        "identity_already_bound": "The synchronized IM identity is already bound.",
        "binding_conflict": "The IM binding changed concurrently.",
        "binding_not_found": "The IM binding was not found.",
    }
    return ContactIMBindingError(error.code, messages.get(error.code, "The IM binding request was rejected."))


__all__ = [
    "ContactIMBindingError",
    "ContactIMBindingService",
    "ContactIMBindingView",
    "IMIdentityListItem",
    "IMIdentityPage",
]
