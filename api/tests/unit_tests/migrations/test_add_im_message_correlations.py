from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations/versions/2026_07_05_2200-9a1b2c3d4e5f_add_im_message_correlations.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("add_im_message_correlations", _MIGRATION_PATH)
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


def test_upgrade_adds_im_message_correlations_table() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    module = _load_migration_module()

    _run_migration_step(module, engine, "upgrade")

    inspector = sa.inspect(engine)
    assert "im_message_correlations" in inspector.get_table_names()

    columns = {column["name"]: column for column in inspector.get_columns("im_message_correlations")}
    assert columns["form_id"]["nullable"] is False
    assert columns["recipient_id"]["nullable"] is False
    assert columns["provider"]["nullable"] is False
    assert columns["interaction_mapping_snapshot"]["nullable"] is False

    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes("im_message_correlations")
    }
    assert indexes["im_message_correlations_form_id_idx"] == ("form_id",)
    assert indexes["im_message_correlations_recipient_id_idx"] == ("recipient_id",)
    assert indexes["im_message_correlations_provider_message_id_idx"] == ("provider_message_id",)

    _run_migration_step(module, engine, "downgrade")
    assert "im_message_correlations" not in sa.inspect(engine).get_table_names()
