"""Contact-v2 Human Input delivery task.

This task is the sole async routing owner for paused Human Input notifications.
It detects whether a paused form uses contact snapshots, then either runs the
contact-v2 delivery service or delegates back to the legacy email-only task.
"""

from __future__ import annotations

import logging

import click
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.human_input import HumanInputForm, HumanInputFormRecipient, RecipientType
from services.human_input_delivery_support import open_human_input_delivery_session
from services.human_input_im.delivery_service import ContactV2HumanInputDeliveryService
from tasks.mail_human_input_delivery_task import dispatch_human_input_email_task

logger = logging.getLogger(__name__)


def form_uses_contact_v2_delivery(form_id: str, session_factory=None) -> bool:
    with open_human_input_delivery_session(session_factory) as session:
        return _form_uses_contact_v2_delivery_in_session(session=session, form_id=form_id)


def _form_uses_contact_v2_delivery_in_session(*, session: Session, form_id: str) -> bool:
    recipients = session.scalars(
        select(HumanInputFormRecipient).where(HumanInputFormRecipient.form_id == form_id)
    ).all()
    return any(
        recipient.recipient_type in {RecipientType.EMAIL_MEMBER, RecipientType.EMAIL_EXTERNAL}
        and recipient.contact_snapshot is not None
        for recipient in recipients
    )


@shared_task(queue="mail")
def dispatch_human_input_im_task(form_id: str, node_title: str | None = None, session_factory=None):
    logger.info(click.style(f"Start contact-v2 human input delivery for form {form_id}", fg="green"))
    try:
        with open_human_input_delivery_session(session_factory) as session:
            form = session.get(HumanInputForm, form_id)
            if form is None:
                logger.warning("Human input form not found, form_id=%s", form_id)
                return
            if not _form_uses_contact_v2_delivery_in_session(session=session, form_id=form_id):
                dispatch_human_input_email_task(form_id=form_id, node_title=node_title, session_factory=session_factory)
                return

            ContactV2HumanInputDeliveryService().deliver_form(session=session, form=form, node_title=node_title)
            if hasattr(session, "commit"):
                session.commit()
    except Exception:
        logger.exception("Contact-v2 human input delivery failed, form_id=%s", form_id)
