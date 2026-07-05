"""Console APIs for IM app config context and management seams.

Runtime resolution, tenant self-built config persistence, and install lifecycle
inspection share a namespace but intentionally stay as separate endpoints so the
backend contract does not imply that every provider uses the same storage path.
"""

from flask_restx import Resource
from pydantic import BaseModel, ConfigDict
from werkzeug.exceptions import BadRequest, UnprocessableEntity

from controllers.common.fields import SimpleResultResponse
from controllers.common.schema import register_response_schema_models, register_schema_models
from controllers.console import console_ns
from controllers.console.wraps import (
    account_initialization_required,
    edit_permission_required,
    setup_required,
    with_current_tenant_id,
)
from extensions.ext_database import db
from libs.helper import dump_response
from libs.login import login_required
from models.im_integration import IMInstallMode
from services.entities.im_app_entities import (
    IMAppInstallationRecord,
    IMSelfBuiltTenantConfigRecord,
    UpsertIMAppInstallation,
    UpsertIMSelfBuiltTenantConfig,
)
from services.errors.im_app_config import IMAppConfigValidationError
from services.human_input_im.app_config_management_service import (
    delete_tenant_self_built_config,
    get_app_installation,
    get_tenant_self_built_config,
    uninstall_app_installation,
    upsert_app_installation,
    upsert_tenant_self_built_config,
)
from services.human_input_im.app_config_service import IMProvider, resolve_im_app_context


class IMAppContextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: IMProvider
    install_mode: str
    scope_type: str
    scope_id: str
    status: str
    token_status: str
    install_status: str
    event_mode: str | None = None
    app_id_configured: bool
    app_secret_configured: bool
    errors: list[str]


class UpsertIMSelfBuiltTenantConfigPayload(UpsertIMSelfBuiltTenantConfig):
    pass


class UpsertIMAppInstallationPayload(UpsertIMAppInstallation):
    pass


class IMSelfBuiltTenantConfigEnvelopeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: IMSelfBuiltTenantConfigRecord | None = None


class IMAppInstallationEnvelopeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: IMAppInstallationRecord | None = None


register_schema_models(console_ns, UpsertIMSelfBuiltTenantConfigPayload, UpsertIMAppInstallationPayload)
register_response_schema_models(
    console_ns,
    SimpleResultResponse,
    IMAppContextResponse,
    IMSelfBuiltTenantConfigRecord,
    IMSelfBuiltTenantConfigEnvelopeResponse,
    IMAppInstallationRecord,
    IMAppInstallationEnvelopeResponse,
)


def _parse_provider(provider: str) -> IMProvider:
    try:
        return IMProvider(provider)
    except ValueError as exc:
        raise BadRequest(str(exc))


def _parse_install_mode(install_mode: str) -> IMInstallMode:
    try:
        return IMInstallMode(install_mode)
    except ValueError as exc:
        raise BadRequest(str(exc))


@console_ns.route("/workspaces/current/im-apps/<string:provider>")
class WorkspaceIMAppApi(Resource):
    @console_ns.response(200, "Success", console_ns.models[IMAppContextResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_tenant_id
    def get(self, tenant_id: str, provider: str):
        context = resolve_im_app_context(provider=_parse_provider(provider), tenant_id=tenant_id)
        return dump_response(
            IMAppContextResponse,
            {
                "provider": context.provider,
                "install_mode": context.install_mode.value,
                "scope_type": context.scope_type.value,
                "scope_id": context.scope_id,
                "status": context.status.value,
                "token_status": context.token_status.value,
                "install_status": context.install_status.value,
                "event_mode": context.event_mode.value if context.event_mode else None,
                "app_id_configured": bool(context.app_id),
                "app_secret_configured": context.app_secret_configured,
                "errors": context.errors,
            },
        ), 200


@console_ns.route("/workspaces/current/im-apps/<string:provider>/self-built-config")
class WorkspaceIMSelfBuiltTenantConfigApi(Resource):
    @console_ns.response(200, "Success", console_ns.models[IMSelfBuiltTenantConfigEnvelopeResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_tenant_id
    def get(self, tenant_id: str, provider: str):
        config = get_tenant_self_built_config(
            session=db.session,
            tenant_id=tenant_id,
            provider=_parse_provider(provider),
        )
        return dump_response(IMSelfBuiltTenantConfigEnvelopeResponse, {"data": config}), 200

    @console_ns.expect(console_ns.models[UpsertIMSelfBuiltTenantConfigPayload.__name__])
    @console_ns.response(200, "Success", console_ns.models[IMSelfBuiltTenantConfigRecord.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @edit_permission_required
    @with_current_tenant_id
    def put(self, tenant_id: str, provider: str):
        payload = UpsertIMSelfBuiltTenantConfigPayload.model_validate(console_ns.payload or {})
        try:
            config = upsert_tenant_self_built_config(
                session=db.session,
                tenant_id=tenant_id,
                provider=_parse_provider(provider),
                request=payload,
            )
        except IMAppConfigValidationError as exc:
            raise UnprocessableEntity(str(exc))

        db.session.commit()
        return dump_response(IMSelfBuiltTenantConfigRecord, config), 200

    @console_ns.response(200, "Success", console_ns.models[SimpleResultResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @edit_permission_required
    @with_current_tenant_id
    def delete(self, tenant_id: str, provider: str):
        delete_tenant_self_built_config(
            session=db.session,
            tenant_id=tenant_id,
            provider=_parse_provider(provider),
        )
        db.session.commit()
        return dump_response(SimpleResultResponse, {"result": "success"}), 200


@console_ns.route("/workspaces/current/im-apps/<string:provider>/installations/<string:install_mode>")
class WorkspaceIMAppInstallationApi(Resource):
    @console_ns.response(200, "Success", console_ns.models[IMAppInstallationEnvelopeResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_tenant_id
    def get(self, tenant_id: str, provider: str, install_mode: str):
        installation = get_app_installation(
            session=db.session,
            tenant_id=tenant_id,
            provider=_parse_provider(provider),
            install_mode=_parse_install_mode(install_mode),
        )
        return dump_response(IMAppInstallationEnvelopeResponse, {"data": installation}), 200

    @console_ns.expect(console_ns.models[UpsertIMAppInstallationPayload.__name__])
    @console_ns.response(200, "Success", console_ns.models[IMAppInstallationRecord.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @edit_permission_required
    @with_current_tenant_id
    def put(self, tenant_id: str, provider: str, install_mode: str):
        payload = UpsertIMAppInstallationPayload.model_validate(console_ns.payload or {})
        try:
            installation = upsert_app_installation(
                session=db.session,
                tenant_id=tenant_id,
                provider=_parse_provider(provider),
                install_mode=_parse_install_mode(install_mode),
                request=payload,
            )
        except IMAppConfigValidationError as exc:
            raise UnprocessableEntity(str(exc))

        db.session.commit()
        return dump_response(IMAppInstallationRecord, installation), 200

    @console_ns.response(200, "Success", console_ns.models[SimpleResultResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @edit_permission_required
    @with_current_tenant_id
    def delete(self, tenant_id: str, provider: str, install_mode: str):
        uninstall_app_installation(
            session=db.session,
            tenant_id=tenant_id,
            provider=_parse_provider(provider),
            install_mode=_parse_install_mode(install_mode),
        )
        db.session.commit()
        return dump_response(SimpleResultResponse, {"result": "success"}), 200
