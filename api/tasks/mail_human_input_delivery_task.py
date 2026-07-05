import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import click
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.workflow.human_input_adapter import EmailDeliveryConfig, EmailDeliveryMethod
from extensions.ext_mail import mail
from models.human_input import (
    DeliveryMethodType,
    HumanInputDelivery,
    HumanInputForm,
    HumanInputFormRecipient,
    RecipientType,
)
from services.feature_service import FeatureService
from services.human_input_delivery_support import (
    build_human_input_form_link,
    load_human_input_variable_pool,
    open_human_input_delivery_session,
    render_human_input_email_body,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EmailRecipient:
    email: str
    token: str


@dataclass(frozen=True)
class _EmailDeliveryJob:
    form_id: str
    subject: str
    body: str
    form_content: str
    recipients: list[_EmailRecipient]

def _parse_recipient_payload(payload: str) -> tuple[str | None, RecipientType | None]:
    try:
        payload_dict: dict[str, Any] = json.loads(payload)
    except Exception:
        logger.exception("Failed to parse recipient payload")
        return None, None

    return payload_dict.get("email"), payload_dict.get("TYPE")


def _load_email_jobs(session: Session, form: HumanInputForm) -> list[_EmailDeliveryJob]:
    deliveries = session.scalars(
        select(HumanInputDelivery).where(
            HumanInputDelivery.form_id == form.id,
            HumanInputDelivery.delivery_method_type == DeliveryMethodType.EMAIL,
        )
    ).all()
    jobs: list[_EmailDeliveryJob] = []
    for delivery in deliveries:
        delivery_config = EmailDeliveryMethod.model_validate_json(delivery.channel_payload)

        recipients = session.scalars(
            select(HumanInputFormRecipient).where(HumanInputFormRecipient.delivery_id == delivery.id)
        ).all()

        recipient_entities: list[_EmailRecipient] = []
        for recipient in recipients:
            email, recipient_type = _parse_recipient_payload(recipient.recipient_payload)
            if recipient_type not in {RecipientType.EMAIL_MEMBER, RecipientType.EMAIL_EXTERNAL}:
                continue
            if not email:
                continue
            token = recipient.access_token
            if not token:
                continue
            recipient_entities.append(_EmailRecipient(email=email, token=token))

        if not recipient_entities:
            continue

        jobs.append(
            _EmailDeliveryJob(
                form_id=form.id,
                subject=delivery_config.config.subject,
                body=delivery_config.config.body,
                form_content=form.rendered_content,
                recipients=recipient_entities,
            )
        )
    return jobs

@shared_task(queue="mail")
def dispatch_human_input_email_task(form_id: str, node_title: str | None = None, session_factory=None):
    if not mail.is_inited():
        return

    logger.info(click.style(f"Start human input email delivery for form {form_id}", fg="green"))
    start_at = time.perf_counter()

    try:
        with open_human_input_delivery_session(session_factory) as session:
            form = session.get(HumanInputForm, form_id)
            if form is None:
                logger.warning("Human input form not found, form_id=%s", form_id)
                return
            features = FeatureService.get_features(form.tenant_id, exclude_vector_space=True)
            if not features.human_input_email_delivery_enabled:
                logger.info(
                    "Human input email delivery is not available for tenant=%s, form_id=%s",
                    form.tenant_id,
                    form_id,
                )
                return
            jobs = _load_email_jobs(session, form)

        variable_pool = load_human_input_variable_pool(form.workflow_run_id)

        for job in jobs:
            for recipient in job.recipients:
                form_link = build_human_input_form_link(recipient.token)
                body = render_human_input_email_body(job.body, form_link, variable_pool=variable_pool)
                subject = EmailDeliveryConfig.sanitize_subject(job.subject)

                mail.send(
                    to=recipient.email,
                    subject=subject,
                    html=body,
                )

        end_at = time.perf_counter()
        logger.info(
            click.style(
                f"Human input email delivery succeeded for form {form_id}: latency: {end_at - start_at}", fg="green"
            )
        )
    except Exception:
        logger.exception("Send human input email failed, form_id=%s", form_id)
