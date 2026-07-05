"""Contact-v2 Human Input delivery orchestration for the phase-1 runtime seam.

This service owns the new contact-oriented runtime notification path. It keeps
legacy email-only HITL unchanged, while contact-v2 forms route each recipient
through authoritative contact snapshot + binding + provider-neutral send logic.
The stored interaction snapshot is the server-side source of truth for mapping
provider-local callback ids back to Dify form variables and actions.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.workflow.human_input_adapter import EmailDeliveryMethod
from core.workflow.human_input_policy import resolve_variable_select_input_options
from core.workflow.nodes.human_input.entities import (
    FileInputConfig,
    FileListInputConfig,
    FormDefinition,
    ParagraphInputConfig,
    SelectInputConfig,
)
from extensions.ext_mail import mail
from libs.datetime_utils import naive_utc_now
from models.human_input import (
    DeliveryMethodType,
    HumanInputContactSnapshot,
    HumanInputDelivery,
    HumanInputForm,
    HumanInputFormRecipient,
    RecipientType,
)
from models.im_delivery import IMMessageCardStatus, IMMessageCorrelation, IMMessageDeliveryStatus
from models.workflow import WorkflowNodeExecutionModel
from services.feature_service import FeatureService
from services.human_input_delivery_support import (
    build_human_input_form_link,
    load_human_input_variable_pool,
    render_human_input_email_body,
)
from services.human_input_im.callback_service import (
    IMInteractionActionMapping,
    IMInteractionInputMapping,
    IMInteractionMappingSnapshot,
)
from services.human_input_im.provider_types import (
    IMActionDefinition,
    IMInlineInputDefinition,
    IMInlineInputOption,
    IMInteractionRenderPayload,
)
from services.human_input_im.service import HumanInputIMService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EmailDeliveryRuntime:
    delivery: HumanInputDelivery
    config: EmailDeliveryMethod
    recipients: Sequence[HumanInputFormRecipient]


class ContactV2HumanInputDeliveryService:
    """Deliver one contact-oriented form via IM or email fallback."""

    def __init__(self, im_service: HumanInputIMService | None = None) -> None:
        self._im_service = im_service or HumanInputIMService()

    def deliver_form(
        self,
        *,
        session: Session,
        form: HumanInputForm,
        node_title: str | None = None,
    ) -> None:
        runtimes = self._load_email_delivery_runtimes(session=session, form=form)
        if not runtimes:
            logger.info("No email delivery runtimes found for contact-v2 form %s", form.id)
            return

        definition = FormDefinition.model_validate_json(form.form_definition)
        variable_pool = load_human_input_variable_pool(form.workflow_run_id)
        email_available = mail.is_inited() and FeatureService.get_features(
            form.tenant_id, exclude_vector_space=True
        ).human_input_email_delivery_enabled
        active_bindings_by_account_id: dict[str, object | None] = {}
        im_contact_ids_sent: set[str] = set()

        for runtime in runtimes:
            for recipient in runtime.recipients:
                if recipient.recipient_type not in {RecipientType.EMAIL_MEMBER, RecipientType.EMAIL_EXTERNAL}:
                    continue
                snapshot = recipient.contact_snapshot
                if snapshot is None:
                    logger.warning(
                        "Contact-v2 delivery encountered recipient without contact snapshot, form_id=%s, recipient_id=%s",
                        form.id,
                        recipient.id,
                    )
                    continue

                if snapshot.type.value == "member":
                    self._deliver_member_recipient(
                        session=session,
                        form=form,
                        definition=definition,
                        runtime=runtime,
                        recipient=recipient,
                        snapshot=snapshot,
                        node_title=node_title,
                        variable_pool=variable_pool,
                        email_available=email_available,
                        active_bindings_by_account_id=active_bindings_by_account_id,
                        im_contact_ids_sent=im_contact_ids_sent,
                    )
                    continue

                delivery_status = self._deliver_email_recipient(
                    form=form,
                    runtime=runtime,
                    recipient=recipient,
                    variable_pool=variable_pool,
                    email_available=email_available,
                )
                self._append_process_data_status(
                    session=session,
                    form=form,
                    status="external_email" if delivery_status == "email_sent" else f"skipped_{delivery_status}",
                    recipient=recipient,
                    extra={"delivery_id": runtime.delivery.id},
                )

    def _deliver_member_recipient(
        self,
        *,
        session: Session,
        form: HumanInputForm,
        definition: FormDefinition,
        runtime: _EmailDeliveryRuntime,
        recipient: HumanInputFormRecipient,
        snapshot: HumanInputContactSnapshot,
        node_title: str | None,
        variable_pool,
        email_available: bool,
        active_bindings_by_account_id: dict[str, object | None],
        im_contact_ids_sent: set[str],
    ) -> None:
        account_id = snapshot.account_id
        if not account_id:
            self._append_process_data_status(
                session=session,
                form=form,
                status="skipped_missing_account",
                recipient=recipient,
                extra={"delivery_id": runtime.delivery.id},
            )
            return

        if account_id not in active_bindings_by_account_id:
            active_bindings_by_account_id[account_id] = self._im_service.inspect_active_binding(
                session=session,
                account_id=account_id,
            )
        binding = active_bindings_by_account_id[account_id]
        if binding is not None:
            if snapshot.contact_id in im_contact_ids_sent:
                return
            im_contact_ids_sent.add(snapshot.contact_id)
            self._send_im(
                session=session,
                form=form,
                definition=definition,
                recipient=recipient,
                snapshot=snapshot,
                binding=binding,
                node_title=node_title,
                variable_pool=variable_pool,
            )
            return

        if snapshot.email:
            delivery_status = self._deliver_email_recipient(
                form=form,
                runtime=runtime,
                recipient=recipient,
                variable_pool=variable_pool,
                email_available=email_available,
            )
            self._append_process_data_status(
                session=session,
                form=form,
                status="fallback_email" if delivery_status == "email_sent" else f"skipped_{delivery_status}",
                recipient=recipient,
                extra={"delivery_id": runtime.delivery.id},
            )
            return

        self._append_process_data_status(
            session=session,
            form=form,
            status="skipped_no_email",
            recipient=recipient,
            extra={"delivery_id": runtime.delivery.id},
        )

    def _send_im(
        self,
        *,
        session: Session,
        form: HumanInputForm,
        definition: FormDefinition,
        recipient: HumanInputFormRecipient,
        snapshot: HumanInputContactSnapshot,
        binding,
        node_title: str | None,
        variable_pool,
    ) -> None:
        interaction_mapping = self._build_interaction_mapping(
            definition=definition,
            variable_pool=variable_pool,
        )
        correlation = IMMessageCorrelation(
            form_id=form.id,
            recipient_id=recipient.id,
            provider=binding.provider,
            interaction_mapping_snapshot=interaction_mapping.model_dump_json(),
            provider_workspace_id=binding.provider_workspace_id,
            delivery_status=IMMessageDeliveryStatus.PENDING,
            target_card_status=IMMessageCardStatus.PENDING,
        )
        session.add(correlation)
        session.flush([correlation])

        content = self._render_im_content(
            definition=definition,
            interaction_mapping=interaction_mapping,
            form_token=recipient.access_token or "",
            variable_pool=variable_pool,
        )
        interaction_payload = self._build_interaction_render_payload(
            definition=definition,
            interaction_mapping=interaction_mapping,
            form_token=recipient.access_token or "",
            variable_pool=variable_pool,
        )
        send_result = self._im_service.send_form(
            provider=binding.provider,
            tenant_id=form.tenant_id,
            recipient_id=binding.provider_user_id,
            form_id=form.id,
            title=node_title or definition.node_title or "Human Input",
            content=content,
            metadata={
                "correlation_id": correlation.id,
                "interaction_id": interaction_mapping.interaction_id,
                "form_token": recipient.access_token or "",
                "recipient_id": recipient.id,
                "contact_id": snapshot.contact_id,
            },
            interaction_payload=interaction_payload,
        )
        if send_result.accepted:
            correlation.provider_message_id = send_result.provider_message_id
            correlation.delivery_status = IMMessageDeliveryStatus.SENT
            correlation.sent_at = naive_utc_now()
            session.flush([correlation])
            return

        correlation.delivery_status = IMMessageDeliveryStatus.FAILED
        correlation.error_reason = send_result.error or "IM provider rejected form send"
        session.flush([correlation])
        self._append_process_data_status(
            session=session,
            form=form,
            status="im_failed",
            recipient=recipient,
            extra={
                "correlation_id": correlation.id,
                "error": correlation.error_reason or "",
            },
        )

    def _deliver_email_recipient(
        self,
        *,
        form: HumanInputForm,
        runtime: _EmailDeliveryRuntime,
        recipient: HumanInputFormRecipient,
        variable_pool,
        email_available: bool,
    ) -> str:
        if not email_available:
            logger.info(
                "Email delivery unavailable for contact-v2 human input, form_id=%s, recipient_id=%s",
                form.id,
                recipient.id,
            )
            return "email_unavailable"
        email = self._recipient_email(recipient)
        if not email or not recipient.access_token:
            return "missing_email"

        form_link = build_human_input_form_link(recipient.access_token)
        body = render_human_input_email_body(runtime.config.config.body, form_link, variable_pool=variable_pool)
        subject = runtime.config.config.sanitize_subject(runtime.config.config.subject)
        mail.send(to=email, subject=subject, html=body)
        return "email_sent"

    @staticmethod
    def _load_email_delivery_runtimes(
        *,
        session: Session,
        form: HumanInputForm,
    ) -> list[_EmailDeliveryRuntime]:
        deliveries = session.scalars(
            select(HumanInputDelivery).where(
                HumanInputDelivery.form_id == form.id,
                HumanInputDelivery.delivery_method_type == DeliveryMethodType.EMAIL,
            )
        ).all()
        runtimes: list[_EmailDeliveryRuntime] = []
        for delivery in deliveries:
            config = EmailDeliveryMethod.model_validate_json(delivery.channel_payload)
            recipients = session.scalars(
                select(HumanInputFormRecipient).where(HumanInputFormRecipient.delivery_id == delivery.id)
            ).all()
            runtimes.append(_EmailDeliveryRuntime(delivery=delivery, config=config, recipients=recipients))
        return runtimes

    @staticmethod
    def _build_interaction_mapping(
        *,
        definition: FormDefinition,
        variable_pool,
    ) -> IMInteractionMappingSnapshot:
        resolved_inputs = resolve_variable_select_input_options(definition.inputs, variable_pool=variable_pool)
        interaction_mapping = IMInteractionMappingSnapshot(interaction_id=f"imhi_{uuid4().hex}")
        for form_input in resolved_inputs:
            if isinstance(form_input, ParagraphInputConfig | SelectInputConfig):
                component_id = f"provider_component_{form_input.output_variable_name}"
                interaction_mapping.inputs[component_id] = IMInteractionInputMapping(
                    output_variable_name=form_input.output_variable_name,
                    type=form_input.type.value,
                )
        for action in definition.user_actions:
            provider_action_id = f"provider_action_{action.id}"
            interaction_mapping.actions[provider_action_id] = IMInteractionActionMapping(action_id=action.id)
        return interaction_mapping

    @staticmethod
    def _build_interaction_render_payload(
        *,
        definition: FormDefinition,
        interaction_mapping: IMInteractionMappingSnapshot,
        form_token: str,
        variable_pool,
    ) -> IMInteractionRenderPayload:
        form_link = build_human_input_form_link(form_token)
        resolved_inputs = resolve_variable_select_input_options(definition.inputs, variable_pool=variable_pool)
        supported_inputs: list[IMInlineInputDefinition] = []
        unsupported_input_names: list[str] = []

        for form_input in resolved_inputs:
            if isinstance(form_input, ParagraphInputConfig):
                supported_inputs.append(
                    IMInlineInputDefinition(
                        component_id=f"provider_component_{form_input.output_variable_name}",
                        label=form_input.output_variable_name,
                        type=form_input.type.value,
                    )
                )
                continue

            if isinstance(form_input, SelectInputConfig):
                supported_inputs.append(
                    IMInlineInputDefinition(
                        component_id=f"provider_component_{form_input.output_variable_name}",
                        label=form_input.output_variable_name,
                        type=form_input.type.value,
                        options=[
                            IMInlineInputOption(label=option_value, value=option_value)
                            for option_value in form_input.option_source.value
                        ],
                    )
                )
                continue

            if isinstance(form_input, FileInputConfig | FileListInputConfig):
                unsupported_input_names.append(form_input.output_variable_name)

        actions = [
            IMActionDefinition(provider_action_id=f"provider_action_{action.id}", label=action.title)
            for action in definition.user_actions
        ]

        return IMInteractionRenderPayload(
            interaction_id=interaction_mapping.interaction_id,
            rendered_content=definition.rendered_content,
            form_link=form_link,
            inputs=supported_inputs,
            unsupported_input_names=unsupported_input_names,
            actions=actions,
        )

    def _render_im_content(
        self,
        *,
        definition: FormDefinition,
        interaction_mapping: IMInteractionMappingSnapshot,
        form_token: str,
        variable_pool,
    ) -> str:
        form_link = build_human_input_form_link(form_token)
        resolved_inputs = resolve_variable_select_input_options(definition.inputs, variable_pool=variable_pool)
        sections = [definition.rendered_content]
        inline_inputs: list[str] = []
        unsupported_inputs: list[str] = []
        for form_input in resolved_inputs:
            if isinstance(form_input, ParagraphInputConfig):
                inline_inputs.append(f"- {form_input.output_variable_name}: paragraph")
            elif isinstance(form_input, SelectInputConfig):
                options = ", ".join(form_input.option_source.value)
                inline_inputs.append(f"- {form_input.output_variable_name}: select [{options}]")
            elif isinstance(form_input, FileInputConfig | FileListInputConfig):
                unsupported_inputs.append(form_input.output_variable_name)

        if inline_inputs:
            sections.append("Inline inputs:\n" + "\n".join(inline_inputs))
        if unsupported_inputs:
            sections.append(
                "File inputs require the web form fallback:\n"
                f"- {', '.join(unsupported_inputs)}\n"
                f"- {form_link}"
            )

        action_lines = [f"- {action.title} (`provider_action_{action.id}`)" for action in definition.user_actions]
        if action_lines:
            sections.append("Actions:\n" + "\n".join(action_lines))

        sections.append(f"Web form: {form_link}")
        return "\n\n".join(section for section in sections if section)

    @staticmethod
    def _recipient_email(recipient: HumanInputFormRecipient) -> str | None:
        try:
            payload = json.loads(recipient.recipient_payload)
        except Exception:
            logger.exception("Failed to parse human input recipient payload, recipient_id=%s", recipient.id)
            return None
        email = payload.get("email")
        return email if isinstance(email, str) and email else None

    @staticmethod
    def _append_process_data_status(
        *,
        session: Session,
        form: HumanInputForm,
        status: str,
        recipient: HumanInputFormRecipient,
        extra: Mapping[str, str],
    ) -> None:
        if not form.workflow_run_id:
            return
        execution = session.scalars(
            select(WorkflowNodeExecutionModel)
            .where(
                WorkflowNodeExecutionModel.tenant_id == form.tenant_id,
                WorkflowNodeExecutionModel.app_id == form.app_id,
                WorkflowNodeExecutionModel.workflow_run_id == form.workflow_run_id,
                WorkflowNodeExecutionModel.node_id == form.node_id,
            )
            .order_by(WorkflowNodeExecutionModel.created_at.desc())
        ).first()
        if execution is None:
            return

        process_data = execution.process_data_dict or {}
        delivery_data = dict(process_data.get("human_input_delivery") or {})
        recipient_statuses = list(delivery_data.get("recipient_statuses") or [])
        recipient_statuses.append(
            {
                "recipient_id": recipient.id,
                "status": status,
                **dict(extra),
            }
        )
        delivery_data["recipient_statuses"] = recipient_statuses
        process_data["human_input_delivery"] = delivery_data
        execution.process_data = json.dumps(process_data)
        session.flush([execution])
