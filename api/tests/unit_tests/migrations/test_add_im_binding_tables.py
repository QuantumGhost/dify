from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations/versions/2026_07_05_1800-8c2d4e6f7a9b_add_im_binding_tables.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("add_im_binding_tables", _MIGRATION_PATH)
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


def test_upgrade_adds_im_binding_tables() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    module = _load_migration_module()

    _run_migration_step(module, engine, "upgrade")

    inspector = sa.inspect(engine)
    assert "im_bindings" in inspector.get_table_names()
    assert "im_binding_sessions" in inspector.get_table_names()

    binding_indexes = {index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes("im_bindings")}
    assert binding_indexes["im_bindings_account_id_status_idx"] == ("account_id", "status")

    bindings = sa.Table("im_bindings", sa.MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            bindings.insert().values(
                id="binding-1",
                account_id="account-1",
                provider="feishu",
                install_mode="self_built",
                scope_type="deployment",
                scope_id="deployment",
                provider_workspace_id="ws-1",
                provider_user_id="user-1",
                provider_union_id=None,
                provider_user_display_name="User 1",
                provider_user_avatar_url=None,
                status="active",
            )
        )
        try:
            connection.execute(
                bindings.insert().values(
                    id="binding-2",
                    account_id="account-2",
                    provider="feishu",
                    install_mode="self_built",
                    scope_type="deployment",
                    scope_id="deployment",
                    provider_workspace_id="ws-1",
                    provider_user_id="user-1",
                    provider_union_id=None,
                    provider_user_display_name="User 1 duplicate",
                    provider_user_avatar_url=None,
                    status="active",
                )
            )
        except sa.exc.IntegrityError:
            pass
        else:
            raise AssertionError("expected duplicate provider identity to violate unique constraint")

    session_indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes("im_binding_sessions")
    }
    assert session_indexes["im_binding_sessions_account_id_status_idx"] == ("account_id", "status")

    _run_migration_step(module, engine, "downgrade")
    assert "im_bindings" not in sa.inspect(engine).get_table_names()
