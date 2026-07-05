"""add im binding tables

Revision ID: 8c2d4e6f7a9b
Revises: 7f1c2e4d9a6b
Create Date: 2026-07-05 18:00:00.000000

"""

from alembic import op
import models as models
import sqlalchemy as sa


revision = "8c2d4e6f7a9b"
down_revision = "7f1c2e4d9a6b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "im_bindings",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("account_id", models.types.StringUUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("install_mode", sa.String(length=20), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("provider_workspace_id", sa.String(length=255), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("active_account_id", models.types.StringUUID(), nullable=True),
        sa.Column("provider_union_id", sa.String(length=255), nullable=True),
        sa.Column("provider_user_display_name", sa.String(length=255), nullable=True),
        sa.Column("provider_user_avatar_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("im_bindings_pkey")),
    )
    with op.batch_alter_table("im_bindings", schema=None) as batch_op:
        batch_op.create_index("im_bindings_account_id_status_idx", ["account_id", "status"], unique=False)
        batch_op.create_unique_constraint("im_bindings_active_account_id_key", ["active_account_id"])
        batch_op.create_unique_constraint(
            "im_bindings_scope_user_key",
            ["provider", "install_mode", "scope_type", "scope_id", "provider_workspace_id", "provider_user_id"],
        )

    op.create_table(
        "im_binding_sessions",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("account_id", models.types.StringUUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("install_mode", sa.String(length=20), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("im_binding_sessions_pkey")),
    )
    with op.batch_alter_table("im_binding_sessions", schema=None) as batch_op:
        batch_op.create_index("im_binding_sessions_account_id_status_idx", ["account_id", "status"], unique=False)
        batch_op.create_unique_constraint("im_binding_sessions_token_key", ["token"])


def downgrade():
    op.drop_table("im_binding_sessions")
    op.drop_table("im_bindings")
