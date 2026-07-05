from flask_restx import Resource
from pydantic import BaseModel, Field

from controllers.common.fields import SimpleResultResponse
from controllers.common.schema import register_response_schema_models, register_schema_models
from controllers.console import console_ns
from controllers.console.wraps import account_initialization_required, setup_required, with_current_tenant_id, with_current_user
from extensions.ext_database import db
from libs.helper import dump_response
from libs.login import login_required
from models import Account
from models.im_integration import IMProvider
from services.entities.im_binding_entities import IMBindingRecord, IMBindingSessionRecord
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.app_config_service import resolve_im_app_context
from services.human_input_im.binding_service import create_binding_session, get_active_binding, revoke_active_binding
from werkzeug.exceptions import UnprocessableEntity


class CreateBindingSessionPayload(BaseModel):
    provider: IMProvider = Field(description="Provider to bind for the current account")


class IMBindingEnvelopeResponse(BaseModel):
    data: IMBindingRecord | None = None


register_schema_models(console_ns, CreateBindingSessionPayload)
register_response_schema_models(
    console_ns,
    SimpleResultResponse,
    IMBindingRecord,
    IMBindingSessionRecord,
    IMBindingEnvelopeResponse,
)


@console_ns.route("/account/im-bindings")
class AccountIMBindingApi(Resource):
    @console_ns.response(200, "Success", console_ns.models[IMBindingEnvelopeResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    def get(self, current_user: Account):
        try:
            binding = get_active_binding(session=db.session, account_id=current_user.id)
        except IMBindingValidationError as exc:
            raise UnprocessableEntity(str(exc))
        return dump_response(IMBindingEnvelopeResponse, {"data": binding}), 200

    @console_ns.response(200, "Success", console_ns.models[SimpleResultResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    def delete(self, current_user: Account):
        try:
            revoke_active_binding(session=db.session, account_id=current_user.id)
        except IMBindingValidationError as exc:
            raise UnprocessableEntity(str(exc))
        db.session.commit()
        return dump_response(SimpleResultResponse, {"result": "success"}), 200


@console_ns.route("/account/im-bindings/sessions")
class AccountIMBindingSessionApi(Resource):
    @console_ns.expect(console_ns.models[CreateBindingSessionPayload.__name__])
    @console_ns.response(201, "Created", console_ns.models[IMBindingSessionRecord.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_current_tenant_id
    def post(self, current_user: Account, tenant_id: str):
        payload = CreateBindingSessionPayload.model_validate(console_ns.payload or {})
        app_context = resolve_im_app_context(provider=payload.provider, tenant_id=tenant_id)
        try:
            binding_session = create_binding_session(
                session=db.session,
                account_id=current_user.id,
                app_context=app_context,
            )
        except IMBindingValidationError as exc:
            raise UnprocessableEntity(str(exc))
        db.session.commit()
        return dump_response(IMBindingSessionRecord, binding_session), 201
