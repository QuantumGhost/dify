"""Controller tests for the implemented Human Input IM integration and sync routes."""

from datetime import UTC, datetime
from http import HTTPStatus
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from controllers.common.human_input_v2_contracts import (
    FeishuIMIntegrationCredentials,
    UpdateIMIntegrationRequest,
)
from controllers.common.human_input_v2_contracts import (
    TestIMIntegrationRequest as IMIntegrationTestRequest,
)
from controllers.console.workspace import human_input as controller
from core.human_input_v2.contact_directory import Contact, ContactResolution
from core.human_input_v2.entities import (
    IMIdentityBindingStatus,
    IMIntegrationStatus,
    IMProvider,
    IMSyncResultType,
)
from core.human_input_v2.im_integration import (
    BindingResolutionKind,
    BindingResolutionResult,
    EncryptedCredentials,
    IMIdentity,
    IMIntegration,
    IMSyncRun,
    IntegrationRevisionToken,
    ProviderTenantIdentity,
)
from core.human_input_v2.shared import (
    AccountId,
    ContactId,
    IMBindingId,
    IMIdentityId,
    IMSyncRunId,
    IntegrationId,
    UtcTimestamp,
    WorkspaceId,
)
from services.human_input_v2.im_contact_binding import (
    ContactIMBindingError,
    ContactIMBindingView,
    IMIdentityListItem,
)
from services.human_input_v2.im_provider import (
    _PROVIDER_REGISTRY,
    ProviderConnectionDiagnostic,
    _CredentialField,
    _ProviderRegistration,
    create_provider_credentials,
)
from services.human_input_v2.im_sync import IMSyncManagementError, IMSyncManagementService

_NOW = UtcTimestamp(datetime(2026, 7, 26, 8, tzinfo=UTC))


def _integration() -> IMIntegration:
    return IMIntegration.create(
        integration_id=IntegrationId("integration-1"),
        workspace_id=WorkspaceId("workspace-1"),
        provider_tenant=ProviderTenantIdentity(IMProvider.FEISHU, "tenant-1"),
        encrypted_credentials=EncryptedCredentials.from_mapping(
            {"app_id": "app-id", "encrypted_app_secret": "encrypted-secret"}
        ),
        configured_by_account_id=AccountId("account-1"),
        callback_url=None,
        now=_NOW,
    ).record_diagnostics(
        status=IMIntegrationStatus.CONNECTED,
        safe_status_reason=None,
        checked_at=_NOW,
    )


def _run() -> IMSyncRun:
    return IMSyncRun.create(
        sync_run_id=IMSyncRunId("run-1"),
        integration_revision=IntegrationRevisionToken(IntegrationId("integration-1"), 2),
        provider=IMProvider.FEISHU,
        started_by_account_id=AccountId("account-1"),
        now=_NOW,
    )


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


def _contact_view(
    kind: BindingResolutionKind = BindingResolutionKind.NOT_AVAILABLE,
) -> ContactIMBindingView:
    return ContactIMBindingView(
        contact=Contact.workspace_member(
            contact_id=ContactId("contact-1"),
            workspace_id=WorkspaceId("workspace-1"),
            account_id=AccountId("account-1"),
            name="Reviewer",
            email="reviewer@example.com",
            now=_NOW,
        ),
        resolution=ContactResolution.WORKSPACE,
        effective_binding=BindingResolutionResult(kind, None),
    )


def _request_payload() -> dict[str, object]:
    return {
        "credentials": {
            "provider": "feishu",
            "app_id": "app-id",
            "app_secret": "secret",
        }
    }


def test_service_factory_wires_repository_and_celery_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = object()
    repository_type = MagicMock(return_value=repository)
    service_type = MagicMock()
    session_maker = object()
    delay = object()

    monkeypatch.setattr(controller, "db", SimpleNamespace(engine=object()))
    monkeypatch.setattr(controller, "sessionmaker", MagicMock(return_value=session_maker))
    monkeypatch.setattr(controller, "SQLAlchemyIMControlPlaneRepository", repository_type)
    monkeypatch.setattr(controller, "IMSyncManagementService", service_type)
    monkeypatch.setattr(controller.human_input_im_sync_task, "delay", delay)

    controller._im_sync_service()

    repository_type.assert_called_once_with(session_maker)
    service_type.assert_called_once_with(repository, delay)


def test_contact_service_factory_wires_repositories_and_edition_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    session_maker = object()
    im_repository = object()
    contact_repository = object()
    im_repository_type = MagicMock(return_value=im_repository)
    contact_repository_type = MagicMock(return_value=contact_repository)
    service_type = MagicMock()

    monkeypatch.setattr(controller, "db", SimpleNamespace(engine=object()))
    monkeypatch.setattr(controller, "sessionmaker", MagicMock(return_value=session_maker))
    monkeypatch.setattr(controller, "SQLAlchemyIMControlPlaneRepository", im_repository_type)
    monkeypatch.setattr(controller, "SQLAlchemyContactDirectoryRepository", contact_repository_type)
    monkeypatch.setattr(controller, "ContactIMBindingService", service_type)
    monkeypatch.setattr(controller.dify_config, "ENTERPRISE_ENABLED", True)

    controller._contact_im_binding_service()

    im_repository_type.assert_called_once_with(session_maker)
    contact_repository_type.assert_called_once_with(session_maker)
    service_type.assert_called_once_with(
        im_repository,
        contact_repository,
        workspace_overrides_enabled=True,
    )


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("integration_not_configured", HTTPStatus.CONFLICT),
        ("provider_connection_failed", HTTPStatus.BAD_GATEWAY),
        ("deployment_integration_unsupported", HTTPStatus.CONFLICT),
        ("sync_run_not_found", HTTPStatus.NOT_FOUND),
        ("unsupported_provider", HTTPStatus.BAD_REQUEST),
        ("unknown", HTTPStatus.BAD_REQUEST),
    ],
)
def test_sync_errors_map_to_safe_http_status(app: Flask, code: str, status: HTTPStatus) -> None:
    with app.test_request_context("/"), pytest.raises(HTTPException) as error:
        controller._handle_im_sync_error(IMSyncManagementError(code, "safe"))

    assert error.value.code == status
    assert "safe" in str(error.value)
    assert error.value.data == {"code": code, "message": "safe", "status": status}


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("contact_not_found", HTTPStatus.NOT_FOUND),
        ("identity_not_found", HTTPStatus.NOT_FOUND),
        ("binding_not_found", HTTPStatus.NOT_FOUND),
        ("workspace_override_unsupported", HTTPStatus.FORBIDDEN),
        ("integration_not_configured", HTTPStatus.CONFLICT),
        ("deployment_integration_unsupported", HTTPStatus.CONFLICT),
        ("external_contact_not_supported", HTTPStatus.CONFLICT),
        ("identity_already_bound", HTTPStatus.CONFLICT),
        ("binding_conflict", HTTPStatus.CONFLICT),
        ("contact_unavailable", HTTPStatus.SERVICE_UNAVAILABLE),
        ("unknown", HTTPStatus.BAD_REQUEST),
    ],
)
def test_contact_binding_errors_map_to_safe_http_status(app: Flask, code: str, status: HTTPStatus) -> None:
    with app.test_request_context("/"), pytest.raises(HTTPException) as error:
        controller._handle_contact_im_binding_error(ContactIMBindingError(code, "safe"))

    assert error.value.code == status
    assert "safe" in str(error.value)
    assert error.value.data == {"code": code, "message": "safe", "status": status}


def test_payload_helpers_serialize_not_configured_integration_and_run() -> None:
    assert controller._integration_payload(None)["status"] is IMIntegrationStatus.NOT_CONFIGURED

    integration_payload = controller._integration_payload(_integration())
    run_payload = controller._sync_run_payload(_run())

    assert integration_payload["integration_id"] == "integration-1"
    assert integration_payload["config_version"] == 1
    assert run_payload["id"] == "run-1"
    assert run_payload["integration_config_version"] == 2
    assert run_payload["result_counts"] == {
        "added": 0,
        "not_matched": 0,
        "failed": 0,
        "removed": 0,
        "skipped": 0,
    }


def test_contact_binding_payload_exposes_only_explicit_effective_binding() -> None:
    binding = SimpleNamespace(
        binding_id=IMBindingId("binding-1"),
        provider=IMProvider.FEISHU,
    )
    view = _contact_view(BindingResolutionKind.WORKSPACE_OVERRIDE)
    view = ContactIMBindingView(
        view.contact,
        view.resolution,
        BindingResolutionResult(
            BindingResolutionKind.WORKSPACE_OVERRIDE,
            SimpleNamespace(binding_id=binding.binding_id, provider=binding.provider),
        ),
    )

    payload = controller._contact_binding_payload(view)

    assert payload["type"] == "workspace"
    assert payload["im_bindings"] == [
        {
            "id": "binding-1",
            "provider": IMProvider.FEISHU,
            "scope": "workspace",
        }
    ]


def test_request_credentials_supports_plain_and_preserved_secrets() -> None:
    service = MagicMock()
    service.prepare_credentials.side_effect = create_provider_credentials
    service.load_plaintext_credentials.return_value = None
    plain = controller._request_credentials(
        service,
        "workspace-1",
        UpdateIMIntegrationRequest.model_validate(_request_payload()),
    )
    assert plain == create_provider_credentials(
        IMProvider.FEISHU,
        {"app_id": "app-id", "app_secret": "secret"},
    )

    service.load_plaintext_credentials.return_value = create_provider_credentials(
        IMProvider.FEISHU,
        {
            "app_id": "app-id",
            "app_secret": "current-secret",
            "verification_token": "current-verification",
            "encrypt_key": "current-encrypt",
        },
    )
    preserved = controller._request_credentials(
        service,
        "workspace-1",
        IMIntegrationTestRequest.model_validate(
            {
                "credentials": {
                    "provider": "feishu",
                    "app_id": "app-id",
                    "app_secret": {"tag": "preserve_original_value"},
                    "verification_token": {"tag": "preserve_original_value"},
                    "encrypt_key": {"tag": "preserve_original_value"},
                }
            }
        ),
    )
    assert preserved.to_mapping() == {
        "app_id": "app-id",
        "app_secret": "current-secret",
        "verification_token": "current-verification",
        "encrypt_key": "current-encrypt",
    }


def test_request_credentials_uses_registry_fields_without_provider_specific_service_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        _PROVIDER_REGISTRY,
        IMProvider.SLACK,
        _ProviderRegistration(
            credential_fields=(
                _CredentialField("client_id", "client_id", required=True, strip=True),
                _CredentialField("client_secret", "encrypted_client_secret", required=True),
                _CredentialField("signing_secret", "encrypted_signing_secret", required=True),
                _CredentialField("bot_token", "encrypted_bot_token", required=True),
            ),
            client_factory=MagicMock(),
        ),
    )
    service = IMSyncManagementService(MagicMock(), MagicMock())
    request_model = IMIntegrationTestRequest.model_validate(
        {
            "credentials": {
                "provider": "slack",
                "client_id": " client-id ",
                "client_secret": "client-secret",
                "signing_secret": "signing-secret",
                "bot_token": "bot-token",
            }
        }
    )

    credentials = controller._request_credentials(service, "workspace-1", request_model)

    assert credentials.provider is IMProvider.SLACK
    assert credentials.to_mapping() == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "signing_secret": "signing-secret",
        "bot_token": "bot-token",
    }


def test_request_credentials_rejects_unsupported_or_unavailable_preserve_value() -> None:
    service = MagicMock()
    service.load_plaintext_credentials.return_value = None
    service.prepare_credentials.side_effect = IMSyncManagementError(
        "unsupported_provider",
        "Directory synchronization is not supported.",
    )
    with pytest.raises(IMSyncManagementError) as unsupported:
        controller._request_credentials(
            service,
            "workspace-1",
            IMIntegrationTestRequest.model_validate(
                {
                    "credentials": {
                        "provider": "slack",
                        "client_id": "client",
                        "client_secret": "secret",
                        "signing_secret": "signing",
                        "bot_token": "token",
                    }
                }
            ),
        )
    assert unsupported.value.code == "unsupported_provider"

    service.prepare_credentials.side_effect = None
    with pytest.raises(IMSyncManagementError) as stale:
        controller._request_credentials(
            service,
            "workspace-1",
            IMIntegrationTestRequest.model_validate(
                {
                    "credentials": {
                        "provider": "feishu",
                        "app_id": "app-id",
                        "app_secret": {"tag": "preserve_original_value"},
                    }
                }
            ),
        )
    assert stale.value.code == "stale_revision"


def test_request_credentials_rejects_missing_application_secret() -> None:
    service = MagicMock()
    service.load_plaintext_credentials.return_value = None
    service.prepare_credentials.side_effect = IMSyncManagementError(
        "invalid_credentials",
        "The IM integration credentials are invalid.",
    )
    request_model = MagicMock()
    request_model.credentials = FeishuIMIntegrationCredentials.model_construct(
        provider=IMProvider.FEISHU,
        app_id="app-id",
        app_secret=None,
        verification_token=None,
        encrypt_key=None,
    )

    with pytest.raises(IMSyncManagementError) as error:
        controller._request_credentials(service, "workspace-1", request_model)

    assert error.value.code == "invalid_credentials"


@pytest.mark.parametrize(
    "result_type",
    [
        IMSyncResultType.ADDED,
        IMSyncResultType.REMOVED,
        IMSyncResultType.FAILED,
        IMSyncResultType.SKIPPED,
        IMSyncResultType.NOT_MATCHED,
    ],
)
def test_sync_result_payload_covers_each_canonical_bucket(result_type: IMSyncResultType) -> None:
    contact = SimpleNamespace(contact_id="contact-1", name="Reviewer")
    identity = SimpleNamespace(
        identity_id="identity-1",
        provider_user_id="provider-user-1",
        display_name="Reviewer",
        email="reviewer@example.com",
    )
    fact = SimpleNamespace(
        id="result-1",
        result_type=result_type,
        provider_user_id="provider-user-1",
        display_name="Reviewer",
        email="reviewer@example.com",
        contact_snapshot=contact,
        identity_snapshot=identity,
        reason_message="safe failure",
        reason_code="failure",
        removal_reason="not_present_in_directory",
        created_at=_NOW,
    )

    payload = controller._sync_result_payload(fact)

    assert payload["result"]["type"] is result_type


def test_removed_result_payload_hides_unavailable_contact_pii_and_keeps_last_known_identity() -> None:
    identity = SimpleNamespace(
        identity_id="identity-removed",
        provider_user_id="provider-user-removed",
        display_name="Removed Identity",
        email="removed-identity@example.com",
    )
    fact = SimpleNamespace(
        id="result-removed",
        result_type=IMSyncResultType.REMOVED,
        provider_user_id="provider-user-removed",
        display_name="Removed Identity",
        email="removed-identity@example.com",
        contact_id=None,
        contact_snapshot=None,
        identity_snapshot=identity,
        reason_message=None,
        reason_code="not_present_in_directory",
        removal_reason="not_present_in_directory",
        created_at=_NOW,
    )

    payload = controller._sync_result_payload(fact)

    result = payload["result"]
    assert result["contact"] is None
    assert result["last_known_identity"] == {
        "identity_id": "identity-removed",
        "provider_user_id": "provider-user-removed",
        "display_name": "Removed Identity",
        "email": "removed-identity@example.com",
    }
    assert result["reason"] == "not_present_in_directory"


def test_integration_get_and_put_routes_delegate_to_service(app: Flask) -> None:
    service = MagicMock()
    service.get_integration.return_value = _integration()
    service.load_plaintext_credentials.return_value = None
    service.upsert_integration.return_value = _integration()
    api = controller.WorkspaceIMIntegrationApi()
    get_method = unwrap(api.get)
    put_method = unwrap(api.put)

    with (
        app.test_request_context("/", json=_request_payload()),
        patch.object(controller, "_im_sync_service", return_value=service),
        patch.object(controller, "current_account_with_tenant", return_value=(SimpleNamespace(id="account-1"), None)),
        patch.object(controller, "dump_response", side_effect=lambda _model, payload: payload),
    ):
        get_result = get_method(api, "workspace-1")
        put_result = put_method(api, "workspace-1")

    assert get_result["integration"]["integration_id"] == "integration-1"
    assert put_result["integration"]["status"] is IMIntegrationStatus.CONNECTED
    service.upsert_integration.assert_called_once()


def test_integration_delete_route_uses_complete_cas_and_returns_empty_204(app: Flask) -> None:
    service = MagicMock()
    api = controller.WorkspaceIMIntegrationApi()

    with (
        app.test_request_context(
            "/?expected_integration_id=integration-1&expected_config_version=2",
        ),
        patch.object(controller, "_im_sync_service", return_value=service),
    ):
        result = unwrap(api.delete)(api, "workspace-1")

    assert result == ("", HTTPStatus.NO_CONTENT)
    service.delete_integration.assert_called_once_with(
        workspace_id="workspace-1",
        expected_revision=IntegrationRevisionToken(IntegrationId("integration-1"), 2),
    )


def test_connection_test_route_returns_safe_diagnostic(app: Flask) -> None:
    service = MagicMock()
    service.load_plaintext_credentials.return_value = None
    service.test_connection.return_value = ProviderConnectionDiagnostic(
        status=IMIntegrationStatus.CONNECTED,
        message="Connection successful.",
        provider_tenant=ProviderTenantIdentity(IMProvider.FEISHU, "tenant-1"),
    )
    api = controller.WorkspaceIMIntegrationTestApi()
    method = unwrap(api.post)

    with (
        app.test_request_context("/", json=_request_payload()),
        patch.object(controller, "_im_sync_service", return_value=service),
        patch.object(controller, "dump_response", side_effect=lambda _model, payload: payload),
    ):
        result = method(api, "workspace-1")

    assert result == {"status": IMIntegrationStatus.CONNECTED, "message": "Connection successful."}


def test_sync_trigger_and_latest_routes_return_run_summary(app: Flask) -> None:
    service = MagicMock()
    service.trigger_sync.return_value = _run()
    service.get_latest_sync_run.return_value = _run()
    trigger_api = controller.WorkspaceIMSyncRunsApi()
    latest_api = controller.WorkspaceLatestIMSyncRunApi()

    with (
        app.test_request_context("/"),
        patch.object(controller, "_im_sync_service", return_value=service),
        patch.object(controller, "current_account_with_tenant", return_value=(SimpleNamespace(id="account-1"), None)),
        patch.object(controller, "dump_response", side_effect=lambda _model, payload: payload),
    ):
        triggered = unwrap(trigger_api.post)(trigger_api, "workspace-1")
        latest = unwrap(latest_api.get)(latest_api, "workspace-1")

    assert triggered["run"]["id"] == "run-1"
    assert latest["run"]["id"] == "run-1"


def test_latest_results_route_validates_query_and_returns_page(app: Flask) -> None:
    service = MagicMock()
    service.list_latest_results.return_value = SimpleNamespace(items=(), total=3, page=2, limit=10)
    api = controller.WorkspaceLatestIMSyncRunResultsApi()

    with (
        app.test_request_context("/?result=failed&page=2&limit=10"),
        patch.object(controller, "_im_sync_service", return_value=service),
        patch.object(controller, "dump_response", side_effect=lambda _model, payload: payload),
    ):
        result = unwrap(api.get)(api, "workspace-1")

    assert result == {"data": [], "page": 2, "limit": 10, "total": 3}
    service.list_latest_results.assert_called_once_with(
        workspace_id="workspace-1",
        result_type=IMSyncResultType.FAILED,
        page=2,
        limit=10,
    )


@pytest.mark.parametrize("query", ["", "?result=all", "?result=created_binding"])
def test_latest_results_route_rejects_missing_or_noncanonical_bucket(app: Flask, query: str) -> None:
    api = controller.WorkspaceLatestIMSyncRunResultsApi()

    with app.test_request_context(f"/{query}"), pytest.raises(ValidationError):
        unwrap(api.get)(api, "workspace-1")


def test_identity_search_route_returns_workspace_binding_status(app: Flask) -> None:
    service = MagicMock()
    service.list_identities.return_value = SimpleNamespace(
        items=(IMIdentityListItem(_identity(), IMIdentityBindingStatus.BOUND),),
        total=1,
        page=2,
        limit=5,
    )
    api = controller.WorkspaceIMIdentitiesApi()

    with (
        app.test_request_context("/?keyword=provider-user-1&page=2&limit=5"),
        patch.object(controller, "_contact_im_binding_service", return_value=service),
        patch.object(controller, "dump_response", side_effect=lambda _model, payload: payload),
    ):
        result = unwrap(api.get)(api, "workspace-1")

    assert result["data"] == [
        {
            "id": "identity-1",
            "provider": IMProvider.FEISHU,
            "provider_user_id": "provider-user-1",
            "display_name": "Reviewer",
            "email": "reviewer@example.com",
            "binding_status": IMIdentityBindingStatus.BOUND,
        }
    ]
    assert (result["page"], result["limit"], result["total"]) == (2, 5, 1)
    service.list_identities.assert_called_once_with(
        workspace_id="workspace-1",
        keyword="provider-user-1",
        page=2,
        limit=5,
    )


def test_identity_search_route_translates_deployment_fallback_to_stable_conflict(app: Flask) -> None:
    service = MagicMock()
    message = "Deployment-wide identities are unavailable."
    service.list_identities.side_effect = ContactIMBindingError(
        "deployment_integration_unsupported",
        message,
    )
    api = controller.WorkspaceIMIdentitiesApi()

    with (
        app.test_request_context("/?page=1&limit=20"),
        patch.object(controller, "_contact_im_binding_service", return_value=service),
        pytest.raises(HTTPException) as error,
    ):
        unwrap(api.get)(api, "workspace-1")

    assert error.value.code == HTTPStatus.CONFLICT
    assert error.value.data == {
        "code": "deployment_integration_unsupported",
        "message": message,
        "status": HTTPStatus.CONFLICT,
    }


@pytest.mark.parametrize("route", ["latest", "results"])
def test_sync_data_routes_translate_deployment_fallback_to_stable_conflict(
    app: Flask,
    route: str,
) -> None:
    service = MagicMock()
    message = "Deployment-wide sync data is unavailable."
    fallback_error = IMSyncManagementError("deployment_integration_unsupported", message)
    if route == "latest":
        service.get_latest_sync_run.side_effect = fallback_error
        api = controller.WorkspaceLatestIMSyncRunApi()
        request_path = "/"
    else:
        service.list_latest_results.side_effect = fallback_error
        api = controller.WorkspaceLatestIMSyncRunResultsApi()
        request_path = "/?result=failed&page=1&limit=20"

    with (
        app.test_request_context(request_path),
        patch.object(controller, "_im_sync_service", return_value=service),
        pytest.raises(HTTPException) as error,
    ):
        unwrap(api.get)(api, "workspace-1")

    assert error.value.code == HTTPStatus.CONFLICT
    assert error.value.data == {
        "code": "deployment_integration_unsupported",
        "message": message,
        "status": HTTPStatus.CONFLICT,
    }


def test_contact_binding_routes_delegate_create_and_delete(app: Flask) -> None:
    service = MagicMock()
    service.create_binding.return_value = _contact_view()
    api = controller.WorkspaceContactIMBindingsApi()

    with (
        patch.object(controller, "_contact_im_binding_service", return_value=service),
        patch.object(controller, "current_account_with_tenant", return_value=(SimpleNamespace(id="account-1"), None)),
        patch.object(controller, "_contact_binding_payload", return_value={"id": "contact-1"}),
        patch.object(controller, "dump_response", side_effect=lambda _model, payload: payload),
    ):
        with app.test_request_context("/", json={"identity_id": "identity-1"}):
            created = unwrap(api.put)(api, "workspace-1", "contact-1")
        with app.test_request_context("/?binding_id=binding-1"):
            deleted = unwrap(api.delete)(api, "workspace-1", "contact-1")

    assert created == {"contact": {"id": "contact-1"}}
    assert deleted == {}
    service.create_binding.assert_called_once_with(
        workspace_id="workspace-1",
        contact_id="contact-1",
        identity_id="identity-1",
        account_id="account-1",
    )
    service.delete_binding.assert_called_once_with(
        workspace_id="workspace-1",
        contact_id="contact-1",
        binding_id="binding-1",
    )


def test_contact_override_routes_delegate_set_and_reset(app: Flask) -> None:
    service = MagicMock()
    service.set_override.return_value = _contact_view()
    service.reset_override.return_value = _contact_view()
    api = controller.WorkspaceContactIMOverrideApi()

    with (
        patch.object(controller, "_contact_im_binding_service", return_value=service),
        patch.object(controller, "current_account_with_tenant", return_value=(SimpleNamespace(id="account-1"), None)),
        patch.object(controller, "_contact_binding_payload", return_value={"id": "contact-1"}),
        patch.object(controller, "dump_response", side_effect=lambda _model, payload: payload),
    ):
        with app.test_request_context("/", json={"identity_id": "identity-1"}):
            set_result = unwrap(api.put)(api, "workspace-1", "contact-1")
        with app.test_request_context("/"):
            reset_result = unwrap(api.delete)(api, "workspace-1", "contact-1")

    assert set_result == {"contact": {"id": "contact-1"}}
    assert reset_result == {"contact": {"id": "contact-1"}}
    service.set_override.assert_called_once_with(
        workspace_id="workspace-1",
        contact_id="contact-1",
        identity_id="identity-1",
        account_id="account-1",
    )
    service.reset_override.assert_called_once_with(
        workspace_id="workspace-1",
        contact_id="contact-1",
    )


def test_implemented_routes_translate_service_errors(app: Flask) -> None:
    service = MagicMock()
    service.load_plaintext_credentials.return_value = None
    service.upsert_integration.side_effect = IMSyncManagementError("stale_revision", "stale")
    service.test_connection.side_effect = IMSyncManagementError("provider_connection_failed", "failed")
    service.trigger_sync.side_effect = IMSyncManagementError("integration_not_configured", "missing")
    service.get_latest_sync_run.side_effect = IMSyncManagementError("sync_run_not_found", "missing")
    integration_api = controller.WorkspaceIMIntegrationApi()
    connection_api = controller.WorkspaceIMIntegrationTestApi()
    trigger_api = controller.WorkspaceIMSyncRunsApi()
    latest_api = controller.WorkspaceLatestIMSyncRunApi()

    with (
        patch.object(controller, "_im_sync_service", return_value=service),
        patch.object(controller, "current_account_with_tenant", return_value=(SimpleNamespace(id="account-1"), None)),
    ):
        with (
            app.test_request_context("/", json=_request_payload()),
            pytest.raises(HTTPException) as update_error,
        ):
            unwrap(integration_api.put)(integration_api, "workspace-1")
        assert update_error.value.code == HTTPStatus.CONFLICT

        with (
            app.test_request_context("/", json=_request_payload()),
            pytest.raises(HTTPException) as connection_error,
        ):
            unwrap(connection_api.post)(connection_api, "workspace-1")
        assert connection_error.value.code == HTTPStatus.BAD_GATEWAY

        with app.test_request_context("/"), pytest.raises(HTTPException) as trigger_error:
            unwrap(trigger_api.post)(trigger_api, "workspace-1")
        assert trigger_error.value.code == HTTPStatus.CONFLICT

        with app.test_request_context("/"), pytest.raises(HTTPException) as latest_error:
            unwrap(latest_api.get)(latest_api, "workspace-1")
        assert latest_error.value.code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("method_name", ["put", "delete"])
def test_override_routes_translate_workspace_override_unsupported_to_forbidden(
    app: Flask,
    method_name: str,
) -> None:
    service = MagicMock()
    if method_name == "put":
        service.set_override.side_effect = ContactIMBindingError(
            "workspace_override_unsupported",
            "Workspace IM overrides require Enterprise Edition.",
        )
    else:
        service.reset_override.side_effect = ContactIMBindingError(
            "workspace_override_unsupported",
            "Workspace IM overrides require Enterprise Edition.",
        )
    api = controller.WorkspaceContactIMOverrideApi()
    method = unwrap(getattr(api, method_name))
    request_kwargs = {"json": {"identity_id": "identity-1"}} if method_name == "put" else {}

    with (
        app.test_request_context("/", **request_kwargs),
        patch.object(controller, "_contact_im_binding_service", return_value=service),
        patch.object(controller, "current_account_with_tenant", return_value=(SimpleNamespace(id="account-1"), None)),
        pytest.raises(HTTPException) as error,
    ):
        method(api, "workspace-1", "contact-1")

    assert error.value.code == HTTPStatus.FORBIDDEN
    assert "Enterprise Edition" in str(error.value)
