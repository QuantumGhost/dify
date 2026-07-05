"""Shared Human Input observability helpers.

This module owns generic identifier/log-context shaping that is reused by
Contact bootstrap, Human Input resume, and IM-specific slices.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from models.human_input import HumanInputContactSnapshot, HumanInputForm, HumanInputFormRecipient
from models.im_delivery import IMMessageCorrelation
from models.im_integration import IMProvider
from services.entities.im_binding_entities import IMBindingRecord


def _normalize_log_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return value


def _set_if_present(context: dict[str, object], *, key: str, value: object | None) -> None:
    if value is None:
        return
    context[key] = _normalize_log_value(value)


def _get_optional_attr(value: object, attr_name: str) -> object | None:
    return getattr(value, attr_name, None)


def build_human_input_log_context(
    *,
    tenant_id: str | None = None,
    app_id: str | None = None,
    workflow_run_id: str | None = None,
    conversation_id: str | None = None,
    form_id: str | None = None,
    node_id: str | None = None,
    recipient_id: str | None = None,
    recipient_type: object | None = None,
    delivery_id: str | None = None,
    provider: IMProvider | None = None,
    provider_workspace_id: str | None = None,
    provider_user_id: str | None = None,
    provider_message_id: str | None = None,
    provider_event_id: str | None = None,
    interaction_id: str | None = None,
    form: HumanInputForm | None = None,
    recipient: HumanInputFormRecipient | None = None,
    contact_snapshot: HumanInputContactSnapshot | None = None,
    binding: IMBindingRecord | None = None,
    correlation: IMMessageCorrelation | None = None,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    context: dict[str, object] = {}

    if form is not None:
        _set_if_present(context, key="tenant_id", value=_get_optional_attr(form, "tenant_id"))
        _set_if_present(context, key="app_id", value=_get_optional_attr(form, "app_id"))
        _set_if_present(context, key="workflow_run_id", value=_get_optional_attr(form, "workflow_run_id"))
        _set_if_present(context, key="conversation_id", value=_get_optional_attr(form, "conversation_id"))
        _set_if_present(context, key="form_id", value=_get_optional_attr(form, "id"))
        _set_if_present(context, key="node_id", value=_get_optional_attr(form, "node_id"))

    if recipient is not None:
        _set_if_present(context, key="recipient_id", value=_get_optional_attr(recipient, "id"))
        _set_if_present(context, key="recipient_type", value=_get_optional_attr(recipient, "recipient_type"))
        _set_if_present(context, key="delivery_id", value=_get_optional_attr(recipient, "delivery_id"))

    if contact_snapshot is not None:
        _set_if_present(context, key="contact_id", value=_get_optional_attr(contact_snapshot, "contact_id"))
        _set_if_present(context, key="contact_tenant_id", value=_get_optional_attr(contact_snapshot, "tenant_id"))
        _set_if_present(context, key="contact_type", value=_get_optional_attr(contact_snapshot, "type"))
        _set_if_present(context, key="contact_source", value=_get_optional_attr(contact_snapshot, "source"))
        _set_if_present(context, key="contact_status", value=_get_optional_attr(contact_snapshot, "status"))
        _set_if_present(context, key="contact_account_id", value=_get_optional_attr(contact_snapshot, "account_id"))

    if binding is not None:
        _set_if_present(context, key="binding_account_id", value=_get_optional_attr(binding, "account_id"))
        _set_if_present(context, key="provider", value=_get_optional_attr(binding, "provider"))
        _set_if_present(context, key="provider_workspace_id", value=_get_optional_attr(binding, "provider_workspace_id"))
        _set_if_present(context, key="provider_user_id", value=_get_optional_attr(binding, "provider_user_id"))
        _set_if_present(context, key="binding_scope_type", value=_get_optional_attr(binding, "scope_type"))
        _set_if_present(context, key="binding_scope_id", value=_get_optional_attr(binding, "scope_id"))
        _set_if_present(context, key="binding_status", value=_get_optional_attr(binding, "status"))

    if correlation is not None:
        _set_if_present(context, key="correlation_id", value=_get_optional_attr(correlation, "id"))
        _set_if_present(context, key="provider", value=_get_optional_attr(correlation, "provider"))
        _set_if_present(
            context,
            key="provider_workspace_id",
            value=_get_optional_attr(correlation, "provider_workspace_id"),
        )
        _set_if_present(context, key="provider_message_id", value=_get_optional_attr(correlation, "provider_message_id"))
        _set_if_present(context, key="provider_event_id", value=_get_optional_attr(correlation, "last_provider_event_id"))
        _set_if_present(context, key="delivery_status", value=_get_optional_attr(correlation, "delivery_status"))
        _set_if_present(context, key="target_card_status", value=_get_optional_attr(correlation, "target_card_status"))

    _set_if_present(context, key="tenant_id", value=tenant_id)
    _set_if_present(context, key="app_id", value=app_id)
    _set_if_present(context, key="workflow_run_id", value=workflow_run_id)
    _set_if_present(context, key="conversation_id", value=conversation_id)
    _set_if_present(context, key="form_id", value=form_id)
    _set_if_present(context, key="node_id", value=node_id)
    _set_if_present(context, key="recipient_id", value=recipient_id)
    _set_if_present(context, key="recipient_type", value=recipient_type)
    _set_if_present(context, key="delivery_id", value=delivery_id)
    _set_if_present(context, key="provider", value=provider)
    _set_if_present(context, key="provider_workspace_id", value=provider_workspace_id)
    _set_if_present(context, key="provider_user_id", value=provider_user_id)
    _set_if_present(context, key="provider_message_id", value=provider_message_id)
    _set_if_present(context, key="provider_event_id", value=provider_event_id)
    _set_if_present(context, key="interaction_id", value=interaction_id)

    if extra:
        for key, value in extra.items():
            _set_if_present(context, key=key, value=value)

    return context


def stringify_log_context(context: Mapping[str, object]) -> dict[str, str]:
    stringified: dict[str, str] = {}
    for key, value in context.items():
        normalized = _normalize_log_value(value)
        if normalized is None:
            continue
        stringified[key] = normalized if isinstance(normalized, str) else str(normalized)
    return stringified
