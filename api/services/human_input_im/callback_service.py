from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.repositories.account_im_binding_repository import get_account_im_binding_by_id
from extensions.ext_database import db
from models.human_input import HumanInputFormRecipient, IMMemberRecipientPayload
from services.human_input_service import HumanInputService


def submit_im_card_action(
    *,
    session: Session,
    form_token: str,
    action_id: str,
    form_data: dict,
    operator_open_id: str | None,
    operator_user_id: str | None,
) -> None:
    service = HumanInputService(db.engine)
    form = service.get_form_by_token(form_token)
    if form is None or form.recipient_type is None:
        raise ValueError(f"Unknown IM form token: {form_token}")

    recipient = session.scalars(
        select(HumanInputFormRecipient).where(HumanInputFormRecipient.access_token == form_token).limit(1)
    ).first()
    if recipient is None:
        raise ValueError(f"Missing IM recipient for form token: {form_token}")

    payload = IMMemberRecipientPayload.model_validate_json(recipient.recipient_payload)
    binding = get_account_im_binding_by_id(session=session, binding_id=payload.binding_id)
    if binding is None:
        raise ValueError(f"Missing IM binding for recipient token: {form_token}")
    _ensure_operator_matches_binding(
        open_id=binding.open_id,
        user_id=binding.user_id,
        operator_open_id=operator_open_id,
        operator_user_id=operator_user_id,
    )

    service.submit_form_by_token(
        recipient_type=form.recipient_type,
        form_token=form_token,
        selected_action_id=action_id,
        form_data=form_data,
        submission_user_id=payload.account_id,
    )


def _ensure_operator_matches_binding(
    *,
    open_id: str | None,
    user_id: str | None,
    operator_open_id: str | None,
    operator_user_id: str | None,
) -> None:
    if open_id and open_id == operator_open_id:
        return
    if user_id and user_id == operator_user_id:
        return
    raise PermissionError("Card action operator does not match bound IM recipient")
