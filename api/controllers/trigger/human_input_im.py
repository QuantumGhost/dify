import logging

from flask import jsonify, request
from pydantic import BaseModel, Field, ValidationError
from werkzeug.exceptions import BadRequest

from controllers.trigger import bp
from extensions.ext_database import db
from models.im_integration import IMProvider
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.callback_service import HumanInputIMCallbackService, IMBindingCompletionEvent

logger = logging.getLogger(__name__)


class IMBindingCompletionPayload(BaseModel):
    event_id: str = Field(min_length=1)
    binding_session_token: str = Field(min_length=1)
    provider_workspace_id: str = Field(min_length=1)
    provider_user_id: str = Field(min_length=1)
    provider_union_id: str | None = None
    provider_user_display_name: str | None = None
    provider_user_avatar_url: str | None = None


@bp.route("/human-input-im/<string:provider>/binding-completion", methods=["POST"])
def handle_im_binding_completion(provider: str):
    """Future external callback skeleton.

    Phase-1 demo uses Feishu long-connection mode and does not depend on this
    HTTP route. This route exists only as a transport-neutral skeleton for
    future webhook-capable integrations.
    """

    try:
        resolved_provider = IMProvider(provider)
    except ValueError as exc:
        raise BadRequest(str(exc))

    payload = IMBindingCompletionPayload.model_validate_json(request.get_data())
    event = IMBindingCompletionEvent(
        provider=resolved_provider,
        event_id=payload.event_id,
        binding_session_token=payload.binding_session_token,
        provider_workspace_id=payload.provider_workspace_id,
        provider_user_id=payload.provider_user_id,
        provider_union_id=payload.provider_union_id,
        provider_user_display_name=payload.provider_user_display_name,
        provider_user_avatar_url=payload.provider_user_avatar_url,
    )

    service = HumanInputIMCallbackService()
    try:
        binding = service.complete_binding(session=db.session, event=event)
    except IMBindingValidationError as exc:
        raise BadRequest(str(exc))

    db.session.commit()
    return jsonify({"result": "accepted", "binding_id": binding.id}), 202
