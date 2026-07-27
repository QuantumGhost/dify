"""Workspace-level Human Input v2 management routes.

IM management stays provider-neutral: controllers validate DTOs, application
services own orchestration, integration writes use complete CAS revisions, and
contact binding writes admit only current non-external contacts.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Never

from flask import abort, request
from flask_restx import Resource
from sqlalchemy.orm import sessionmaker

from configs import dify_config
from controllers.common.human_input_v2_contracts import (
    AddPlatformContactsRequest,
    AddPlatformContactsResponse,
    BatchGetContactOptionsQuery,
    BatchGetContactOptionsResponse,
    BatchGetContactsQuery,
    BatchGetContactsResponse,
    ContactListQuery,
    ContactOption,
    ContactOptionsQuery,
    CreateIMBindingRequest,
    CreateIMBindingResponse,
    CreateIMSyncRunResponse,
    DeleteIMBindingQuery,
    DeleteIMBindingResponse,
    DeleteIMIntegrationQuery,
    ExternalContactCreateRequest,
    ExternalContactCreateResponse,
    ExternalContactUpdateRequest,
    ExternalContactUpdateResponse,
    GetContactResponse,
    GetEmailProviderResponse,
    GetIMIntegrationResponse,
    GetLatestIMSyncRunResponse,
    HumanInputContact,
    HumanInputContactType,
    IMIntegrationStatus,
    IMProvider,
    IMSyncResultType,
    IMSyncRunStatus,
    ListContactOptionsResponse,
    ListContactsResponse,
    ListIMIdentitiesQuery,
    ListIMIdentitiesResponse,
    ListLatestIMSyncRunResultsQuery,
    ListLatestIMSyncRunResultsResponse,
    ListOrganizationCandidatesResponse,
    NodeDataMigrationFailureResponse,
    NodeDataMigrationPayload,
    NodeDataMigrationResponse,
    OrganizationCandidatesQuery,
    PreserveOriginalValue,
    RemoveContactsRequest,
    RemoveContactsResponse,
    ResetContactIMOverrideResponse,
    SetContactIMOverrideRequest,
    SetContactIMOverrideResponse,
    SetEmailProviderRequest,
    SetEmailProviderResponse,
    TestIMIntegrationRequest,
    TestIMIntegrationResponse,
    UpdateIMIntegrationRequest,
    UpdateIMIntegrationResponse,
)
from controllers.common.schema import (
    query_params_from_model,
    query_params_from_request,
    register_enum_models,
    register_response_schema_models,
    register_schema_models,
)
from controllers.console import console_ns
from controllers.console.wraps import (
    account_initialization_required,
    edit_permission_required,
    is_admin_or_owner_required,
    setup_required,
    with_current_tenant_id,
)
from core.human_input_v2.im_integration import BindingResolutionKind, IntegrationRevisionToken, SyncResultFact
from core.human_input_v2.im_integration import IMIntegration as DomainIMIntegration
from core.human_input_v2.im_integration import IMSyncRun as DomainIMSyncRun
from core.human_input_v2.shared import IntegrationId
from extensions.ext_database import db
from libs.exception import BaseHTTPException
from libs.helper import dump_response, to_timestamp
from libs.login import current_account_with_tenant, login_required
from repositories.human_input_v2.contact_directory import SQLAlchemyContactDirectoryRepository
from repositories.human_input_v2.im_integration import SQLAlchemyIMControlPlaneRepository
from services.human_input_v2.im_contact_binding import (
    ContactIMBindingError,
    ContactIMBindingService,
    ContactIMBindingView,
)
from services.human_input_v2.im_provider import ProviderCredentials
from services.human_input_v2.im_sync import (
    IMSyncManagementError,
    IMSyncManagementService,
)
from tasks.human_input_im_sync_task import human_input_im_sync_task

register_enum_models(
    console_ns,
    HumanInputContactType,
    IMIntegrationStatus,
    IMSyncRunStatus,
    IMSyncResultType,
    IMProvider,
)
register_schema_models(
    console_ns,
    ContactListQuery,
    ContactOptionsQuery,
    BatchGetContactOptionsQuery,
    OrganizationCandidatesQuery,
    AddPlatformContactsRequest,
    ExternalContactCreateRequest,
    ExternalContactUpdateRequest,
    RemoveContactsRequest,
    UpdateIMIntegrationRequest,
    DeleteIMIntegrationQuery,
    TestIMIntegrationRequest,
    ListIMIdentitiesQuery,
    ListLatestIMSyncRunResultsQuery,
    SetContactIMOverrideRequest,
    CreateIMBindingRequest,
    NodeDataMigrationPayload,
    SetEmailProviderRequest,
)
register_response_schema_models(
    console_ns,
    HumanInputContact,
    ContactOption,
    GetContactResponse,
    ExternalContactCreateResponse,
    ExternalContactUpdateResponse,
    AddPlatformContactsResponse,
    ListContactsResponse,
    ListContactOptionsResponse,
    BatchGetContactOptionsResponse,
    RemoveContactsResponse,
    ListIMIdentitiesResponse,
    GetIMIntegrationResponse,
    UpdateIMIntegrationResponse,
    TestIMIntegrationResponse,
    CreateIMSyncRunResponse,
    GetLatestIMSyncRunResponse,
    ListLatestIMSyncRunResultsResponse,
    ListOrganizationCandidatesResponse,
    ResetContactIMOverrideResponse,
    SetContactIMOverrideResponse,
    CreateIMBindingResponse,
    DeleteIMBindingResponse,
    BatchGetContactsResponse,
    NodeDataMigrationResponse,
    NodeDataMigrationFailureResponse,
    GetEmailProviderResponse,
    SetEmailProviderResponse,
)


def _raise_stub_not_implemented() -> None:
    abort(HTTPStatus.NOT_IMPLEMENTED, "Human Input v2 stub endpoint is not implemented yet.")


def _im_sync_service() -> IMSyncManagementService:
    repository = SQLAlchemyIMControlPlaneRepository(
        sessionmaker(bind=db.engine, expire_on_commit=False),
    )
    return IMSyncManagementService(repository, human_input_im_sync_task.delay)


def _contact_im_binding_service() -> ContactIMBindingService:
    session_maker_ = sessionmaker(bind=db.engine, expire_on_commit=False)
    return ContactIMBindingService(
        SQLAlchemyIMControlPlaneRepository(session_maker_),
        SQLAlchemyContactDirectoryRepository(session_maker_),
        workspace_overrides_enabled=dify_config.ENTERPRISE_ENABLED,
    )


class _HumanInputManagementHTTPError(BaseHTTPException):
    """Console error that preserves the application's stable machine code."""

    def __init__(self, *, error_code: str, description: str, status: HTTPStatus) -> None:
        self.error_code = error_code
        self.code = status
        super().__init__(description=description)


def _handle_im_sync_error(error: IMSyncManagementError) -> Never:
    status = {
        "integration_not_configured": HTTPStatus.CONFLICT,
        "provider_connection_failed": HTTPStatus.BAD_GATEWAY,
        "deployment_integration_unsupported": HTTPStatus.CONFLICT,
        "stale_integration_revision": HTTPStatus.CONFLICT,
        "stale_revision": HTTPStatus.CONFLICT,
        "sync_dispatch_failed": HTTPStatus.SERVICE_UNAVAILABLE,
        "sync_run_not_found": HTTPStatus.NOT_FOUND,
        "unsupported_provider": HTTPStatus.BAD_REQUEST,
        "invalid_credentials": HTTPStatus.BAD_REQUEST,
    }.get(error.code, HTTPStatus.BAD_REQUEST)
    raise _HumanInputManagementHTTPError(
        error_code=error.code,
        description=str(error),
        status=status,
    ) from error


def _handle_contact_im_binding_error(error: ContactIMBindingError) -> Never:
    status = {
        "contact_not_found": HTTPStatus.NOT_FOUND,
        "identity_not_found": HTTPStatus.NOT_FOUND,
        "binding_not_found": HTTPStatus.NOT_FOUND,
        "workspace_override_unsupported": HTTPStatus.FORBIDDEN,
        "integration_not_configured": HTTPStatus.CONFLICT,
        "deployment_integration_unsupported": HTTPStatus.CONFLICT,
        "external_contact_not_supported": HTTPStatus.CONFLICT,
        "identity_already_bound": HTTPStatus.CONFLICT,
        "binding_conflict": HTTPStatus.CONFLICT,
        "contact_unavailable": HTTPStatus.SERVICE_UNAVAILABLE,
    }.get(error.code, HTTPStatus.BAD_REQUEST)
    raise _HumanInputManagementHTTPError(
        error_code=error.code,
        description=str(error),
        status=status,
    ) from error


def _integration_payload(integration: DomainIMIntegration | None) -> dict[str, object]:
    if integration is None:
        return {
            "provider": None,
            "status": IMIntegrationStatus.NOT_CONFIGURED,
            "callback_url": None,
            "permission_hint": None,
            "configured_at": None,
            "updated_at": None,
            "integration_id": None,
            "config_version": None,
        }
    return {
        "provider": integration.provider_tenant.provider,
        "status": integration.status,
        "callback_url": integration.callback_url,
        "permission_hint": integration.safe_status_reason,
        "configured_at": to_timestamp(integration.created_at.value),
        "updated_at": to_timestamp(integration.updated_at.value),
        "integration_id": str(integration.id),
        "config_version": integration.config_version,
    }


def _sync_run_payload(run: DomainIMSyncRun) -> dict[str, object]:
    return {
        "id": str(run.id),
        "status": run.status,
        "started_at": to_timestamp(run.started_at.value) if run.started_at is not None else None,
        "finished_at": to_timestamp(run.finished_at.value) if run.finished_at is not None else None,
        "error_message": run.error_message,
        "result_counts": {
            "added": run.added_count,
            "not_matched": run.not_matched_count,
            "failed": run.failed_count,
            "removed": run.removed_count,
            "skipped": run.skipped_count,
        },
        "provider": run.provider,
        "integration_id": str(run.integration_revision.integration_id),
        "integration_config_version": run.integration_revision.config_version,
    }


def _request_credentials(
    service: IMSyncManagementService,
    tenant_id: str,
    request_model: UpdateIMIntegrationRequest | TestIMIntegrationRequest,
) -> ProviderCredentials:
    credentials = request_model.credentials
    values = {name: getattr(credentials, name) for name in type(credentials).model_fields if name != "provider"}
    preserve_requested = any(isinstance(value, PreserveOriginalValue) for value in values.values())
    current = service.load_plaintext_credentials(tenant_id) if preserve_requested else None
    if preserve_requested and (current is None or current.provider is not credentials.provider):
        raise IMSyncManagementError("stale_revision", "No matching credential exists to preserve.")

    current_values = current.to_mapping() if current is not None else {}
    resolved = {
        name: current_values.get(name) if isinstance(value, PreserveOriginalValue) else value
        for name, value in values.items()
    }
    return service.prepare_credentials(credentials.provider, resolved)


def _sync_result_payload(fact: SyncResultFact) -> dict[str, object]:
    entry = (
        {
            "provider_user_id": fact.provider_user_id,
            "display_name": fact.display_name,
            "email": fact.email,
        }
        if fact.provider_user_id is not None
        else None
    )
    contact = (
        {
            "id": str(fact.contact_snapshot.contact_id),
            "name": fact.contact_snapshot.name,
            "avatar_url": "",
            "created_at": to_timestamp(fact.created_at.value),
        }
        if fact.contact_snapshot is not None
        else None
    )
    if fact.result_type is IMSyncResultType.ADDED:
        result: dict[str, object] = {"type": fact.result_type, "contact": contact, "entry": entry}
    elif fact.result_type is IMSyncResultType.REMOVED:
        identity = fact.identity_snapshot
        result = {
            "type": fact.result_type,
            "contact": contact,
            "last_known_identity": (
                {
                    "identity_id": str(identity.identity_id),
                    "provider_user_id": identity.provider_user_id,
                    "display_name": identity.display_name,
                    "email": identity.email,
                }
                if identity is not None
                else None
            ),
            "reason": fact.removal_reason,
        }
    elif fact.result_type is IMSyncResultType.FAILED:
        result = {
            "type": fact.result_type,
            "entry": entry,
            "reason": fact.reason_message or fact.reason_code or "failed",
        }
    elif fact.result_type is IMSyncResultType.SKIPPED:
        result = {"type": fact.result_type, "entry": entry, "contact": contact}
    else:
        result = {"type": fact.result_type, "entry": entry}
    return {"id": str(fact.id), "result": result}


def _contact_binding_payload(view: ContactIMBindingView) -> dict[str, object]:
    effective = view.effective_binding
    binding = effective.binding
    explicit_binding = (
        {
            "id": str(binding.binding_id),
            "provider": binding.provider,
            "scope": ("workspace" if effective.kind is BindingResolutionKind.WORKSPACE_OVERRIDE else "organization"),
        }
        if binding is not None and binding.binding_id is not None
        else None
    )
    return {
        "id": str(view.contact.id),
        "type": view.resolution.value,
        "name": view.contact.name,
        "email": view.contact.email,
        "avatar_url": "",
        "im_bindings": [explicit_binding] if explicit_binding is not None else [],
        "created_at": to_timestamp(view.contact.created_at.value),
    }


@console_ns.route("/workspaces/current/human-input/contacts")
class WorkspaceContactsApi(Resource):
    @console_ns.doc(params=query_params_from_model(ContactListQuery))
    @console_ns.response(200, "Success", console_ns.models[ListContactsResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        ContactListQuery.model_validate(request.args.to_dict(flat=True))
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/contacts/<uuid:contact_id>")
class WorkspaceContactApi(Resource):
    """Read one contact only when it resolves in the current workspace scope."""

    @console_ns.response(200, "Success", console_ns.models[GetContactResponse.__name__])
    @console_ns.response(404, "Contact not found or absent in the current workspace")
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def get(self, tenant_id: str, contact_id: str):
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/contact-options")
class WorkspaceContactOptionsApi(Resource):
    """Search the current workspace's selectable Contact projection for workflow editors."""

    @console_ns.doc(
        params=query_params_from_model(ContactOptionsQuery),
        description=(
            "List editor-safe Contact options for static recipient selection. "
            "The projection omits email, IM bindings, and management metadata; contacts that resolve as ABSENT "
            "or are otherwise unavailable in the current workspace are omitted."
        ),
    )
    @console_ns.response(200, "Success", console_ns.models[ListContactOptionsResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @edit_permission_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        ContactOptionsQuery.model_validate(request.args.to_dict(flat=True))
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/organization-candidates")
class WorkspaceOrganizationCandidatesApi(Resource):
    @console_ns.doc(params=query_params_from_model(OrganizationCandidatesQuery))
    @console_ns.response(200, "Success", console_ns.models[ListOrganizationCandidatesResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        OrganizationCandidatesQuery.model_validate(request.args.to_dict(flat=True))
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/contacts/platform")
class WorkspacePlatformContactsApi(Resource):
    @console_ns.expect(console_ns.models[AddPlatformContactsRequest.__name__])
    @console_ns.response(200, "Success", console_ns.models[AddPlatformContactsResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        AddPlatformContactsRequest.model_validate(console_ns.payload or {})
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/contacts/external")
class WorkspaceExternalContactsApi(Resource):
    @console_ns.expect(console_ns.models[ExternalContactCreateRequest.__name__])
    @console_ns.response(200, "Success", console_ns.models[ExternalContactCreateResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        ExternalContactCreateRequest.model_validate(console_ns.payload or {})
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/contacts/external/<uuid:contact_id>")
class WorkspaceExternalContactApi(Resource):
    @console_ns.expect(console_ns.models[ExternalContactUpdateRequest.__name__])
    @console_ns.response(200, "Success", console_ns.models[ExternalContactUpdateResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def patch(self, tenant_id: str, contact_id: str):
        ExternalContactUpdateRequest.model_validate(console_ns.payload or {})
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/contacts/remove")
class WorkspaceContactsRemoveApi(Resource):
    @console_ns.expect(console_ns.models[RemoveContactsRequest.__name__])
    @console_ns.response(200, "Success", console_ns.models[RemoveContactsResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        RemoveContactsRequest.model_validate(console_ns.payload or {})
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/im-integration")
class WorkspaceIMIntegrationApi(Resource):
    @console_ns.response(200, "Success", console_ns.models[GetIMIntegrationResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        service = _im_sync_service()
        return dump_response(
            GetIMIntegrationResponse,
            {"integration": _integration_payload(service.get_integration(tenant_id))},
        )

    @console_ns.expect(console_ns.models[UpdateIMIntegrationRequest.__name__])
    @console_ns.response(200, "Success", console_ns.models[UpdateIMIntegrationResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def put(self, tenant_id: str):
        request_model = UpdateIMIntegrationRequest.model_validate(console_ns.payload or {})
        service = _im_sync_service()
        account, _ = current_account_with_tenant()
        try:
            credentials = _request_credentials(service, tenant_id, request_model)
            expected_revision = (
                IntegrationRevisionToken(
                    IntegrationId(request_model.expected_integration_id),
                    request_model.expected_config_version,
                )
                if request_model.expected_integration_id is not None
                and request_model.expected_config_version is not None
                else None
            )
            integration = service.upsert_integration(
                workspace_id=tenant_id,
                account_id=account.id,
                credentials=credentials,
                expected_revision=expected_revision,
            )
        except IMSyncManagementError as error:
            _handle_im_sync_error(error)
        return dump_response(UpdateIMIntegrationResponse, {"integration": _integration_payload(integration)})

    @console_ns.doc(params=query_params_from_model(DeleteIMIntegrationQuery))
    @console_ns.response(204, "IM integration deleted successfully")
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def delete(self, tenant_id: str):
        query = query_params_from_request(DeleteIMIntegrationQuery)
        expected_revision = IntegrationRevisionToken(
            IntegrationId(query.expected_integration_id),
            query.expected_config_version,
        )
        try:
            _im_sync_service().delete_integration(
                workspace_id=tenant_id,
                expected_revision=expected_revision,
            )
        except IMSyncManagementError as error:
            _handle_im_sync_error(error)
        return "", HTTPStatus.NO_CONTENT


@console_ns.route("/workspaces/current/human-input/im-integration/test")
class WorkspaceIMIntegrationTestApi(Resource):
    @console_ns.expect(console_ns.models[TestIMIntegrationRequest.__name__])
    @console_ns.response(200, "Success", console_ns.models[TestIMIntegrationResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        request_model = TestIMIntegrationRequest.model_validate(console_ns.payload or {})
        service = _im_sync_service()
        try:
            diagnostic = service.test_connection(_request_credentials(service, tenant_id, request_model))
        except IMSyncManagementError as error:
            _handle_im_sync_error(error)
        return dump_response(
            TestIMIntegrationResponse,
            {"status": diagnostic.status, "message": diagnostic.message},
        )


@console_ns.route("/workspaces/current/human-input/im-sync-runs")
class WorkspaceIMSyncRunsApi(Resource):
    @console_ns.response(200, "Success", console_ns.models[CreateIMSyncRunResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        service = _im_sync_service()
        account, _ = current_account_with_tenant()
        try:
            run = service.trigger_sync(workspace_id=tenant_id, account_id=account.id)
        except IMSyncManagementError as error:
            _handle_im_sync_error(error)
        return dump_response(CreateIMSyncRunResponse, {"run": _sync_run_payload(run)})


@console_ns.route("/workspaces/current/human-input/im-sync-runs/latest")
class WorkspaceLatestIMSyncRunApi(Resource):
    @console_ns.doc(
        description=(
            "Return the latest IM sync run summary. The UI uses finished_at as the explicit sync time; "
            "the response does not include started_by."
        )
    )
    @console_ns.response(200, "Success", console_ns.models[GetLatestIMSyncRunResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        try:
            run = _im_sync_service().get_latest_sync_run(tenant_id)
        except IMSyncManagementError as error:
            _handle_im_sync_error(error)
        return dump_response(GetLatestIMSyncRunResponse, {"run": _sync_run_payload(run)})


@console_ns.route("/workspaces/current/human-input/im-sync-runs/latest/results")
class WorkspaceLatestIMSyncRunResultsApi(Resource):
    @console_ns.doc(
        params=query_params_from_model(ListLatestIMSyncRunResultsQuery),
        description=(
            "Return one required result bucket from the latest IM sync run using page and limit pagination. "
            "There is no all filter; the response contains page, limit, and total metadata without a run summary."
        ),
    )
    @console_ns.response(200, "Success", console_ns.models[ListLatestIMSyncRunResultsResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        query = ListLatestIMSyncRunResultsQuery.model_validate(request.args.to_dict(flat=True))
        try:
            page = _im_sync_service().list_latest_results(
                workspace_id=tenant_id,
                result_type=query.result,
                page=query.page,
                limit=query.limit,
            )
        except IMSyncManagementError as error:
            _handle_im_sync_error(error)
        return dump_response(
            ListLatestIMSyncRunResultsResponse,
            {
                "data": [_sync_result_payload(item) for item in page.items],
                "page": page.page,
                "limit": page.limit,
                "total": page.total,
            },
        )


@console_ns.route("/workspaces/current/human-input/im-identities")
class WorkspaceIMIdentitiesApi(Resource):
    @console_ns.doc(params=query_params_from_model(ListIMIdentitiesQuery))
    @console_ns.response(200, "Success", console_ns.models[ListIMIdentitiesResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        query = ListIMIdentitiesQuery.model_validate(request.args.to_dict(flat=True))
        try:
            page = _contact_im_binding_service().list_identities(
                workspace_id=tenant_id,
                keyword=query.keyword,
                page=query.page,
                limit=query.limit,
            )
        except ContactIMBindingError as error:
            _handle_contact_im_binding_error(error)
        return dump_response(
            ListIMIdentitiesResponse,
            {
                "data": [
                    {
                        "id": str(item.identity.id),
                        "provider": item.identity.provider,
                        "provider_user_id": item.identity.provider_user_id,
                        "display_name": item.identity.display_name,
                        "email": item.identity.email,
                        "binding_status": item.binding_status,
                    }
                    for item in page.items
                ],
                "page": page.page,
                "limit": page.limit,
                "total": page.total,
            },
        )


@console_ns.route("/workspaces/current/human-input/contacts/<uuid:contact_id>/im-override")
class WorkspaceContactIMOverrideApi(Resource):
    @console_ns.doc(
        description=(
            "Set or reset the IM override for a contact. "
            "This endpoint is used to override the IM identity for a contact in the workspace."
        ),
    )
    @console_ns.expect(console_ns.models[SetContactIMOverrideRequest.__name__])
    @console_ns.response(200, "Success", console_ns.models[SetContactIMOverrideResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def put(self, tenant_id: str, contact_id: str):
        request_model = SetContactIMOverrideRequest.model_validate(console_ns.payload or {})
        account, _ = current_account_with_tenant()
        try:
            view = _contact_im_binding_service().set_override(
                workspace_id=tenant_id,
                contact_id=str(contact_id),
                identity_id=str(request_model.identity_id),
                account_id=str(account.id),
            )
        except ContactIMBindingError as error:
            _handle_contact_im_binding_error(error)
        return dump_response(SetContactIMOverrideResponse, {"contact": _contact_binding_payload(view)})

    @console_ns.doc(
        description=(
            "Reset the IM override for a contact. "
            "This endpoint is used to clear the IM identity override for a contact in the workspace."
        ),
    )
    @console_ns.response(200, "Success", console_ns.models[ResetContactIMOverrideResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def delete(self, tenant_id: str, contact_id: str):
        try:
            view = _contact_im_binding_service().reset_override(
                workspace_id=tenant_id,
                contact_id=str(contact_id),
            )
        except ContactIMBindingError as error:
            _handle_contact_im_binding_error(error)
        return dump_response(ResetContactIMOverrideResponse, {"contact": _contact_binding_payload(view)})


@console_ns.route("/workspaces/current/human-input/contacts/<uuid:contact_id>/im-bindings")
class WorkspaceContactIMBindingsApi(Resource):
    @console_ns.doc(
        description=(
            "Set an IM binding for a contact. Used for binding an IM identity to a contact. "
            "This endpoint is not used for creating workspace IM override. "
            "For that purpose, use WorkspaceContactIMOverrideApi.put instead."
        ),
    )
    @console_ns.expect(console_ns.models[CreateIMBindingRequest.__name__])
    @console_ns.response(200, "Success", console_ns.models[CreateIMBindingResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def put(self, tenant_id: str, contact_id: str):
        request_model = CreateIMBindingRequest.model_validate(console_ns.payload or {})
        account, _ = current_account_with_tenant()
        try:
            view = _contact_im_binding_service().create_binding(
                workspace_id=tenant_id,
                contact_id=str(contact_id),
                identity_id=str(request_model.identity_id),
                account_id=str(account.id),
            )
        except ContactIMBindingError as error:
            _handle_contact_im_binding_error(error)
        return dump_response(CreateIMBindingResponse, {"contact": _contact_binding_payload(view)})

    @console_ns.response(200, "Success", console_ns.models[DeleteIMBindingResponse.__name__])
    @console_ns.doc(
        params=query_params_from_model(DeleteIMBindingQuery),
        description=(
            "Delete an IM binding for a contact. Used for removing contact IM binding information. "
            "This endpoint is not used for resetting workspace IM override. For that purpose, use "
            "WorkspaceContactIMOverrideApi.delete instead."
        ),
    )
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def delete(self, tenant_id: str, contact_id: str):
        query = query_params_from_request(DeleteIMBindingQuery)
        try:
            _contact_im_binding_service().delete_binding(
                workspace_id=tenant_id,
                contact_id=str(contact_id),
                binding_id=str(query.binding_id),
            )
        except ContactIMBindingError as error:
            _handle_contact_im_binding_error(error)
        return dump_response(DeleteIMBindingResponse, {})


@console_ns.route("/workspaces/current/human-input/contacts/batch")
class BatchGetContactsAPI(Resource):
    @console_ns.doc(
        params=query_params_from_model(BatchGetContactsQuery),
        description=(
            "Admin-only batch lookup for Contact management clients. "
            "Workflow editors must use the editor-safe contact-options/batch projection."
        ),
    )
    @console_ns.response(200, "Success", console_ns.models[BatchGetContactsResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        query_params_from_request(BatchGetContactsQuery, list_fields=("contact_ids",))
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/contact-options/batch")
class BatchGetContactOptionsAPI(Resource):
    """Resolve persisted Contact IDs through the same editor-safe selection projection."""

    @console_ns.doc(
        params=query_params_from_model(BatchGetContactOptionsQuery),
        description=(
            "Resolve Contact IDs persisted in workflow recipient configuration. "
            "Contacts that resolve as ABSENT or are otherwise unavailable in the current workspace are omitted."
        ),
    )
    @console_ns.response(200, "Success", console_ns.models[BatchGetContactOptionsResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @edit_permission_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        query_params_from_request(BatchGetContactOptionsQuery, list_fields=("contact_ids",))
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/node-data-migration")
class NodeDataMigrationAPI(Resource):
    @console_ns.doc(
        description=(
            "Migrate node data from HITLv1 to HITLv2. "
            'A missing legacy version defaults to "1"; any other explicit version is rejected. '
            "This endpoint only returns the migrated Human Input v2 node data to the client. "
            "It does not update the workflow DSL."
        ),
    )
    @console_ns.expect(console_ns.models[NodeDataMigrationPayload.__name__])
    @console_ns.response(200, "Success", console_ns.models[NodeDataMigrationResponse.__name__])
    @console_ns.response(400, "Migration failed", console_ns.models[NodeDataMigrationFailureResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @edit_permission_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        NodeDataMigrationPayload.model_validate(console_ns.payload or {})
        _raise_stub_not_implemented()


@console_ns.route("/workspaces/current/human-input/email-provider")
class HumanInputEmailProviderAPI(Resource):
    @console_ns.doc(description="Retrieve the current email provider settings for human input")
    @console_ns.response(200, "Success", console_ns.models[GetEmailProviderResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        _raise_stub_not_implemented()

    @console_ns.doc(description="update the current email provider settings for human input")
    @console_ns.expect(console_ns.models[SetEmailProviderRequest.__name__])
    @console_ns.response(200, "Success", console_ns.models[SetEmailProviderResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @is_admin_or_owner_required
    @with_current_tenant_id
    def put(self, tenant_id: str):
        SetEmailProviderRequest.model_validate(console_ns.payload or {})
        _raise_stub_not_implemented()
