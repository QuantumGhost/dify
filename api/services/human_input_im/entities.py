from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

HumanInputIMFieldType = Literal["paragraph", "select", "file", "file_list", "text"]
FeishuCardMode = Literal["inline_card", "summary_card_with_link"]


@dataclass(frozen=True)
class HumanInputIMSelectOption:
    label: str
    value: str


@dataclass(frozen=True)
class HumanInputIMField:
    name: str
    label: str
    field_type: HumanInputIMFieldType
    required: bool
    default_value: str | None = None
    options: tuple[HumanInputIMSelectOption, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HumanInputIMAction:
    id: str
    title: str


@dataclass(frozen=True)
class HumanInputIMRecipient:
    account_id: str
    provider: str
    open_id: str | None
    user_id: str | None
    form_token: str


@dataclass(frozen=True)
class HumanInputIMNotificationJob:
    form_id: str
    node_id: str
    node_title: str
    rendered_content: str
    fields: tuple[HumanInputIMField, ...]
    actions: tuple[HumanInputIMAction, ...]
    recipient: HumanInputIMRecipient


@dataclass(frozen=True)
class FeishuCardBuildResult:
    mode: FeishuCardMode
    payload: dict

