from flask_restx import Resource
from pydantic import BaseModel
from werkzeug.exceptions import BadRequest

from controllers.common.schema import register_response_schema_models
from controllers.console import console_ns
from controllers.console.wraps import (
    account_initialization_required,
    setup_required,
    with_current_tenant_id,
)
from libs.helper import dump_response
from libs.login import login_required
from services.human_input_im.app_config_service import IMProvider, resolve_im_app_context


class IMAppContextResponse(BaseModel):
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


register_response_schema_models(console_ns, IMAppContextResponse)


@console_ns.route("/workspaces/current/im-apps/<string:provider>")
class WorkspaceIMAppApi(Resource):
    @console_ns.response(200, "Success", console_ns.models[IMAppContextResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_tenant_id
    def get(self, tenant_id: str, provider: str):
        try:
            resolved_provider = IMProvider(provider)
        except ValueError as exc:
            raise BadRequest(str(exc))
        context = resolve_im_app_context(provider=resolved_provider, tenant_id=tenant_id)
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
