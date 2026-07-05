"""add im self-built tenant configs and app installations

Revision ID: a4f0a91b3c2d
Revises: 8c2d4e6f7a9b
Create Date: 2026-07-05 23:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

import models

revision = "a4f0a91b3c2d"
down_revision = "8c2d4e6f7a9b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "im_self_built_tenant_configs",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("tenant_id", models.types.StringUUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_workspace_id", sa.String(length=255), nullable=True),
        sa.Column("app_id", sa.String(length=255), nullable=True),
        sa.Column("encrypted_app_secret", models.types.LongText(), nullable=True),
        sa.Column("encrypted_verification_token", models.types.LongText(), nullable=True),
        sa.Column("encrypted_encrypt_key", models.types.LongText(), nullable=True),
        sa.Column("event_mode", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("im_self_built_tenant_configs_pkey")),
    )
    with op.batch_alter_table("im_self_built_tenant_configs", schema=None) as batch_op:
        batch_op.create_index(
            "im_self_built_tenant_configs_tenant_provider_idx",
            ["tenant_id", "provider"],
            unique=False,
        )
        batch_op.create_unique_constraint(
            "im_self_built_tenant_configs_tenant_provider_key",
            ["tenant_id", "provider"],
        )

    op.create_table(
        "im_app_installations",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("tenant_id", models.types.StringUUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("install_mode", sa.String(length=20), nullable=False),
        sa.Column("install_status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("provider_workspace_id", sa.String(length=255), nullable=True),
        sa.Column("encrypted_access_token", models.types.LongText(), nullable=True),
        sa.Column("encrypted_refresh_token", models.types.LongText(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("token_refreshed_at", sa.DateTime(), nullable=True),
        sa.Column("token_refresh_error", sa.String(length=1024), nullable=True),
        sa.Column("installed_at", sa.DateTime(), nullable=True),
        sa.Column("uninstalled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("im_app_installations_pkey")),
    )
    with op.batch_alter_table("im_app_installations", schema=None) as batch_op:
        batch_op.create_index(
            "im_app_installations_tenant_provider_status_idx",
            ["tenant_id", "provider", "install_status"],
            unique=False,
        )
        batch_op.create_unique_constraint(
            "im_app_installations_tenant_provider_install_mode_key",
            ["tenant_id", "provider", "install_mode"],
        )


def downgrade():
    op.drop_table("im_app_installations")
    op.drop_table("im_self_built_tenant_configs")
