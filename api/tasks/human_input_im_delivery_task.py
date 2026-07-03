from __future__ import annotations

import json
import logging

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.repositories.account_im_binding_repository import get_account_im_binding_by_id
from extensions.ext_database import db
from graphon.nodes.human_input.entities import (
    FileInputConfig,
    FileListInputConfig,
    FormDefinition,
    ParagraphInputConfig,
    SelectInputConfig,
)
from models.human_input import HumanInputDelivery, HumanInputForm, HumanInputFormRecipient, IMMemberRecipientPayload
from services.human_input_im.config_store import EnvBackedProviderConfigStore, ProviderConfigStore
from services.human_input_im.dispatcher import HumanInputIMDispatcher
from services.human_input_im.entities import (
    HumanInputIMAction,
    HumanInputIMField,
    HumanInputIMNotificationJob,
    HumanInputIMRecipient,
    HumanInputIMSelectOption,
)

logger = logging.getLogger(__name__)


def _open_session(session_factory: sessionmaker | Session | None):
    if session_factory is None:
        return Session(db.engine)
    if isinstance(session_factory, Session):
        return session_factory
    return session_factory()


def _build_provider_config_store() -> ProviderConfigStore:
    return EnvBackedProviderConfigStore()


def _build_provider_dispatcher() -> HumanInputIMDispatcher:
    return HumanInputIMDispatcher()


def _load_im_jobs(session: Session, form: HumanInputForm) -> list[HumanInputIMNotificationJob]:
    deliveries = session.scalars(
        select(HumanInputDelivery).where(
            HumanInputDelivery.form_id == form.id,
        )
    ).all()
    jobs: list[HumanInputIMNotificationJob] = []
    form_definition_payload = json.loads(form.form_definition)
    if "expiration_time" not in form_definition_payload:
        form_definition_payload["expiration_time"] = form.expiration_time
    form_definition = FormDefinition.model_validate(form_definition_payload)
    for delivery in deliveries:
        if str(delivery.delivery_method_type) != "im":
            continue
        recipients = session.scalars(
            select(HumanInputFormRecipient).where(
                HumanInputFormRecipient.delivery_id == delivery.id,
            )
        ).all()
        for recipient in recipients:
            if str(recipient.recipient_type) != "im_member" or not recipient.access_token:
                continue
            payload = IMMemberRecipientPayload.model_validate_json(recipient.recipient_payload)
            binding = get_account_im_binding_by_id(session=session, binding_id=payload.binding_id)
            if binding is None or (not binding.open_id and not binding.user_id):
                continue
            jobs.append(
                HumanInputIMNotificationJob(
                    form_id=form.id,
                    node_id=form.node_id,
                    node_title=form_definition.node_title or form.node_id,
                    rendered_content=form_definition.rendered_content,
                    fields=tuple(_build_fields(form_definition)),
                    actions=tuple(
                        HumanInputIMAction(id=action.id, title=action.title)
                        for action in form_definition.user_actions
                    ),
                    recipient=HumanInputIMRecipient(
                        account_id=payload.account_id,
                        provider=binding.provider,
                        open_id=binding.open_id,
                        user_id=binding.user_id,
                        form_token=recipient.access_token,
                    ),
                )
            )
    return jobs


def _build_fields(form_definition: FormDefinition) -> list[HumanInputIMField]:
    fields: list[HumanInputIMField] = []
    for input_config in form_definition.inputs:
        default_value = form_definition.default_values.get(input_config.output_variable_name)
        if isinstance(input_config, ParagraphInputConfig):
            fields.append(
                HumanInputIMField(
                    name=input_config.output_variable_name,
                    label=input_config.output_variable_name,
                    field_type="paragraph",
                    required=False,
                    default_value=str(default_value) if isinstance(default_value, str) else None,
                )
            )
            continue
        if isinstance(input_config, SelectInputConfig):
            fields.append(
                HumanInputIMField(
                    name=input_config.output_variable_name,
                    label=input_config.output_variable_name,
                    field_type="select",
                    required=False,
                    default_value=str(default_value) if isinstance(default_value, str) else None,
                    options=tuple(
                        HumanInputIMSelectOption(label=option, value=option)
                        for option in input_config.option_source.value
                    ),
                )
            )
            continue
        if isinstance(input_config, FileInputConfig):
            fields.append(
                HumanInputIMField(
                    name=input_config.output_variable_name,
                    label=input_config.output_variable_name,
                    field_type="file",
                    required=False,
                )
            )
            continue
        if isinstance(input_config, FileListInputConfig):
            fields.append(
                HumanInputIMField(
                    name=input_config.output_variable_name,
                    label=input_config.output_variable_name,
                    field_type="file_list",
                    required=False,
                )
            )
            continue
        fields.append(
            HumanInputIMField(
                name=input_config.output_variable_name,
                label=input_config.output_variable_name,
                field_type="text",
                required=False,
                default_value=str(default_value) if isinstance(default_value, str) else None,
            )
        )
    return fields


@shared_task(queue="mail")
def dispatch_human_input_im_task(form_id: str, node_title: str | None = None, session_factory=None):
    del node_title

    try:
        with _open_session(session_factory) as session:
            form = session.get(HumanInputForm, form_id)
            if form is None:
                logger.warning("Human input form not found for IM delivery, form_id=%s", form_id)
                return
            jobs = _load_im_jobs(session, form)

        if not jobs:
            return

        config_store = _build_provider_config_store()
        config = config_store.get_active_config(form.tenant_id)
        if config is None:
            logger.info("Human input IM delivery skipped without active config, form_id=%s", form_id)
            return

        dispatcher = _build_provider_dispatcher()
        for job in jobs:
            dispatcher.send_form_notification(config=config, job=job)
    except Exception:
        logger.exception("Human input IM delivery failed, form_id=%s", form_id)


__all__ = [
    "dispatch_human_input_im_task",
]
