from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations/versions/2026_07_05_2230-a1b2c3d4e6f7_add_im_processed_callback_events.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("add_im_processed_callback_events", _MIGRATION_PATH)
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


def test_upgrade_adds_im_processed_callback_events_table() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    module = _load_migration_module()

    _run_migration_step(module, engine, "upgrade")

    inspector = sa.inspect(engine)
    assert "im_processed_callback_events" in inspector.get_table_names()
    constraints = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("im_processed_callback_events")
    }
    assert constraints["im_processed_callback_events_provider_event_id_key"] == ("provider", "event_id")

    _run_migration_step(module, engine, "downgrade")
    assert "im_processed_callback_events" not in sa.inspect(engine).get_table_names()
