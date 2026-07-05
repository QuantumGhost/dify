from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations/versions/2026_07_05_2300-b2c3d4e5f6a7_add_human_input_snapshot_carriers.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("add_human_input_snapshot_carriers", _MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load migration module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration_step(module: object, engine: sa.Engine, step_name: str) -> None:
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = module.op
        module.op = operations
        try:
            getattr(module, step_name)()
        finally:
            module.op = original_op


def _create_pre_upgrade_schema(engine: sa.Engine) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "human_input_forms",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("app_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("form_kind", sa.String(length=20), nullable=False),
        sa.Column("node_id", sa.String(length=60), nullable=False),
        sa.Column("form_definition", sa.Text(), nullable=False),
        sa.Column("rendered_content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expiration_time", sa.DateTime(), nullable=False),
        sa.Column("selected_action_id", sa.String(length=200), nullable=True),
        sa.Column("submitted_data", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("submission_user_id", sa.String(length=36), nullable=True),
        sa.Column("submission_end_user_id", sa.String(length=36), nullable=True),
        sa.Column("completed_by_recipient_id", sa.String(length=36), nullable=True),
    )
    sa.Table(
        "human_input_form_recipients",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("form_id", sa.String(length=36), nullable=False),
        sa.Column("delivery_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_type", sa.String(length=20), nullable=False),
        sa.Column("recipient_payload", sa.Text(), nullable=False),
        sa.Column("access_token", sa.String(length=32), nullable=False),
    )
    metadata.create_all(engine)


def test_upgrade_adds_human_input_snapshot_carriers_without_rewriting_existing_rows() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    _create_pre_upgrade_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO human_input_forms (
                    id, created_at, updated_at, tenant_id, app_id, workflow_run_id, conversation_id,
                    form_kind, node_id, form_definition, rendered_content, status, expiration_time
                ) VALUES (
                    :id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :tenant_id, :app_id, :workflow_run_id, :conversation_id,
                    :form_kind, :node_id, :form_definition, :rendered_content, :status, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "id": "form-1",
                "tenant_id": "tenant-1",
                "app_id": "app-1",
                "workflow_run_id": "run-1",
                "conversation_id": None,
                "form_kind": "runtime",
                "node_id": "node-1",
                "form_definition": "{}",
                "rendered_content": "{}",
                "status": "waiting",
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO human_input_form_recipients (
                    id, created_at, updated_at, form_id, delivery_id, recipient_type, recipient_payload, access_token
                ) VALUES (
                    :id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :form_id, :delivery_id, :recipient_type, :recipient_payload, :access_token
                )
                """
            ),
            {
                "id": "recipient-1",
                "form_id": "form-1",
                "delivery_id": "delivery-1",
                "recipient_type": "email_external",
                "recipient_payload": "{\"TYPE\":\"email_external\",\"email\":\"vendor@example.com\"}",
                "access_token": "token-1",
            },
        )

    module = _load_migration_module()
    _run_migration_step(module, engine, "upgrade")

    inspector = sa.inspect(engine)
    form_columns = {column["name"]: column for column in inspector.get_columns("human_input_forms")}
    recipient_columns = {column["name"]: column for column in inspector.get_columns("human_input_form_recipients")}
    assert form_columns["initiator_approval_snapshot"]["nullable"] is True
    assert recipient_columns["contact_snapshot"]["nullable"] is True

    with engine.begin() as connection:
        stored_form_snapshot = connection.execute(
            sa.text("SELECT initiator_approval_snapshot FROM human_input_forms WHERE id = :id"),
            {"id": "form-1"},
        ).scalar_one()
        stored_recipient_snapshot = connection.execute(
            sa.text("SELECT contact_snapshot FROM human_input_form_recipients WHERE id = :id"),
            {"id": "recipient-1"},
        ).scalar_one()
    assert stored_form_snapshot is None
    assert stored_recipient_snapshot is None

    _run_migration_step(module, engine, "downgrade")

    downgraded_form_columns = {column["name"] for column in sa.inspect(engine).get_columns("human_input_forms")}
    downgraded_recipient_columns = {
        column["name"] for column in sa.inspect(engine).get_columns("human_input_form_recipients")
    }
    assert "initiator_approval_snapshot" not in downgraded_form_columns
    assert "contact_snapshot" not in downgraded_recipient_columns
