"""Acceptance checks for exhaustive IM provider evidence accounting."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_CHANGE_ROOT = _REPOSITORY_ROOT / "openspec/changes/define-im-provider-adapter-contracts"
_EVIDENCE_MATRIX = _CHANGE_ROOT / "evidence-matrix.md"
_TASKS = _CHANGE_ROOT / "tasks.md"
_SLACK_LIVE_RECEIPT = _CHANGE_ROOT / "evidence/slack-live-e2e-2026-08-02.md"
_SLACK_SOCKET_FIXTURE = _CHANGE_ROOT / "evidence/fixtures/slack-live-socket-block-actions-2026-08-03.json"
_FEISHU_DIRECTORY_PARTIAL_RECEIPT = _CHANGE_ROOT / "evidence/feishu-live-directory-partial-2026-08-03.md"
_FEISHU_DIRECTORY_PARTIAL_FIXTURE = _CHANGE_ROOT / "evidence/fixtures/feishu-live-directory-partial-2026-08-03.json"
_FEISHU_PHASE_A_RECEIPT = _CHANGE_ROOT / "evidence/feishu-live-api-phase-a-2026-08-03.md"
_FEISHU_PHASE_A_FIXTURE = _CHANGE_ROOT / "evidence/fixtures/feishu-live-api-phase-a-2026-08-03.json"
_WECOM_DIRECTORY_PARTIAL_RECEIPT = _CHANGE_ROOT / "evidence/wecom-live-directory-partial-2026-08-03.md"
_WECOM_DIRECTORY_PARTIAL_FIXTURE = _CHANGE_ROOT / "evidence/fixtures/wecom-live-directory-partial-2026-08-03.json"
_WECOM_LIVE_RECEIPT = _CHANGE_ROOT / "evidence/wecom-live-read-only-2026-08-02.md"
_WECOM_LIVE_FIXTURE = _CHANGE_ROOT / "evidence/fixtures/wecom-live-api-2026-08-02.json"
_DINGTALK_DIRECTORY_PARTIAL_RECEIPT = _CHANGE_ROOT / "evidence/dingtalk-live-directory-partial-2026-08-03.md"
_DINGTALK_DIRECTORY_PARTIAL_FIXTURE = _CHANGE_ROOT / "evidence/fixtures/dingtalk-live-directory-partial-2026-08-03.json"
_MS_TEAMS_DIRECTORY_PARTIAL_RECEIPT = _CHANGE_ROOT / "evidence/microsoft-teams-live-directory-partial-2026-08-03.md"
_MS_TEAMS_DIRECTORY_PARTIAL_FIXTURE = (
    _CHANGE_ROOT / "evidence/fixtures/microsoft-teams-live-directory-partial-2026-08-03.json"
)
_LOCAL_VERIFICATION_RECEIPT = _CHANGE_ROOT / "evidence/local-verification-coverage-2026-08-02.md"

_ALL_PROVIDERS = {
    "Slack",
    "Feishu/Lark",
    "DingTalk",
    "WeCom",
    "Microsoft Teams",
}
_CARD_PROVIDERS = {"Slack", "Feishu/Lark", "Microsoft Teams"}
_STREAM_PROVIDERS = {"Slack", "Feishu/Lark"}
_ALL_PROVIDER_OPERATIONS = {
    "credential.test_credentials",
    "directory.read_snapshot",
    "basic_messaging.test_destination",
    "basic_messaging.send_text",
}
_CARD_OPERATIONS = {
    "dynamic_card.send_card",
    "dynamic_card.update_card",
}
_EXTERNAL_CHALLENGE_ENTRIES = {
    ("Feishu/Lark", "webhook.challenge"),
}
_TEST_ONLY_BEHAVIORS = {
    "dynamic_card.assess",
    "stream.control",
    "stream.reconnect",
    "stream.stop",
    "webhook.authentication_failure",
    "webhook.tamper_failure",
    "webhook.replay_failure",
    "webhook.timestamp_failure",
    "webhook.wrong_key_failure",
    "sink.retry",
    "sink.exception",
    "stream.ack_failure",
    "event_id.missing",
    "event_id.synthetic_rejection",
}
_EVIDENCE_COLUMNS = {
    "unit_test",
    "integration_test",
    "real_execution",
    "sanitized_fixture",
    "independent_crypto",
}
_EXACT_INVENTORY_COLUMNS = {
    "provider",
    "operation",
    "external_entry",
    "condition",
    *_EVIDENCE_COLUMNS,
}
_CRYPTO_APPLICABLE_EXACT_ENTRIES = {
    ("Slack", "webhook.interactive.block_actions", "receive interactive request with block_actions payload"),
    ("Feishu/Lark", "webhook.challenge", "receive url_verification challenge"),
    (
        "Feishu/Lark",
        "webhook.card.action.trigger",
        "receive card.action.trigger webhook event",
    ),
    (
        "Microsoft Teams",
        "webhook.message.action_submit",
        "receive message Activity with Action.Submit value",
    ),
}


def _expected_cells() -> set[tuple[str, str]]:
    cells = {(provider, operation) for provider in _ALL_PROVIDERS for operation in _ALL_PROVIDER_OPERATIONS}
    cells.update((provider, operation) for provider in _CARD_PROVIDERS for operation in _CARD_OPERATIONS)
    cells.update((provider, "stream.connect") for provider in _STREAM_PROVIDERS)
    cells.update(
        {
            ("Slack", "webhook.interactive.block_actions"),
            ("Slack", "stream.interactive.block_actions"),
            ("Feishu/Lark", "webhook.card.action.trigger"),
            ("Feishu/Lark", "stream.card.action.trigger"),
            ("Microsoft Teams", "webhook.message.action_submit"),
        }
    )
    cells.update(_EXTERNAL_CHALLENGE_ENTRIES)
    return cells


_EXPECTED_EXACT_INVENTORY_ENTRIES = {
    "Slack": {
        ("credential.test_credentials", "POST /api/auth.test", "always"),
        ("directory.read_snapshot", "POST /api/auth.test", "before each directory snapshot"),
        ("directory.read_snapshot", "GET /api/users.list [paginated]", "one or more pages"),
        ("basic_messaging.test_destination", "GET /api/users.info", "personal user destination"),
        (
            "basic_messaging.send_text",
            "POST /api/chat.postMessage [text]",
            "direct personal text with user ID as channel",
        ),
        ("dynamic_card.send_card", "POST /api/chat.postMessage [Block Kit]", "new card"),
        ("dynamic_card.update_card", "POST /api/chat.update [Block Kit]", "exact message reference"),
        (
            "webhook.interactive.block_actions",
            "receive interactive request with block_actions payload",
            "signed form payload",
        ),
        (
            "stream.interactive.block_actions",
            "receive interactive Socket Mode envelope with block_actions payload",
            "interactive envelope only",
        ),
        ("stream.connect", "POST apps.connections.open [endpoint discovery]", "before WebSocket connect"),
    },
    "Feishu/Lark": {
        (
            "credential.test_credentials",
            "POST /auth/v3/tenant_access_token/internal",
            "tenant token cache miss or expiry on configured Provider host",
        ),
        ("credential.test_credentials", "GET /tenant/v2/tenant/query", "after tenant token acquisition"),
        (
            "credential.test_credentials",
            "GET /contact/v3/scopes [paginated visibility roots]",
            "after tenant identification",
        ),
        (
            "directory.read_snapshot",
            "POST /auth/v3/tenant_access_token/internal",
            "tenant token cache miss or expiry",
        ),
        ("directory.read_snapshot", "GET /tenant/v2/tenant/query", "before scoped traversal"),
        (
            "directory.read_snapshot",
            "GET /contact/v3/scopes [paginated visibility roots]",
            "before scoped traversal",
        ),
        (
            "directory.read_snapshot",
            "GET /contact/v3/departments/{department_id}/children [paginated]",
            "each explicit department visibility root",
        ),
        (
            "directory.read_snapshot",
            "GET /contact/v3/users/find_by_department [paginated]",
            "each visible department",
        ),
        (
            "directory.read_snapshot",
            "GET /contact/v3/users/{id} [explicit-user branch]",
            "each explicit user visibility root",
        ),
        (
            "basic_messaging.test_destination",
            "POST /auth/v3/tenant_access_token/internal",
            "tenant token cache miss or expiry",
        ),
        (
            "basic_messaging.test_destination",
            "POST /contact/v3/users/batch_get_id [email]",
            "receive_id_type=email",
        ),
        (
            "basic_messaging.test_destination",
            "GET /contact/v3/users/{id} [open_id]",
            "receive_id_type=open_id",
        ),
        (
            "basic_messaging.test_destination",
            "GET /contact/v3/users/{id} [user_id]",
            "receive_id_type=user_id",
        ),
        (
            "basic_messaging.test_destination",
            "GET /contact/v3/users/{id} [union_id]",
            "receive_id_type=union_id",
        ),
        (
            "basic_messaging.send_text",
            "POST /auth/v3/tenant_access_token/internal",
            "tenant token cache miss or expiry",
        ),
        ("basic_messaging.send_text", "POST /im/v1/messages [text]", "new text message"),
        (
            "dynamic_card.send_card",
            "POST /auth/v3/tenant_access_token/internal",
            "tenant token cache miss or expiry",
        ),
        ("dynamic_card.send_card", "POST /im/v1/messages [interactive]", "new interactive card"),
        (
            "dynamic_card.update_card",
            "POST /auth/v3/tenant_access_token/internal",
            "tenant token cache miss or expiry",
        ),
        ("dynamic_card.update_card", "PATCH /im/v1/messages/{message_id}", "exact message reference"),
        ("webhook.challenge", "receive url_verification challenge", "authenticated challenge"),
        (
            "webhook.card.action.trigger",
            "receive card.action.trigger webhook event",
            "authenticated business event",
        ),
        (
            "stream.connect",
            "POST /callback/ws/endpoint [endpoint discovery]",
            "initial connection and every reconnect",
        ),
        ("stream.card.action.trigger", "receive card.action.trigger STREAM frame", "DATA frame only"),
    },
    "DingTalk": {
        ("credential.test_credentials", "POST /v1.0/oauth2/{corpId}/token", "API token cache miss or expiry"),
        (
            "credential.test_credentials",
            "POST /topapi/v2/department/listsub [permission probe]",
            "after OAuth; root department permission preflight",
        ),
        (
            "credential.test_credentials",
            "POST /topapi/v2/user/list [permission probe]",
            "after department probe; root user page-size-1 permission preflight",
        ),
        ("directory.read_snapshot", "POST /v1.0/oauth2/{corpId}/token", "API token cache miss or expiry"),
        (
            "directory.read_snapshot",
            "POST /topapi/v2/department/listsub [permission probe]",
            "before hierarchy traversal",
        ),
        (
            "directory.read_snapshot",
            "POST /topapi/v2/user/list [permission probe]",
            "before paginated user traversal",
        ),
        (
            "directory.read_snapshot",
            "POST /topapi/v2/department/listsub [hierarchy traversal]",
            "each unvisited department, starting at root",
        ),
        (
            "directory.read_snapshot",
            "POST /topapi/v2/user/list [paginated directory traversal]",
            "each visible department",
        ),
        (
            "basic_messaging.test_destination",
            "POST /v1.0/oauth2/{corpId}/token",
            "API token cache miss or expiry",
        ),
        (
            "basic_messaging.test_destination",
            "POST /topapi/v2/user/get",
            "personal user destination",
        ),
        ("basic_messaging.send_text", "POST /v1.0/oauth2/{corpId}/token", "API token cache miss or expiry"),
        ("basic_messaging.send_text", "POST /v1.0/robot/oToMessages/batchSend", "single-user robot text"),
    },
    "WeCom": {
        ("credential.test_credentials", "GET /gettoken", "access-token cache miss or expiry"),
        ("credential.test_credentials", "GET /agent/get [visibility]", "after token acquisition"),
        ("directory.read_snapshot", "GET /gettoken", "access-token cache miss or expiry"),
        ("directory.read_snapshot", "GET /agent/get [visibility]", "always"),
        ("directory.read_snapshot", "GET /user/get [explicit-user branch]", "allow_userinfos member"),
        ("directory.read_snapshot", "GET /department/list [department branch]", "allow_partys root"),
        ("directory.read_snapshot", "GET /user/list [department branch]", "each visible department"),
        ("directory.read_snapshot", "GET /tag/get [tag branch]", "allow_tags member"),
        (
            "directory.read_snapshot",
            "GET /department/list [tag-department branch]",
            "tag-derived department not already expanded through explicit department visibility",
        ),
        (
            "directory.read_snapshot",
            "GET /user/list [tag-department branch]",
            "each tag-derived department not already expanded through explicit department visibility",
        ),
        ("basic_messaging.test_destination", "GET /gettoken", "access-token cache miss or expiry"),
        (
            "basic_messaging.test_destination",
            "GET /user/get [personal-user destination]",
            "exact destination user after token acquisition",
        ),
        ("basic_messaging.send_text", "GET /gettoken", "access-token cache miss or expiry"),
        (
            "basic_messaging.send_text",
            "POST /message/send",
            "application text message with one `touser`",
        ),
    },
    "Microsoft Teams": {
        (
            "credential.test_credentials",
            "POST /{tenant_id}/oauth2/v2.0/token [Graph scope]",
            "Graph token cache miss or expiry",
        ),
        (
            "credential.test_credentials",
            "GET /v1.0/organization/{tenant_id}",
            "after Graph role validation",
        ),
        (
            "directory.read_snapshot",
            "POST /{tenant_id}/oauth2/v2.0/token [Graph scope]",
            "Graph token cache miss or expiry",
        ),
        ("directory.read_snapshot", "GET /v1.0/users [initial page]", "always"),
        (
            "directory.read_snapshot",
            "GET trusted @odata.nextLink [subsequent page]",
            "when a trusted nextLink is present",
        ),
        (
            "basic_messaging.test_destination",
            "POST /{tenant_id}/oauth2/v2.0/token [Bot scope]",
            "Bot token cache miss or expiry",
        ),
        (
            "basic_messaging.test_destination",
            "GET /v3/conversations/{conversation_id}/members/{user_id}",
            "trusted service URL and exact personal user",
        ),
        (
            "basic_messaging.send_text",
            "POST /{tenant_id}/oauth2/v2.0/token [Bot scope]",
            "Bot token cache miss or expiry",
        ),
        (
            "basic_messaging.send_text",
            "POST /v3/conversations/{conversation_id}/activities [text]",
            "trusted service URL",
        ),
        (
            "dynamic_card.send_card",
            "POST /{tenant_id}/oauth2/v2.0/token [Bot scope]",
            "Bot token cache miss or expiry",
        ),
        (
            "dynamic_card.send_card",
            "POST /v3/conversations/{conversation_id}/activities [Adaptive Card]",
            "trusted service URL",
        ),
        (
            "dynamic_card.update_card",
            "POST /{tenant_id}/oauth2/v2.0/token [Bot scope]",
            "Bot token cache miss or expiry",
        ),
        (
            "dynamic_card.update_card",
            "PUT /v3/conversations/{conversation_id}/activities/{activity_id} [Adaptive Card]",
            "exact Activity reference",
        ),
        ("webhook.message.action_submit", "GET Bot OpenID metadata", "metadata cache miss or expiry"),
        ("webhook.message.action_submit", "GET Bot JWKS", "key cache miss or expiry"),
        (
            "webhook.message.action_submit",
            "GET Bot JWKS [unknown-kid refresh]",
            "signed token kid absent from first JWK set used, whether cached, newly loaded, or expiry-refreshed",
        ),
        (
            "webhook.message.action_submit",
            "receive message Activity with Action.Submit value",
            "type=message and exact action_id/value object",
        ),
    },
}


def _expected_exact_inventory_keys() -> set[tuple[str, str, str, str]]:
    return {
        (provider, operation, external_entry, condition)
        for provider, entries in _EXPECTED_EXACT_INVENTORY_ENTRIES.items()
        for operation, external_entry, condition in entries
    }


def _parse_matrix() -> list[dict[str, str]]:
    assert _EVIDENCE_MATRIX.is_file(), "the Provider x operation evidence matrix is required"
    document = _EVIDENCE_MATRIX.read_text()
    external_section, separator, _ = document.partition("## Exact External Entry Inventory")
    if not separator:
        external_section = document.partition("## Test-only Verification Checklist")[0]
    lines = [line for line in external_section.splitlines() if line.startswith("|")]
    assert len(lines) >= 2, "evidence matrix must contain a Markdown table"

    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(values) == len(headers), f"malformed evidence row: {line}"
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _parse_test_only_checklist() -> list[dict[str, str]]:
    lines = _EVIDENCE_MATRIX.read_text().splitlines()
    heading = "## Test-only Verification Checklist"
    assert heading in lines, "test-only behavior must be tracked separately from external evidence"

    section_start = lines.index(heading) + 1
    section_lines = [line for line in lines[section_start:] if line.startswith("|")]
    assert len(section_lines) >= 2, "test-only checklist must contain a Markdown table"

    headers = [cell.strip() for cell in section_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in section_lines[2:]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(values) == len(headers), f"malformed checklist row: {line}"
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _parse_exact_external_inventory() -> list[dict[str, str]]:
    lines = _EVIDENCE_MATRIX.read_text().splitlines()
    heading = "## Exact External Entry Inventory"
    assert heading in lines, "exact external requests and receive entries must be inventoried"

    section_start = lines.index(heading) + 1
    section_end = lines.index("## Test-only Verification Checklist")
    section_lines = [line for line in lines[section_start:section_end] if line.startswith("|")]
    assert len(section_lines) >= 2, "exact external entry inventory must contain a Markdown table"

    headers = [cell.strip() for cell in section_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in section_lines[2:]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(values) == len(headers), f"malformed inventory row: {line}"
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _assert_repository_reference_resolves(reference: str) -> None:
    assert reference.startswith("`")
    assert reference.endswith("`")
    path_text, separator, test_name = reference[1:-1].partition("::")
    path = _REPOSITORY_ROOT / path_text
    assert path.is_file(), f"evidence path does not exist: {path_text}"
    if separator:
        assert f"def {test_name}(" in path.read_text(), f"evidence test does not exist: {reference[1:-1]}"


def test_evidence_matrix_accounts_for_every_applicable_provider_operation() -> None:
    assert _EVIDENCE_MATRIX.is_file(), "the Provider x operation evidence matrix is required"

    rows = _parse_matrix()
    actual_cells = [(row["provider"], row["operation"]) for row in rows]

    assert len(actual_cells) == len(set(actual_cells)), "each Provider x operation cell must be unique"
    assert set(actual_cells) == _expected_cells()
    assert len(actual_cells) == 34


def test_evidence_matrix_uses_explicit_auditable_cell_states() -> None:
    rows = _parse_matrix()

    for row in rows:
        assert row.keys() >= _EVIDENCE_COLUMNS
        for column in _EVIDENCE_COLUMNS:
            value = row[column]
            assert value, f"{row['provider']} {row['operation']} has an empty {column} cell"
            assert value in {"MISSING", "N/A"} or value.startswith("`"), (
                f"{row['provider']} {row['operation']} {column} must be MISSING, N/A, or a repository path"
            )


def test_test_only_behavior_is_not_counted_as_external_provider_evidence() -> None:
    external_operations = {row["operation"] for row in _parse_matrix()}
    assert external_operations.isdisjoint(_TEST_ONLY_BEHAVIORS)

    checklist = _parse_test_only_checklist()
    actual_behaviors = [row["behavior"] for row in checklist]
    assert len(actual_behaviors) == len(set(actual_behaviors)), "each test-only behavior must be unique"
    assert set(actual_behaviors) == _TEST_ONLY_BEHAVIORS
    for row in checklist:
        assert row.keys() >= {"behavior", "test_evidence"}
        assert row["test_evidence"].startswith("`"), f"{row['behavior']} must point to repository test evidence"


def test_all_repository_evidence_references_resolve() -> None:
    matrix_references = (
        row[column] for row in _parse_matrix() for column in _EVIDENCE_COLUMNS if row[column] not in {"MISSING", "N/A"}
    )
    inventory_references = (
        row[column]
        for row in _parse_exact_external_inventory()
        for column in _EVIDENCE_COLUMNS
        if row[column] not in {"MISSING", "N/A"}
    )
    checklist_references = (row["test_evidence"] for row in _parse_test_only_checklist())

    for reference in (*matrix_references, *inventory_references, *checklist_references):
        _assert_repository_reference_resolves(reference)


def test_exact_inventory_covers_every_external_row_and_conditional_request() -> None:
    matrix_cells = {(row["provider"], row["operation"]) for row in _parse_matrix()}
    inventory = _parse_exact_external_inventory()
    inventory_keys = [(row["provider"], row["operation"], row["external_entry"], row["condition"]) for row in inventory]

    assert len(inventory_keys) == len(set(inventory_keys)), "each exact external entry must be unique"
    assert len(inventory_keys) == 77
    assert matrix_cells <= {(provider, operation) for provider, operation, _, _ in inventory_keys}
    assert set(inventory_keys) == _expected_exact_inventory_keys()
    for row in inventory:
        assert row.keys() >= {"provider", "operation", "external_entry", "condition"}
        assert (row["provider"], row["operation"]) in matrix_cells
        assert row["condition"]


def test_scope_corrected_matrix_has_expected_missing_baseline() -> None:
    aggregate_rows = _parse_matrix()
    exact_rows = _parse_exact_external_inventory()

    assert len(aggregate_rows) == 34
    assert len(exact_rows) == 77
    assert {column: sum(row[column] == "MISSING" for row in aggregate_rows) for column in _EVIDENCE_COLUMNS} == {
        "unit_test": 0,
        "integration_test": 0,
        "real_execution": 23,
        "sanitized_fixture": 23,
        "independent_crypto": 4,
    }
    assert {column: sum(row[column] == "MISSING" for row in exact_rows) for column in _EVIDENCE_COLUMNS} == {
        "unit_test": 0,
        "integration_test": 0,
        "real_execution": 37,
        "sanitized_fixture": 37,
        "independent_crypto": 4,
    }


def test_exact_inventory_uses_explicit_auditable_evidence_states() -> None:
    for row in _parse_exact_external_inventory():
        assert row.keys() == _EXACT_INVENTORY_COLUMNS
        for evidence_column in _EVIDENCE_COLUMNS:
            evidence = row[evidence_column]
            assert evidence in {"MISSING", "N/A"} or evidence.startswith("`"), (
                f"{row['provider']} {row['operation']} {row['external_entry']} {evidence_column} "
                "must be MISSING, N/A, or a repository path"
            )


def test_wecom_messaging_uses_only_personal_destination_entries_while_directory_keeps_visibility() -> None:
    destination_entries = {
        row["external_entry"]
        for row in _parse_exact_external_inventory()
        if row["provider"] == "WeCom" and row["operation"] == "basic_messaging.test_destination"
    }
    directory_entries = {
        row["external_entry"]
        for row in _parse_exact_external_inventory()
        if row["provider"] == "WeCom" and row["operation"] == "directory.read_snapshot"
    }

    assert destination_entries == {"GET /gettoken", "GET /user/get [personal-user destination]"}
    assert {
        "GET /agent/get [visibility]",
        "GET /department/list [department branch]",
        "GET /tag/get [tag branch]",
    } <= directory_entries


def test_exact_inventory_applies_each_evidence_axis_to_the_concrete_entry() -> None:
    for row in _parse_exact_external_inventory():
        entry = f"{row['provider']} {row['operation']} {row['external_entry']}"
        assert row["unit_test"].startswith("`"), f"{entry} must have unit test evidence"
        assert row["integration_test"].startswith("`"), f"{entry} must have integration test evidence"
        assert row["real_execution"] != "N/A", f"{entry} can be exercised against the real Provider"
        assert row["sanitized_fixture"] != "N/A", f"{entry} can retain a sanitized fixture"
        if row["sanitized_fixture"].startswith("`"):
            assert row["real_execution"].startswith("`"), f"{entry} fixture must have a real-execution receipt"

        crypto_applicable = (
            row["provider"],
            row["operation"],
            row["external_entry"],
        ) in _CRYPTO_APPLICABLE_EXACT_ENTRIES
        if crypto_applicable:
            assert row["independent_crypto"] != "N/A", f"{entry} requires independent crypto evidence"
        else:
            assert row["independent_crypto"] == "N/A", f"{entry} has no adapter-owned crypto boundary"


def test_aggregate_evidence_is_a_conservative_rollup_of_exact_entries() -> None:
    exact_by_cell: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in _parse_exact_external_inventory():
        exact_by_cell.setdefault((row["provider"], row["operation"]), []).append(row)

    for aggregate_row in _parse_matrix():
        cell = (aggregate_row["provider"], aggregate_row["operation"])
        exact_rows = exact_by_cell[cell]
        for column in _EVIDENCE_COLUMNS:
            exact_states = [row[column] for row in exact_rows]
            aggregate_state = aggregate_row[column]
            if "MISSING" in exact_states:
                assert aggregate_state == "MISSING", f"{cell} {column} must preserve an exact-entry MISSING state"
            elif all(state == "N/A" for state in exact_states):
                assert aggregate_state == "N/A", f"{cell} {column} is not applicable to any exact entry"
            else:
                assert aggregate_state.startswith("`"), f"{cell} {column} must resolve to repository evidence"


def test_slack_socket_fixture_proves_block_action_ack_and_reference_equality() -> None:
    fixture = json.loads(_SLACK_SOCKET_FIXTURE.read_text())
    operations = {operation["operation"]: operation for operation in fixture["operations"]}

    assert fixture["provider"] == "slack"
    assert fixture["transport"] == "socket_mode"
    assert operations["dynamic_card.send_card"]["result"] == {
        "exact_reference_present": True,
        "outcome": "accepted",
        "provider_request_id_present": True,
    }
    stream_operation = operations["stream.interactive.block_actions"]
    assert stream_operation["result"] == {
        "ack_success_count": 1,
        "outcome": "accepted",
        "sink_acceptance_count": 1,
    }
    assert stream_operation["delivery"]["type"] == "interactive"
    assert stream_operation["delivery"]["payload"]["type"] == "block_actions"
    assert stream_operation["normalized_event"]["provider_event_type"] == "block_actions"
    assert stream_operation["ack"] == {
        "envelope_id": "<redacted:string>",
        "payload": None,
    }
    assert operations["dynamic_card.update_card"]["result"] == {
        "exact_reference_preserved": True,
        "outcome": "accepted",
        "provider_request_id_present": True,
    }
    assert [exchange["path"] for exchange in operations["dynamic_card.update_card"]["exchanges"]] == [
        "/api/chat.update"
    ]
    send_exchange = operations["dynamic_card.send_card"]["exchanges"][0]
    update_exchange = operations["dynamic_card.update_card"]["exchanges"][0]
    callback_container = stream_operation["delivery"]["payload"]["container"]
    normalized_container = stream_operation["normalized_event"]["provider_payload"]["container"]
    channel_pseudonyms = {
        send_exchange["response_body"]["channel"],
        callback_container["channel_id"],
        normalized_container["channel_id"],
        update_exchange["request_body"]["channel"],
        update_exchange["response_body"]["channel"],
    }
    timestamp_pseudonyms = {
        send_exchange["response_body"]["ts"],
        send_exchange["response_body"]["message"]["ts"],
        callback_container["message_ts"],
        stream_operation["delivery"]["payload"]["message"]["ts"],
        normalized_container["message_ts"],
        stream_operation["normalized_event"]["provider_payload"]["message"]["ts"],
        update_exchange["request_body"]["ts"],
        update_exchange["response_body"]["ts"],
    }
    assert len(channel_pseudonyms) == 1
    assert len(timestamp_pseudonyms) == 1
    channel_pseudonym = channel_pseudonyms.pop()
    timestamp_pseudonym = timestamp_pseudonyms.pop()
    assert channel_pseudonym.startswith("<pseudonym:slack-channel:")
    assert timestamp_pseudonym.startswith("<pseudonym:slack-message-ts:")
    assert channel_pseudonym != timestamp_pseudonym
    assert fixture["gui_observation"] == {
        "clicked": {"acknowledge_button_clicks": 1},
        "rendered": {
            "enabled_acknowledge_buttons": 1,
            "matching_message_containers": 1,
        },
        "updated": {
            "button_removed": True,
            "matching_bodies": 1,
            "matching_message_containers": 1,
            "matching_titles": 1,
            "remaining_acknowledge_buttons": 0,
            "same_message_container": True,
        },
    }
    assert fixture["audit"] == {
        "ack_attempts": 1,
        "ack_successes": 1,
        "automatic_retries": 0,
        "block_actions_deliveries": 1,
        "chat_post_message_attempts": 1,
        "chat_update_attempts": 1,
        "duration_seconds": fixture["audit"]["duration_seconds"],
        "endpoint_discovery_attempts": 1,
        "endpoint_discovery_successes": 1,
        "gui_acknowledge_button_clicks": 1,
        "gui_buttons_removed": 1,
        "gui_rendered_message_containers": 1,
        "gui_same_container_updates": 1,
        "residual_runner_threads": 0,
        "sink_acceptances": 1,
        "websocket_connection_successes": 1,
    }
    assert fixture["sanitization"] == {
        "credentials_retained": False,
        "pii_retained": False,
        "provider_identity_retained": False,
        "raw_headers_retained": False,
        "safe_test_content_retained": True,
        "stable_reference_pseudonyms": True,
        "url_or_wss_retained": False,
    }

    serialized = _SLACK_SOCKET_FIXTURE.read_text()
    forbidden_patterns = (
        r"xox[a-z]-[A-Za-z0-9-]+",
        r"https?://",
        r"wss://",
        r"(?i:(cookie|set-cookie|x-slack-signature))\s*[:=]",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        r"\b[ACDGTUW][A-Z0-9]{8,}\b",
        r"\b\d{10,}\.\d+\b",
    )
    assert all(re.search(pattern, serialized) is None for pattern in forbidden_patterns)


def test_slack_channel_evidence_does_not_close_personal_card_or_stream_rows() -> None:
    aggregate_rows = {(row["provider"], row["operation"]): row for row in _parse_matrix()}
    exact_rows = {
        (row["provider"], row["operation"], row["external_entry"]): row for row in _parse_exact_external_inventory()
    }

    for operation in (
        "basic_messaging.test_destination",
        "basic_messaging.send_text",
        "dynamic_card.send_card",
        "dynamic_card.update_card",
        "stream.interactive.block_actions",
    ):
        aggregate_row = aggregate_rows[("Slack", operation)]
        assert aggregate_row["real_execution"] == "MISSING"
        assert aggregate_row["sanitized_fixture"] == "MISSING"

    assert aggregate_rows[("Slack", "webhook.interactive.block_actions")]["real_execution"] == "MISSING"
    assert aggregate_rows[("Slack", "webhook.interactive.block_actions")]["sanitized_fixture"] == "MISSING"
    assert aggregate_rows[("Slack", "webhook.interactive.block_actions")]["independent_crypto"] == "MISSING"

    personal_exact_entries = (
        ("basic_messaging.test_destination", "GET /api/users.info"),
        ("basic_messaging.send_text", "POST /api/chat.postMessage [text]"),
        ("dynamic_card.send_card", "POST /api/chat.postMessage [Block Kit]"),
        ("dynamic_card.update_card", "POST /api/chat.update [Block Kit]"),
        (
            "stream.interactive.block_actions",
            "receive interactive Socket Mode envelope with block_actions payload",
        ),
    )
    for operation, external_entry in personal_exact_entries:
        row = exact_rows[("Slack", operation, external_entry)]
        assert row["real_execution"] == "MISSING"
        assert row["sanitized_fixture"] == "MISSING"

    webhook_row = exact_rows[
        (
            "Slack",
            "webhook.interactive.block_actions",
            "receive interactive request with block_actions payload",
        )
    ]
    assert webhook_row["real_execution"] == "MISSING"
    assert webhook_row["sanitized_fixture"] == "MISSING"
    assert webhook_row["independent_crypto"] == "MISSING"

    assert "obsolete historical channel evidence" in _SLACK_LIVE_RECEIPT.read_text()


def test_slack_receipt_correlates_to_current_socket_fixture() -> None:
    fixture_bytes = _SLACK_SOCKET_FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    receipt = _SLACK_LIVE_RECEIPT.read_text()

    assert hashlib.sha256(fixture_bytes).hexdigest() in receipt
    assert fixture["captured_at"] in receipt


def test_feishu_directory_partial_fixture_closes_only_the_exact_token_entry() -> None:
    fixture_bytes = _FEISHU_DIRECTORY_PARTIAL_FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    receipt = _FEISHU_DIRECTORY_PARTIAL_RECEIPT.read_text()
    receipt_reference = f"`{_FEISHU_DIRECTORY_PARTIAL_RECEIPT.relative_to(_REPOSITORY_ROOT)}`"
    fixture_reference = f"`{_FEISHU_DIRECTORY_PARTIAL_FIXTURE.relative_to(_REPOSITORY_ROOT)}`"
    aggregate_rows = {(row["provider"], row["operation"]): row for row in _parse_matrix()}
    exact_rows = {
        (row["provider"], row["operation"], row["external_entry"]): row for row in _parse_exact_external_inventory()
    }

    assert fixture == {
        "audit": {
            "adapter_instances": 1,
            "automatic_retries": 0,
            "credential_invocations": 0,
            "directory_invocations": 1,
            "gui_invocations": 0,
            "messaging_invocations": 0,
            "observed_endpoint_counts": {
                "contact_scopes": 1,
                "explicit_user": 2,
                "tenant_query": 1,
                "tenant_token": 1,
            },
            "provider_configuration_changes": 0,
            "retained_endpoint_counts": {"tenant_token": 1},
        },
        "captured_at": fixture["captured_at"],
        "evidence_scope": {
            "aggregate_directory_complete": False,
            "closed_exact_entries": ["POST /auth/v3/tenant_access_token/internal"],
            "unobserved_exact_entries": [
                "GET /contact/v3/departments/{department_id}/children [paginated]",
                "GET /contact/v3/users/find_by_department [paginated]",
            ],
        },
        "exchange_catalog": {
            "tenant-token-1": {
                "authorization_present": False,
                "method": "POST",
                "path": "/open-apis/auth/v3/tenant_access_token/internal",
                "query": [],
                "request_body": {
                    "app_id": "<redacted:string>",
                    "app_secret": "<redacted:string>",
                },
                "response_body": {
                    "code": 0,
                    "expire": "<redacted:number>",
                    "msg": "<redacted:string>",
                    "tenant_access_token": "<redacted:string>",
                },
                "status_code": 200,
            }
        },
        "operations": [
            {
                "exchange_ids": ["tenant-token-1"],
                "operation": "directory.read_snapshot",
                "result": {
                    "evidence_outcome": "partial",
                    "snapshot_outcome": "success",
                    "tenant_bound": True,
                },
            }
        ],
        "provider": "feishu",
        "sanitization": {
            "credentials_retained": False,
            "pii_retained": False,
            "preclosed_exchanges_retained": False,
            "provider_identity_retained": False,
            "raw_headers_retained": False,
        },
        "source_attempt_sha256": "b003b70793a1b4d3d428e9556f8ff7f9ecdf63b2e384c149bb335db0e969bfca",
    }
    assert hashlib.sha256(fixture_bytes).hexdigest() in receipt
    assert fixture["captured_at"] in receipt
    assert fixture["source_attempt_sha256"] in receipt

    serialized = fixture_bytes.decode()
    forbidden_value_patterns = (
        r"(?i)bearer\s+\S+",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        r"(?i)(?<![a-z0-9])(?:ou|od|oc|om|on|cli)_[a-z0-9_-]{5,}",
    )
    assert all(re.search(pattern, serialized) is None for pattern in forbidden_value_patterns)
    serialized_exchanges = json.dumps(fixture["exchange_catalog"])
    forbidden_dynamic_path_patterns = (
        r"/contact/v3/users/(?!find_by_department)[^/<\s]+",
        r"/contact/v3/departments/[^/<\s]+/children",
    )
    assert all(re.search(pattern, serialized_exchanges) is None for pattern in forbidden_dynamic_path_patterns)

    aggregate_row = aggregate_rows[("Feishu/Lark", "directory.read_snapshot")]
    assert aggregate_row["real_execution"] == "MISSING"
    assert aggregate_row["sanitized_fixture"] == "MISSING"

    token_row = exact_rows[("Feishu/Lark", "directory.read_snapshot", "POST /auth/v3/tenant_access_token/internal")]
    assert token_row["real_execution"] == receipt_reference
    assert token_row["sanitized_fixture"] == fixture_reference

    for external_entry in fixture["evidence_scope"]["unobserved_exact_entries"]:
        row = exact_rows[("Feishu/Lark", "directory.read_snapshot", external_entry)]
        assert row["real_execution"] == "MISSING"
        assert row["sanitized_fixture"] == "MISSING"


def test_feishu_phase_a_fixture_closes_only_successful_api_entries() -> None:
    fixture_bytes = _FEISHU_PHASE_A_FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    receipt = _FEISHU_PHASE_A_RECEIPT.read_text()
    receipt_reference = f"`{_FEISHU_PHASE_A_RECEIPT.relative_to(_REPOSITORY_ROOT)}`"
    fixture_reference = f"`{_FEISHU_PHASE_A_FIXTURE.relative_to(_REPOSITORY_ROOT)}`"
    aggregate_rows = {(row["provider"], row["operation"]): row for row in _parse_matrix()}
    exact_rows = {
        (row["provider"], row["operation"], row["external_entry"]): row for row in _parse_exact_external_inventory()
    }

    assert fixture["provider"] == "feishu"
    assert fixture["audit"] == {
        "adapter_instances": 6,
        "automatic_retries": 0,
        "directory_page_size": 1,
        "operation_invocations": 6,
        "provider_configuration_changes": 0,
        "side_effecting_endpoint_counts": {
            "message_interactive": 1,
            "message_text": 1,
            "message_update": 1,
        },
    }
    assert fixture["sanitization"] == {
        "credentials_retained": False,
        "performed_in_memory_before_persistence": True,
        "pii_retained": False,
        "provider_identity_retained": False,
        "raw_headers_retained": False,
        "stable_reference_pseudonyms": True,
    }
    operations = {operation["operation"]: operation for operation in fixture["operations"]}
    assert operations["credential.test_credentials"]["result"] == {
        "outcome": "success",
        "tenant_bound": True,
    }
    assert operations["directory.read_snapshot"]["result"] == {
        "entries_present": True,
        "outcome": "success",
        "tenant_bound": True,
    }
    assert operations["basic_messaging.test_destination"]["address_type_results"] == {
        "email": {"failure_code": "destination_unreachable", "outcome": "failure"},
        "open_id": {"outcome": "success"},
        "union_id": {"outcome": "success"},
        "user_id": {"outcome": "success"},
    }
    for operation in (
        "basic_messaging.send_text",
        "dynamic_card.send_card",
        "dynamic_card.update_card",
    ):
        assert operations[operation]["result"] == {
            "exact_reference_present": True,
            "outcome": "accepted",
        }

    exchanges = tuple(fixture["exchange_catalog"].values())
    assert len(exchanges) == 21
    card_exchange = next(exchange for exchange in exchanges if exchange["endpoint"] == "message_interactive")
    update_exchange = next(exchange for exchange in exchanges if exchange["endpoint"] == "message_update")
    message_pseudonym = card_exchange["response_body"]["data"]["message_id"]
    assert message_pseudonym.startswith("<pseudonym:feishu-message:")
    assert update_exchange["path"] == f"/open-apis/im/v1/messages/{message_pseudonym}"

    assert hashlib.sha256(fixture_bytes).hexdigest() in receipt
    assert fixture["captured_at"] in receipt
    serialized = fixture_bytes.decode()
    forbidden_patterns = (
        r"(?i)bearer\s+\S+",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)",
        r"(?i)(?<![a-z0-9])(?:ou|od|oc|om|on|cli)_[a-z0-9_-]{5,}",
        r"/open-apis/contact/v3/users/(?!find_by_department|batch_get_id|<redacted)[^/<\s]+",
        r"/open-apis/im/v1/(?:chats|messages)/(?!<)[^/<\s]+",
    )
    assert all(re.search(pattern, serialized) is None for pattern in forbidden_patterns)

    closed_exact_entries = (
        ("basic_messaging.test_destination", "POST /auth/v3/tenant_access_token/internal"),
        ("basic_messaging.test_destination", "GET /contact/v3/users/{id} [open_id]"),
        ("basic_messaging.test_destination", "GET /contact/v3/users/{id} [user_id]"),
        ("basic_messaging.test_destination", "GET /contact/v3/users/{id} [union_id]"),
        ("basic_messaging.send_text", "POST /auth/v3/tenant_access_token/internal"),
        ("basic_messaging.send_text", "POST /im/v1/messages [text]"),
        ("dynamic_card.send_card", "POST /auth/v3/tenant_access_token/internal"),
        ("dynamic_card.send_card", "POST /im/v1/messages [interactive]"),
        ("dynamic_card.update_card", "POST /auth/v3/tenant_access_token/internal"),
        ("dynamic_card.update_card", "PATCH /im/v1/messages/{message_id}"),
    )
    for operation, external_entry in closed_exact_entries:
        row = exact_rows[("Feishu/Lark", operation, external_entry)]
        assert row["real_execution"] == receipt_reference
        assert row["sanitized_fixture"] == fixture_reference

    for operation in (
        "basic_messaging.send_text",
        "dynamic_card.send_card",
        "dynamic_card.update_card",
    ):
        row = aggregate_rows[("Feishu/Lark", operation)]
        assert row["real_execution"] == receipt_reference
        assert row["sanitized_fixture"] == fixture_reference

    for external_entry in ("POST /contact/v3/users/batch_get_id [email]",):
        row = exact_rows[("Feishu/Lark", "basic_messaging.test_destination", external_entry)]
        assert row["real_execution"] == "MISSING"
        assert row["sanitized_fixture"] == "MISSING"
    destination_aggregate = aggregate_rows[("Feishu/Lark", "basic_messaging.test_destination")]
    assert destination_aggregate["real_execution"] == "MISSING"
    assert destination_aggregate["sanitized_fixture"] == "MISSING"


def test_wecom_directory_partial_fixture_closes_only_the_exact_token_entry() -> None:
    fixture_bytes = _WECOM_DIRECTORY_PARTIAL_FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    receipt = _WECOM_DIRECTORY_PARTIAL_RECEIPT.read_text()
    receipt_reference = f"`{_WECOM_DIRECTORY_PARTIAL_RECEIPT.relative_to(_REPOSITORY_ROOT)}`"
    fixture_reference = f"`{_WECOM_DIRECTORY_PARTIAL_FIXTURE.relative_to(_REPOSITORY_ROOT)}`"
    aggregate_rows = {(row["provider"], row["operation"]): row for row in _parse_matrix()}
    exact_rows = {
        (row["provider"], row["operation"], row["external_entry"]): row for row in _parse_exact_external_inventory()
    }

    assert fixture == {
        "audit": {
            "adapter_instances": 1,
            "automatic_retries": 0,
            "credential_invocations": 0,
            "destination_invocations": 0,
            "directory_invocations": 1,
            "observed_endpoint_counts": {
                "agent_get": 1,
                "department_list_explicit": 1,
                "gettoken": 1,
                "user_list_explicit": 1,
            },
            "operation_invocations": 1,
            "provider_configuration_changes": 0,
            "retained_endpoint_counts": {"gettoken": 1},
            "send_invocations": 0,
        },
        "captured_at": fixture["captured_at"],
        "evidence_scope": {
            "closed_exact_entries": ["GET /gettoken"],
            "unobserved_missing_entries": [
                "GET /user/get [explicit-user branch]",
                "GET /tag/get [tag branch]",
                "GET /department/list [tag-department branch]",
                "GET /user/list [tag-department branch]",
            ],
        },
        "exchange_catalog": {
            "gettoken-1": {
                "authorization_present": False,
                "method": "GET",
                "path": "/cgi-bin/gettoken",
                "query": [
                    ["corpid", "<redacted:string>"],
                    ["corpsecret", "<redacted:string>"],
                ],
                "request_body": None,
                "response_body": {
                    "access_token": "<redacted:string>",
                    "errcode": 0,
                    "errmsg": "<redacted:string>",
                    "expires_in": "<redacted:number>",
                },
                "status_code": 200,
            }
        },
        "operations": [
            {
                "exchange_ids": ["gettoken-1"],
                "operation": "directory.read_snapshot",
                "result": {
                    "entries_present": True,
                    "evidence_outcome": "partial",
                    "snapshot_outcome": "success",
                    "tenant_bound": True,
                },
            }
        ],
        "provider": "we_com",
        "sanitization": {
            "credentials_retained": False,
            "pii_retained": False,
            "preclosed_exchanges_retained": False,
            "provider_identity_retained": False,
            "raw_headers_retained": False,
        },
    }
    assert hashlib.sha256(fixture_bytes).hexdigest() in receipt
    assert fixture["captured_at"] in receipt
    assert "Webhook" not in receipt

    serialized = fixture_bytes.decode()
    forbidden_value_patterns = (
        r"(?i)bearer\s+\S+",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)",
        r"(?i)(?<![a-z0-9])ww[a-z0-9]{10,}",
        r"(?<![a-z0-9])\+?\d{7,15}(?![a-z0-9])",
    )
    assert all(re.search(pattern, serialized) is None for pattern in forbidden_value_patterns)

    aggregate_row = aggregate_rows[("WeCom", "directory.read_snapshot")]
    assert aggregate_row["real_execution"] == "MISSING"
    assert aggregate_row["sanitized_fixture"] == "MISSING"

    token_row = exact_rows[("WeCom", "directory.read_snapshot", "GET /gettoken")]
    assert token_row["real_execution"] == receipt_reference
    assert token_row["sanitized_fixture"] == fixture_reference

    for external_entry in fixture["evidence_scope"]["unobserved_missing_entries"]:
        row = exact_rows[("WeCom", "directory.read_snapshot", external_entry)]
        assert row["real_execution"] == "MISSING"
        assert row["sanitized_fixture"] == "MISSING"

    for operation in ("basic_messaging.test_destination", "basic_messaging.send_text"):
        row = exact_rows[("WeCom", operation, "GET /gettoken")]
        assert row["real_execution"] == "MISSING"
        assert row["sanitized_fixture"] == "MISSING"


def test_wecom_live_evidence_is_api_only_and_uses_current_three_role_config() -> None:
    receipt = _WECOM_LIVE_RECEIPT.read_text()
    fixture = json.loads(_WECOM_LIVE_FIXTURE.read_text())

    assert fixture["role_presence"] == {
        "agent_id": True,
        "corp_id": True,
        "corp_secret": True,
        "destination_selected_from_directory_only": True,
    }
    assert [operation["operation"] for operation in fixture["operations"]] == [
        "credential.test_credentials",
        "directory.read_snapshot",
        "basic_messaging.test_destination",
        "basic_messaging.send_text",
    ]
    assert "three production configuration roles" in receipt
    assert "five production configuration roles" not in receipt
    assert "aggregate Directory evidence `MISSING`" in receipt
    assert "aggregate destination evidence `MISSING`" in receipt
    assert "aggregate send evidence also remains `MISSING`" in receipt
    assert all(term not in receipt for term in ("Webhook", "callback", "STREAM"))
    assert all(term not in _WECOM_LIVE_FIXTURE.read_text() for term in ("webhook", "callback", "stream"))


def test_dingtalk_directory_partial_fixture_closes_only_the_exact_token_entry() -> None:
    fixture_bytes = _DINGTALK_DIRECTORY_PARTIAL_FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    receipt = _DINGTALK_DIRECTORY_PARTIAL_RECEIPT.read_text()
    receipt_reference = f"`{_DINGTALK_DIRECTORY_PARTIAL_RECEIPT.relative_to(_REPOSITORY_ROOT)}`"
    fixture_reference = f"`{_DINGTALK_DIRECTORY_PARTIAL_FIXTURE.relative_to(_REPOSITORY_ROOT)}`"
    aggregate_rows = {(row["provider"], row["operation"]): row for row in _parse_matrix()}
    exact_rows = {
        (row["provider"], row["operation"], row["external_entry"]): row for row in _parse_exact_external_inventory()
    }

    assert fixture == {
        "audit": {
            "adapter_instances": 1,
            "automatic_retries": 0,
            "credential_invocations": 0,
            "destination_invocations": 0,
            "directory_invocations": 1,
            "observed_endpoint_counts": {
                "department_permission_probe": 1,
                "department_traversal": 1,
                "oauth_token": 1,
                "user_permission_probe": 1,
                "user_traversal": 1,
            },
            "operation_invocations": 1,
            "provider_configuration_changes": 0,
            "retained_endpoint_counts": {"oauth_token": 1},
            "send_invocations": 0,
        },
        "captured_at": fixture["captured_at"],
        "evidence_scope": {
            "closed_exact_entries": ["POST /v1.0/oauth2/{corpId}/token"],
            "unobserved_missing_entries": [],
        },
        "exchange_catalog": {
            "oauth-token-1": {
                "authorization_present": False,
                "method": "POST",
                "path": "/v1.0/oauth2/<redacted:path-segment>/token",
                "query": [],
                "request_body": {
                    "client_id": "<redacted:string>",
                    "client_secret": "<redacted:string>",
                    "grant_type": "<redacted:string>",
                },
                "response_body": {
                    "access_token": "<redacted:string>",
                    "expires_in": "<redacted:number>",
                },
                "status_code": 200,
            }
        },
        "operations": [
            {
                "exchange_ids": ["oauth-token-1"],
                "operation": "directory.read_snapshot",
                "result": {
                    "entries_present": True,
                    "evidence_outcome": "complete",
                    "snapshot_outcome": "success",
                    "tenant_bound": True,
                },
            }
        ],
        "provider": "ding_talk",
        "sanitization": {
            "credentials_retained": False,
            "pii_retained": False,
            "preclosed_exchanges_retained": False,
            "provider_identity_retained": False,
            "raw_headers_retained": False,
        },
    }
    assert hashlib.sha256(fixture_bytes).hexdigest() in receipt
    assert fixture["captured_at"] in receipt
    assert all(term not in receipt for term in ("Webhook", "STREAM", "stream.connect"))

    serialized = fixture_bytes.decode()
    forbidden_value_patterns = (
        r"(?i)bearer\s+\S+",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)",
        r"(?i)(?<![a-z0-9])ding[a-z0-9_-]{8,}",
        r"(?<![a-z0-9])\+?\d{7,15}(?![a-z0-9])",
    )
    assert all(re.search(pattern, serialized) is None for pattern in forbidden_value_patterns)
    assert "/topapi/v2/department/listsub" not in serialized
    assert "/topapi/v2/user/list" not in serialized

    aggregate_row = aggregate_rows[("DingTalk", "directory.read_snapshot")]
    assert aggregate_row["real_execution"] == receipt_reference
    assert aggregate_row["sanitized_fixture"] == fixture_reference

    token_row = exact_rows[("DingTalk", "directory.read_snapshot", "POST /v1.0/oauth2/{corpId}/token")]
    assert token_row["real_execution"] == receipt_reference
    assert token_row["sanitized_fixture"] == fixture_reference

    preclosed_entries = (
        "POST /topapi/v2/department/listsub [permission probe]",
        "POST /topapi/v2/user/list [permission probe]",
        "POST /topapi/v2/department/listsub [hierarchy traversal]",
        "POST /topapi/v2/user/list [paginated directory traversal]",
    )
    for external_entry in preclosed_entries:
        row = exact_rows[("DingTalk", "directory.read_snapshot", external_entry)]
        assert row["real_execution"] != receipt_reference
        assert row["sanitized_fixture"] != fixture_reference
        assert row["real_execution"].startswith("`")
        assert row["sanitized_fixture"].startswith("`")

    missing_entries = (
        ("basic_messaging.test_destination", "POST /v1.0/oauth2/{corpId}/token"),
        ("basic_messaging.test_destination", "POST /topapi/v2/user/get"),
        ("basic_messaging.send_text", "POST /v1.0/oauth2/{corpId}/token"),
        ("basic_messaging.send_text", "POST /v1.0/robot/oToMessages/batchSend"),
    )
    for operation, external_entry in missing_entries:
        row = exact_rows[("DingTalk", operation, external_entry)]
        assert row["real_execution"] == "MISSING"
        assert row["sanitized_fixture"] == "MISSING"


def test_microsoft_teams_directory_partial_fixture_closes_only_the_exact_token_entry() -> None:
    assert _MS_TEAMS_DIRECTORY_PARTIAL_RECEIPT.exists(), "Microsoft Teams Directory receipt is missing"
    fixture_bytes = _MS_TEAMS_DIRECTORY_PARTIAL_FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    receipt = _MS_TEAMS_DIRECTORY_PARTIAL_RECEIPT.read_text()
    receipt_reference = f"`{_MS_TEAMS_DIRECTORY_PARTIAL_RECEIPT.relative_to(_REPOSITORY_ROOT)}`"
    fixture_reference = f"`{_MS_TEAMS_DIRECTORY_PARTIAL_FIXTURE.relative_to(_REPOSITORY_ROOT)}`"
    aggregate_rows = {(row["provider"], row["operation"]): row for row in _parse_matrix()}
    exact_rows = {
        (row["provider"], row["operation"], row["external_entry"]): row for row in _parse_exact_external_inventory()
    }

    assert fixture == {
        "audit": {
            "adapter_instances": 1,
            "automatic_retries": 0,
            "card_invocations": 0,
            "credential_invocations": 0,
            "directory_invocations": 1,
            "messaging_invocations": 0,
            "observed_endpoint_counts": {
                "graph_scope_token": 1,
                "initial_users_page": 1,
            },
            "operation_invocations": 1,
            "provider_configuration_changes": 0,
            "retained_endpoint_counts": {"graph_scope_token": 1},
            "webhook_invocations": 0,
        },
        "captured_at": fixture["captured_at"],
        "evidence_scope": {
            "closed_exact_entries": ["POST /{tenant_id}/oauth2/v2.0/token [Graph scope]"],
            "unobserved_missing_entries": ["GET trusted @odata.nextLink [subsequent page]"],
        },
        "exchange_catalog": {
            "graph-scope-token-1": {
                "authorization_present": False,
                "method": "POST",
                "origin": "login.microsoftonline.com",
                "path": "/<redacted:path-segment>/oauth2/v2.0/token",
                "query": [],
                "request_body": {
                    "client_id": "<redacted:string>",
                    "client_secret": "<redacted:string>",
                    "grant_type": "<redacted:string>",
                    "scope": "<redacted:string>",
                },
                "response_body": {
                    "access_token": "<redacted:string>",
                    "expires_in": "<redacted:number>",
                    "ext_expires_in": "<redacted:number>",
                    "token_type": "<redacted:string>",
                },
                "status_code": 200,
            }
        },
        "operations": [
            {
                "exchange_ids": ["graph-scope-token-1"],
                "operation": "directory.read_snapshot",
                "result": {
                    "entries_present": True,
                    "evidence_outcome": "partial",
                    "snapshot_outcome": "success",
                    "tenant_bound": True,
                },
            }
        ],
        "provider": "ms_teams",
        "sanitization": {
            "credentials_retained": False,
            "pii_retained": False,
            "preclosed_exchanges_retained": False,
            "provider_identity_retained": False,
            "raw_headers_retained": False,
        },
    }
    assert hashlib.sha256(fixture_bytes).hexdigest() in receipt
    assert fixture["captured_at"] in receipt

    serialized = fixture_bytes.decode()
    forbidden_value_patterns = (
        r"(?i)bearer\s+\S+",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)",
        r"(?<![a-z0-9])\+?\d{7,15}(?![a-z0-9])",
        r"(?i)(?<![a-f0-9])[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}(?![a-f0-9])",
    )
    assert all(re.search(pattern, serialized) is None for pattern in forbidden_value_patterns)
    assert "/v1.0/users" not in serialized

    aggregate_operations = (
        "credential.test_credentials",
        "directory.read_snapshot",
        "basic_messaging.test_destination",
        "basic_messaging.send_text",
        "dynamic_card.send_card",
        "dynamic_card.update_card",
        "webhook.message.action_submit",
    )
    for operation in aggregate_operations:
        row = aggregate_rows[("Microsoft Teams", operation)]
        assert row["real_execution"] == "MISSING"
        assert row["sanitized_fixture"] == "MISSING"

    token_row = exact_rows[
        (
            "Microsoft Teams",
            "directory.read_snapshot",
            "POST /{tenant_id}/oauth2/v2.0/token [Graph scope]",
        )
    ]
    assert token_row["real_execution"] == receipt_reference
    assert token_row["sanitized_fixture"] == fixture_reference

    old_receipt_reference = (
        "`openspec/changes/define-im-provider-adapter-contracts/evidence/microsoft-teams-live-read-only-2026-08-02.md`"
    )
    old_fixture_reference = (
        "`openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/"
        "microsoft-teams-live-read-only-2026-08-02.json`"
    )
    credential_token_row = exact_rows[
        (
            "Microsoft Teams",
            "credential.test_credentials",
            "POST /{tenant_id}/oauth2/v2.0/token [Graph scope]",
        )
    ]
    initial_users_row = exact_rows[
        (
            "Microsoft Teams",
            "directory.read_snapshot",
            "GET /v1.0/users [initial page]",
        )
    ]
    for preclosed_row in (credential_token_row, initial_users_row):
        assert preclosed_row["real_execution"] == old_receipt_reference
        assert preclosed_row["sanitized_fixture"] == old_fixture_reference

    remaining_missing_rows = [
        row
        for key, row in exact_rows.items()
        if key[0] == "Microsoft Teams" and (row["real_execution"] == "MISSING" or row["sanitized_fixture"] == "MISSING")
    ]
    assert len(remaining_missing_rows) == 14
    assert all(row["real_execution"] == "MISSING" for row in remaining_missing_rows)
    assert all(row["sanitized_fixture"] == "MISSING" for row in remaining_missing_rows)
    assert {row["external_entry"] for row in remaining_missing_rows} >= set(
        fixture["evidence_scope"]["unobserved_missing_entries"]
    )


def test_local_verification_receipt_matches_matrix_missing_accounting() -> None:
    receipt = _LOCAL_VERIFICATION_RECEIPT.read_text()
    aggregate_section = receipt.partition("Aggregate capability matrix")[2].partition("Exact External Entry Inventory")[
        0
    ]
    exact_section = receipt.partition("Exact External Entry Inventory")[2].partition("Exact `MISSING`")[0]

    def parse_missing_counts(section: str) -> dict[str, int]:
        return {
            column: int(count)
            for column, count in re.findall(
                r"^\| (unit_test|integration_test|real_execution|sanitized_fixture|independent_crypto) \| (\d+) \|$",
                section,
                flags=re.MULTILINE,
            )
        }

    aggregate_counts = {
        column: sum(row[column] == "MISSING" for row in _parse_matrix()) for column in _EVIDENCE_COLUMNS
    }
    exact_counts = {
        column: sum(row[column] == "MISSING" for row in _parse_exact_external_inventory())
        for column in _EVIDENCE_COLUMNS
    }
    assert parse_missing_counts(aggregate_section) == aggregate_counts
    assert parse_missing_counts(exact_section) == exact_counts


def test_started_exhaustive_tasks_are_blocked_by_exact_inventory_missing_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    aggregate_section, separator, exact_section = _EVIDENCE_MATRIX.read_text().partition(
        "## Exact External Entry Inventory"
    )
    assert separator
    matrix_path = tmp_path / "evidence-matrix.md"
    matrix_path.write_text(aggregate_section.replace("MISSING", "N/A") + separator + exact_section)
    tasks_path = tmp_path / "tasks.md"
    tasks_path.write_text("- [x] 7.5 Keep capabilities incomplete while evidence is missing.\n")
    monkeypatch.setitem(globals(), "_EVIDENCE_MATRIX", matrix_path)
    monkeypatch.setitem(globals(), "_TASKS", tasks_path)

    with pytest.raises(AssertionError, match="exact"):
        test_exhaustive_verification_tasks_cannot_complete_with_missing_evidence()


def test_exhaustive_verification_tasks_cannot_complete_with_missing_evidence() -> None:
    tasks = _TASKS.read_text()
    exhaustive_verification_started = any(f"- [x] 7.{task}" in tasks for task in range(1, 6))
    if not exhaustive_verification_started:
        return

    aggregate_missing = [
        f"aggregate:{row['provider']}:{row['operation']}:{column}"
        for row in _parse_matrix()
        for column in _EVIDENCE_COLUMNS
        if row[column] == "MISSING"
    ]
    exact_missing = [
        f"exact:{row['provider']}:{row['operation']}:{row['external_entry']}:{row['condition']}:{column}"
        for row in _parse_exact_external_inventory()
        for column in _EVIDENCE_COLUMNS
        if row[column] == "MISSING"
    ]
    assert aggregate_missing + exact_missing == []
