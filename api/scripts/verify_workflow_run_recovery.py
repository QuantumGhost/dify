#!/usr/bin/env python3
"""
Verify that workflow run data was restored from the source database to the target database.

Given one or more workflow run IDs, this script compares every table touched by
the cleanup/recovery process between the source and target databases and
reports any missing, extra, or mismatched rows.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import click
from sqlalchemy import Select, create_engine, select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session, sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))
from models.model import (
    AppAnnotationHitHistory,
    Conversation,
    Message,
    MessageAgentThought,
    MessageAnnotation,
    MessageChain,
    MessageFeedback,
    MessageFile,
)
from models.workflow import ConversationVariable, WorkflowAppLog, WorkflowNodeExecutionModel, WorkflowRun


@dataclass
class ComparisonResult:
    table: str
    missing_in_target: list[str] = field(default_factory=list)
    extra_in_target: list[str] = field(default_factory=list)
    mismatched: dict[str, dict[str, tuple[Any, Any]]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not (self.missing_in_target or self.extra_in_target or self.mismatched)


def session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url)
    return sessionmaker(engine, expire_on_commit=False)


def normalize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def build_row_map(rows: list[Any], model: type) -> dict[Any, dict[str, Any]]:
    mapper = inspect(model)
    columns = mapper.columns
    pk_columns = mapper.primary_key

    def build_key(row: Any) -> Any:
        values = tuple(normalize_value(getattr(row, col.key)) for col in pk_columns)
        return values[0] if len(values) == 1 else values

    row_map: dict[Any, dict[str, Any]] = {}
    for row in rows:
        serialized = {col.key: normalize_value(getattr(row, col.key)) for col in columns}
        row_map[build_key(row)] = serialized
    return row_map


def compare_table(
    *,
    table_label: str,
    model: type,
    source_rows: list[Any],
    target_rows: list[Any],
) -> ComparisonResult:
    source_map = build_row_map(source_rows, model)
    target_map = build_row_map(target_rows, model)

    source_keys = set(source_map.keys())
    target_keys = set(target_map.keys())

    missing = sorted(_key_to_str(key) for key in source_keys - target_keys)
    extra = sorted(_key_to_str(key) for key in target_keys - source_keys)

    mismatched: dict[str, dict[str, tuple[Any, Any]]] = {}
    for key in source_keys & target_keys:
        source_row = source_map[key]
        target_row = target_map[key]
        diff: dict[str, tuple[Any, Any]] = {}
        for field_, source_value in source_row.items():
            target_value = target_row[field_]
            if source_value != target_value:
                diff[field_] = (source_value, target_value)
        if diff:
            mismatched[_key_to_str(key)] = diff

    return ComparisonResult(table=table_label, missing_in_target=missing, extra_in_target=extra, mismatched=mismatched)


def _key_to_str(key: Any) -> str:
    if isinstance(key, tuple):
        return ",".join(str(component) for component in key)
    return str(key)


def fetch_rows(session: Session, stmt: Select[Any]) -> list[Any]:
    return session.execute(stmt).scalars().all()


def compare_with_clause(
    *,
    table_label: str,
    model: type,
    source_session: Session,
    target_session: Session,
    clause: Any,
    capture_source_rows: bool = False,
) -> tuple[ComparisonResult, list[Any] | None]:
    source_rows = fetch_rows(source_session, select(model).where(clause))
    target_rows = fetch_rows(target_session, select(model).where(clause))
    result = compare_table(table_label=table_label, model=model, source_rows=source_rows, target_rows=target_rows)
    return result, (source_rows if capture_source_rows else None)


def _workflow_run_filter(workflow_run_id: str) -> Any:
    try:
        from uuid import UUID

        UUID(workflow_run_id)
        return WorkflowRun.id == workflow_run_id
    except ValueError:
        return WorkflowRun.id == workflow_run_id


def verify_workflow_run(
    workflow_run_id: str,
    source_session_factory: sessionmaker[Session],
    target_session_factory: sessionmaker[Session],
) -> tuple[list[ComparisonResult], bool]:
    with source_session_factory() as source_session, target_session_factory() as target_session:
        results: list[ComparisonResult] = []
        failures = False

        run_result, _ = compare_with_clause(
            table_label="workflow_runs",
            model=WorkflowRun,
            source_session=source_session,
            target_session=target_session,
            clause=_workflow_run_filter(workflow_run_id),
        )
        results.append(run_result)
        failures |= not run_result.ok

        log_result, _ = compare_with_clause(
            table_label="workflow_app_logs",
            model=WorkflowAppLog,
            source_session=source_session,
            target_session=target_session,
            clause=(WorkflowAppLog.workflow_run_id == workflow_run_id),
        )
        results.append(log_result)
        failures |= not log_result.ok

        node_result, _ = compare_with_clause(
            table_label="workflow_node_executions",
            model=WorkflowNodeExecutionModel,
            source_session=source_session,
            target_session=target_session,
            clause=(WorkflowNodeExecutionModel.workflow_run_id == workflow_run_id),
        )
        results.append(node_result)
        failures |= not node_result.ok

        message_result, source_messages = compare_with_clause(
            table_label="messages",
            model=Message,
            source_session=source_session,
            target_session=target_session,
            clause=(Message.workflow_run_id == workflow_run_id),
            capture_source_rows=True,
        )
        results.append(message_result)
        failures |= not message_result.ok

        message_ids = [message.id for message in (source_messages or [])]
        conversation_ids = {message.conversation_id for message in (source_messages or [])}

        def compare_message_child(table_label: str, model: type) -> None:
            child_result, _ = compare_with_clause(
                table_label=table_label,
                model=model,
                source_session=source_session,
                target_session=target_session,
                clause=model.message_id.in_(message_ids) if message_ids else (model.message_id == "__never__"),  # type: ignore[attr-defined]
            )
            results.append(child_result)
            nonlocal failures
            failures |= not child_result.ok

        if message_ids:
            compare_message_child("message_chains", MessageChain)
            compare_message_child("message_agent_thoughts", MessageAgentThought)
            compare_message_child("message_files", MessageFile)
            compare_message_child("message_annotations", MessageAnnotation)
            compare_message_child("app_annotation_hit_histories", AppAnnotationHitHistory)
            compare_message_child("message_feedbacks", MessageFeedback)
        else:
            for label in [
                "message_chains",
                "message_agent_thoughts",
                "message_files",
                "message_annotations",
                "app_annotation_hit_histories",
                "message_feedbacks",
            ]:
                results.append(ComparisonResult(table=label))

        if conversation_ids:
            conversation_clause = Conversation.id.in_(conversation_ids)
            conversation_result, _ = compare_with_clause(
                table_label="conversations",
                model=Conversation,
                source_session=source_session,
                target_session=target_session,
                clause=conversation_clause,
            )
            results.append(conversation_result)
            failures |= not conversation_result.ok

            variable_clause = ConversationVariable.conversation_id.in_(list(conversation_ids))
            conversation_variable_result, _ = compare_with_clause(
                table_label="workflow_conversation_variables",
                model=ConversationVariable,
                source_session=source_session,
                target_session=target_session,
                clause=variable_clause,
            )
            results.append(conversation_variable_result)
            failures |= not conversation_variable_result.ok
        else:
            results.append(ComparisonResult(table="conversations"))
            results.append(ComparisonResult(table="workflow_conversation_variables"))

    return results, failures


def load_workflow_run_ids(
    ids: tuple[str, ...],
    ids_file: Path | None,
) -> list[str]:
    run_ids = list(ids)

    if ids_file:
        content = ids_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped:
                run_ids.append(stripped)

    deduped = list(dict.fromkeys(run_ids))
    if not deduped:
        raise click.ClickException("At least one workflow run ID must be provided.")
    return deduped


def summarize_result(result: ComparisonResult, indent: str = "  ") -> list[str]:
    if result.ok:
        return [f"{indent}[OK ] {result.table}"]

    lines = [f"{indent}[FAIL] {result.table}"]
    if result.missing_in_target:
        lines.append(f"{indent}  Missing in target: {', '.join(result.missing_in_target)}")
    if result.extra_in_target:
        lines.append(f"{indent}  Extra in target: {', '.join(result.extra_in_target)}")
    if result.mismatched:
        preview_items = list(result.mismatched.items())[:3]
        for key, diffs in preview_items:
            lines.append(f"{indent}  Mismatched row {key}:")
            for field, (source_value, target_value) in list(diffs.items())[:5]:
                lines.append(f"{indent}    {field}: source={source_value} target={target_value}")
        if len(result.mismatched) > len(preview_items):
            lines.append(f"{indent}  ... {len(result.mismatched) - len(preview_items)} more mismatched rows")
    return lines


@click.command()
@click.option("--workflow-run-id", "workflow_run_ids", multiple=True, help="Workflow run ID to verify.")
@click.option(
    "--workflow-run-ids-file",
    type=click.Path(path_type=Path),
    help="Path to a file containing workflow run IDs (one per line).",
)
@click.option("--source-db-url", envvar="SOURCE_DB_URL", required=True, help="Source database URL.")
@click.option("--target-db-url", envvar="TARGET_DB_URL", required=True, help="Target database URL.")
def main(
    workflow_run_ids: tuple[str, ...],
    workflow_run_ids_file: Path | None,
    source_db_url: str | None,
    target_db_url: str | None,
) -> None:
    """Validate that workflow run data in the target database matches the source database."""

    run_ids = load_workflow_run_ids(workflow_run_ids, workflow_run_ids_file)

    source_session_factory = session_factory(source_db_url)
    target_session_factory = session_factory(target_db_url)

    overall_failures = False
    for run_id in run_ids:
        click.echo(click.style(f"Verifying workflow run {run_id}", fg="cyan"))
        results, failed = verify_workflow_run(run_id, source_session_factory, target_session_factory)
        overall_failures |= failed

        for result in results:
            for line in summarize_result(result):
                click.echo(line)
        click.echo()

    if overall_failures:
        raise click.ClickException("Verification failed: discrepancies detected.")

    click.echo(click.style("Verification successful for all workflow runs.", fg="green"))


if __name__ == "__main__":
    main()
