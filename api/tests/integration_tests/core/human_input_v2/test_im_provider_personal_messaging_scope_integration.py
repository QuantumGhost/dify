"""RED repository gate for personal-user-only Provider inventory."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
MATRIX_PATH = ROOT / "openspec/changes/define-im-provider-adapter-contracts/evidence-matrix.md"


def _table_rows(markdown: str, column_count: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        if not line.startswith("| ") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == column_count and cells[0] != "provider":
            rows.append(cells)
    return rows


def test_personal_messaging_inventory_has_no_group_recipient_entries() -> None:
    markdown = MATRIX_PATH.read_text()
    exact_rows = _table_rows(markdown, 9)
    exact_keys = {(row[0], row[1], row[2], row[3]) for row in exact_rows}

    assert len(_table_rows(markdown, 7)) == 34
    assert len(exact_rows) == 77
    assert (
        "Slack",
        "basic_messaging.test_destination",
        "GET /api/users.info",
        "personal user destination",
    ) in exact_keys
    assert not any(
        provider == "Feishu/Lark"
        and operation.startswith(("basic_messaging", "dynamic_card"))
        and "chat_id" in f"{external_entry} {condition}"
        for provider, operation, external_entry, condition in exact_keys
    )
    assert (
        "DingTalk",
        "basic_messaging.test_destination",
        "POST /topapi/v2/user/get",
        "personal user destination",
    ) in exact_keys
    assert (
        "DingTalk",
        "basic_messaging.send_text",
        "POST /v1.0/robot/oToMessages/batchSend",
        "single-user robot text",
    ) in exact_keys
    assert (
        "WeCom",
        "basic_messaging.send_text",
        "POST /message/send",
        "application text message with one `touser`",
    ) in exact_keys
    assert (
        "Microsoft Teams",
        "basic_messaging.test_destination",
        "GET /v3/conversations/{conversation_id}/members/{user_id}",
        "trusted service URL and exact personal user",
    ) in exact_keys

    forbidden_fragments = (
        "/api/conversations.info",
        "/im/v1/chats/{chat_id}",
        "/v1.0/im/sceneGroups/query",
        "/v1.0/robot/groupMessages/send",
    )
    assert all(fragment not in markdown for fragment in forbidden_fragments)
