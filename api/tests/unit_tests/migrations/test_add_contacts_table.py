from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations/versions/2026_07_05_1200-7f1c2e4d9a6b_add_contacts_table.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("add_contacts_table", _MIGRATION_PATH)
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


def test_upgrade_adds_contacts_table_with_workspace_member_uniqueness() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    module = _load_migration_module()

    _run_migration_step(module, engine, "upgrade")

    inspector = sa.inspect(engine)
    assert "contacts" in inspector.get_table_names()

    columns = {column["name"]: column for column in inspector.get_columns("contacts")}
    assert columns["tenant_id"]["nullable"] is False
    assert columns["type"]["nullable"] is False
    assert columns["account_id"]["nullable"] is True
    assert columns["status"]["nullable"] is False
    assert columns["source"]["nullable"] is False

    unique_constraints = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("contacts")
    }
    assert unique_constraints["contacts_tenant_type_account_id_key"] == ("tenant_id", "type", "account_id")
    indexes = {index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes("contacts")}
    assert indexes["contacts_tenant_created_at_id_idx"] == ("tenant_id", "created_at", "id")

    contacts = sa.Table("contacts", sa.MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                contacts.insert().values(
                    id="contact-1",
                    tenant_id="tenant-1",
                    type="external",
                    account_id="account-1",
                    name="Broken",
                    email=None,
                    status="active",
                    source="manual_external",
                )
            )
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                contacts.insert().values(
                    id="contact-2",
                    tenant_id="tenant-1",
                    type="external",
                    account_id=None,
                    name="Blank Email",
                    email="   ",
                    status="active",
                    source="manual_external",
                )
            )
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                contacts.insert().values(
                    id="contact-2b",
                    tenant_id="tenant-1",
                    type="external",
                    account_id=None,
                    name="   ",
                    email="vendor@example.com",
                    status="active",
                    source="manual_external",
                )
            )
        connection.execute(
            contacts.insert().values(
                id="contact-3",
                tenant_id="tenant-1",
                type="member",
                account_id="account-1",
                name="Member A",
                email="member-a@example.com",
                status="active",
                source="workspace_member",
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                contacts.insert().values(
                    id="contact-4",
                    tenant_id="tenant-1",
                    type="member",
                    account_id="account-1",
                    name="Member B",
                    email="member-b@example.com",
                    status="disabled",
                    source="workspace_member",
                )
            )

    _run_migration_step(module, engine, "downgrade")
    assert "contacts" not in sa.inspect(engine).get_table_names()
