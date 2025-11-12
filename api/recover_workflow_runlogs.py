#!/usr/bin/env python3
"""
Data recovery script for restoring workflow run logs from the source database.

This script restores data that was accidentally deleted by the clean_workflow_runlogs_precise function.
It reads from the source (backup) database and restores missing data to the target database.

Key requirements:
- Only reads from the source database, never modifies it
- Only restores missing/non-existent data to the target database
- Skips restoration if data already exists in the target database
- No other modifications to the target database
"""

import datetime
import logging
import os
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
from sqlalchemy import create_engine, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

# Add the api directory to Python path to import Dify modules
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))
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

logger = logging.getLogger(__name__)

BATCH_SIZE = 2000


def _log_insert(
    table_name: str, rows: list[dict[str, Any]], key_builder: Callable[[dict[str, Any]], str] | None = None
) -> None:
    if not rows:
        return
    keys = [key_builder(row) if key_builder else str(row.get("id")) for row in rows]
    logger.info("Inserted %s rows into %s: %s", len(rows), table_name, keys)
    for key in keys:
        logger.info("Inserted record into table, table_name=%s, id=%s", table_name, key)


def setup_session(database_url: str) -> sessionmaker[Session]:
    """Create session factory for a database."""
    if not database_url:
        raise ValueError("Database URL must be provided.")

    engine = create_engine(database_url)
    return sessionmaker(engine, expire_on_commit=False)


def iter_source_workflow_run_batches(
    source_session_factory: sessionmaker[Session], cutoff_date: datetime.datetime, batch_size: int
) -> Iterator[list[str]]:
    """
    Yield ordered batches of workflow run IDs from the source database.
    Uses keyset pagination to avoid long-running transactions.
    """

    last_created_at: datetime.datetime | None = None
    last_id: str | None = None

    while True:
        with source_session_factory() as source_session:
            stmt = select(WorkflowRun.id, WorkflowRun.created_at).where(WorkflowRun.created_at < cutoff_date)

            if last_created_at is not None and last_id is not None:
                stmt = stmt.where(
                    (WorkflowRun.created_at > last_created_at)
                    | ((WorkflowRun.created_at == last_created_at) & (WorkflowRun.id > last_id))
                )

            stmt = stmt.order_by(WorkflowRun.created_at, WorkflowRun.id).limit(batch_size)

            rows = source_session.execute(stmt).all()

        if not rows:
            break

        last_created_at = rows[-1].created_at
        last_id = rows[-1].id

        ids = [row.id for row in rows]
        yield ids


def _filter_missing_workflow_runs(target_session_factory: sessionmaker[Session], candidate_ids: list[str]) -> list[str]:
    """
    Return IDs from candidate_ids that do not yet exist in production.
    """
    if not candidate_ids:
        return []

    with target_session_factory() as target_session:
        existing_target_ids = set(
            target_session.execute(select(WorkflowRun.id).where(WorkflowRun.id.in_(candidate_ids))).scalars().all()
        )
    return [workflow_run_id for workflow_run_id in candidate_ids if workflow_run_id not in existing_target_ids]


_UNSET = object()


def _extract_mapped_value(row: Any, column_attr: Any, instance_dict: dict[str, Any]) -> Any:
    """
    Resolve the Python-level value for a mapped column.

    SQLAlchemy allows a column name (e.g. "inputs") to map onto a differently named Python
    attribute (e.g. "_inputs").  The ORM stores the loaded value under column_attr.key,
    but relationship loaders or descriptors might also expose the column name itself.
    We therefore:
        1. Prefer the attribute key recorded by the mapper (column_attr.key).
        2. Fall back to the column name (column.key) if the mapper created synonyms.
        3. Default to None when neither attribute currently has a value (e.g. deferred columns).

    This logic keeps us from accidentally reading higher-level properties (like
    WorkflowRun.inputs_dict) while still handling private attribute names without special cases.
    """

    column = column_attr.columns[0]
    # First try the mapper’s attribute key (handles private names like "_inputs").
    value = instance_dict.get(column_attr.key, _UNSET)

    if value is _UNSET:
        # Fall back to getattr in case the attribute is defined via descriptor.
        value = getattr(row, column_attr.key, _UNSET)

    if value is _UNSET:
        # Some models expose both names; check the column key on the instance dict.
        value = instance_dict.get(column.key, _UNSET)

    if value is _UNSET:
        # Finally, try getattr using the column name (covers synonym/alias cases).
        value = getattr(row, column.key, _UNSET)

    if value is _UNSET:
        # Unset values (e.g. deferred columns) are serialized as None.
        value = None

    return value


def _model_to_dict(row: Any) -> dict[str, Any]:
    """
    Convert a SQLAlchemy ORM instance to a dict keyed by mapper attribute names.

    NOTE: For ORM objects we must stick to the Python attribute keys (e.g. `_inputs` on
    Conversation). SQLAlchemy’s mapper ensures those keys map back to the correct DB
    column when `bulk_insert_mappings` runs, so we deliberately avoid raw column names here.
    """
    inspected = sa_inspect(row)
    instance_dict = getattr(inspected, "dict", row.__dict__)
    data: dict[str, Any] = {}

    for attr in inspected.mapper.column_attrs:
        data[attr.key] = _extract_mapped_value(row, attr, instance_dict)

    return data


MESSAGE_RELATED_MODELS: Sequence[tuple[type[Any], str]] = [
    (AppAnnotationHitHistory, "message_id"),
    (MessageAgentThought, "message_id"),
    (MessageChain, "message_id"),
    (MessageFile, "message_id"),
    (MessageAnnotation, "message_id"),
    (MessageFeedback, "message_id"),
]


@dataclass
class WorkflowRunPayload:
    workflow_run: dict[str, Any]
    workflow_app_logs: list[dict[str, Any]] = field(default_factory=list)
    workflow_node_executions: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    message_related: dict[type[Any], list[dict[str, Any]]] = field(default_factory=dict)
    conversations: list[dict[str, Any]] = field(default_factory=list)
    conversation_variables: list[dict[str, Any]] = field(default_factory=list)


def restore_workflow_runs_batch(
    source_session_factory: sessionmaker[Session],
    target_session_factory: sessionmaker[Session],
    workflow_run_ids: list[str],
    dry_run: bool = False,
) -> int:
    """
    Restore a batch of workflow runs and their related data from the source database to the target database.
    Only restores data that doesn't exist in production.
    Uses conflict-tolerant inserts with short-lived transactions per workflow run.
    """
    restored_count = 0

    for workflow_run_id in workflow_run_ids:
        payload = _collect_workflow_run_payload(source_session_factory, workflow_run_id)
        if payload is None:
            continue
        restored_count += _persist_workflow_run_payload(target_session_factory, payload, dry_run=dry_run)

    return restored_count


def _collect_workflow_run_payload(
    source_session_factory: sessionmaker[Session], workflow_run_id: str
) -> WorkflowRunPayload | None:
    with source_session_factory() as source_session:
        workflow_run = source_session.execute(
            select(WorkflowRun).where(WorkflowRun.id == workflow_run_id)
        ).scalar_one_or_none()
        if workflow_run is None:
            return None

        payload = WorkflowRunPayload(workflow_run=_model_to_dict(workflow_run))

        payload.workflow_app_logs = _fetch_model_dicts(
            source_session, WorkflowAppLog, WorkflowAppLog.workflow_run_id == workflow_run_id
        )
        payload.workflow_node_executions = _fetch_model_dicts(
            source_session, WorkflowNodeExecutionModel, WorkflowNodeExecutionModel.workflow_run_id == workflow_run_id
        )
        payload.messages = _fetch_model_dicts(source_session, Message, Message.workflow_run_id == workflow_run_id)

        message_ids = [message["id"] for message in payload.messages]
        conversation_ids = {
            message["conversation_id"] for message in payload.messages if message.get("conversation_id")
        }

        payload.message_related = {}
        if message_ids:
            for model, foreign_key_field in MESSAGE_RELATED_MODELS:
                payload.message_related[model] = _fetch_model_dicts(
                    source_session, model, getattr(model, foreign_key_field).in_(message_ids)
                )
        else:
            for model, _ in MESSAGE_RELATED_MODELS:
                payload.message_related[model] = []

        if conversation_ids:
            conversation_ids_list = list(conversation_ids)
            payload.conversations = _fetch_model_dicts(
                source_session, Conversation, Conversation.id.in_(conversation_ids_list)
            )
            payload.conversation_variables = _fetch_model_dicts(
                source_session,
                ConversationVariable,
                ConversationVariable.conversation_id.in_(conversation_ids_list),
            )

        return payload


def _fetch_model_dicts(session: Session, model: type[Any], clause: Any) -> list[dict[str, Any]]:
    records = session.execute(select(model).where(clause)).scalars().all()
    return [_model_to_dict(record) for record in records]


def _persist_workflow_run_payload(
    target_session_factory: sessionmaker[Session],
    payload: WorkflowRunPayload,
    *,
    dry_run: bool,
) -> int:
    inserted_rows = 0

    with target_session_factory() as target_session:
        transaction = target_session.begin()
        try:
            inserted_rows += _insert_with_conflict_handling(target_session, WorkflowRun, [payload.workflow_run])
            inserted_rows += _insert_with_conflict_handling(target_session, WorkflowAppLog, payload.workflow_app_logs)
            inserted_rows += _insert_with_conflict_handling(
                target_session, WorkflowNodeExecutionModel, payload.workflow_node_executions
            )
            inserted_rows += _insert_with_conflict_handling(target_session, Conversation, payload.conversations)
            inserted_rows += _insert_with_conflict_handling(
                target_session,
                ConversationVariable,
                payload.conversation_variables,
                key_builder=lambda row: f"{row.get('conversation_id')}:{row.get('id')}",
            )
            inserted_rows += _insert_with_conflict_handling(target_session, Message, payload.messages)

            for model, _ in MESSAGE_RELATED_MODELS:
                inserted_rows += _insert_with_conflict_handling(
                    target_session, model, payload.message_related.get(model, [])
                )

            if dry_run:
                transaction.rollback()
            else:
                transaction.commit()
        except Exception:
            transaction.rollback()
            raise

    return inserted_rows


def _insert_with_conflict_handling(
    session: Session,
    model: type[Any],
    rows: list[dict[str, Any]],
    key_builder: Callable[[dict[str, Any]], str] | None = None,
) -> int:
    if not rows:
        return 0

    bind = session.get_bind()
    mapper = sa_inspect(model)
    pk_columns = list(mapper.primary_key)

    if bind is None or bind.dialect.name != "postgresql":
        raise Exception("only postgresql is supported!")

    stmt = pg_insert(model).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=[column.name for column in pk_columns])
    stmt = stmt.returning(*pk_columns)
    result = session.execute(stmt)
    inserted_keys = [_normalize_returned_primary_key(row, len(pk_columns)) for row in result.fetchall()]
    if not inserted_keys:
        return 0
    inserted_rows = _filter_rows_by_primary_keys(rows, pk_columns, inserted_keys)
    _log_insert(model.__tablename__, inserted_rows, key_builder=key_builder)
    return len(inserted_keys)


def _primary_key_from_row_dict(row: dict[str, Any], pk_columns: Sequence[Any]) -> Any:
    values = tuple(row[column.key] for column in pk_columns)
    return values[0] if len(values) == 1 else values


def _normalize_returned_primary_key(row: Any, num_columns: int) -> Any:
    if num_columns == 1:
        return row[0]
    return tuple(row[i] for i in range(num_columns))


def _filter_rows_by_primary_keys(
    rows: list[dict[str, Any]],
    pk_columns: Sequence[Any],
    inserted_keys: list[Any],
) -> list[dict[str, Any]]:
    key_set = set(inserted_keys)
    filtered_rows: list[dict[str, Any]] = []
    for row in rows:
        key = _primary_key_from_row_dict(row, pk_columns)
        if key in key_set:
            filtered_rows.append(row)
    return filtered_rows


@click.command()
@click.option("--source-db-url", envvar="SOURCE_DB_URL", required=True, help="Source (read-only) database URL.")
@click.option("--target-db-url", envvar="TARGET_DB_URL", required=True, help="Target (write) database URL.")
@click.option("--retention-days", type=int, help="Retention days to match the cleanup logic.")
@click.option("--dry-run", is_flag=True, help="Execute restore logic but roll back each batch.")
@click.option("--batch-size", type=int, default=BATCH_SIZE, show_default=True, help="Batch size for processing.")
def recover_workflow_runlogs(
    source_db_url: str, target_db_url: str, retention_days: int | None, dry_run: bool, batch_size: int
):
    """
    Recover workflow run logs from the source database to the target database.
    """
    if retention_days is None:
        retention_days = int(os.environ.get("WORKFLOW_LOG_RETENTION_DAYS", "30"))

    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=retention_days)

    click.echo(click.style("Starting workflow run logs recovery...", fg="green"))
    click.echo(f"Cutoff date: {cutoff_date}")
    click.echo(f"Retention days: {retention_days}")
    click.echo(f"Dry run: {dry_run}")
    click.echo(f"Batch size: {batch_size}")

    source_session_factory = setup_session(source_db_url)
    target_session_factory = setup_session(target_db_url)

    total_restored = 0

    try:
        missing_found = False
        batch_count = 0

        for candidate_ids in iter_source_workflow_run_batches(source_session_factory, cutoff_date, batch_size):
            missing_ids = _filter_missing_workflow_runs(target_session_factory, candidate_ids)

            if not missing_ids:
                continue

            missing_found = True
            batch_count += 1

            batch_label = f"Processing batch {batch_count}: {len(missing_ids)} workflow runs"
            if dry_run:
                batch_label += " [dry-run]"
            click.echo(batch_label)

            batch_restored = restore_workflow_runs_batch(
                source_session_factory, target_session_factory, missing_ids, dry_run=dry_run
            )
            total_restored += batch_restored

            click.echo(f"Batch {batch_count} restored: {batch_restored} records")
            click.echo(f"Total restored so far: {total_restored}")

        if not missing_found:
            click.echo(click.style("No workflow runs need to be restored.", fg="green"))
            return

        if dry_run:
            click.echo(f"DRY RUN COMPLETE: Would restore {total_restored} records across {batch_count} batches")
            return

    except Exception as e:
        logger.exception("Recovery failed")
        click.echo(click.style(f"Recovery failed: {e}", fg="red"))
        sys.exit(1)

    click.echo(click.style(f"Recovery completed successfully. Total records restored: {total_restored}", fg="green"))


if __name__ == "__main__":
    recover_workflow_runlogs()
