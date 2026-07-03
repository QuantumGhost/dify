"""add_account_im_bindings

Revision ID: 4b6e0c9a2d11
Revises: a6f1c9d2e8b4
Create Date: 2026-07-03 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from models.types import StringUUID

# revision identifiers, used by Alembic.
revision: str = "4b6e0c9a2d11"
down_revision: str | None = "a6f1c9d2e8b4"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_im_bindings",
        sa.Column("id", StringUUID, nullable=False),
        sa.Column("tenant_id", StringUUID, nullable=False),
        sa.Column("account_id", StringUUID, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("open_id", sa.String(length=255), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="account_im_binding_pkey"),
        sa.UniqueConstraint("tenant_id", "account_id", "provider", name="unique_account_im_binding"),
        sa.UniqueConstraint("tenant_id", "provider", "open_id", name="unique_account_im_binding_open_id"),
        sa.UniqueConstraint("tenant_id", "provider", "user_id", name="unique_account_im_binding_user_id"),
    )
    op.create_index("account_im_bindings_tenant_idx", "account_im_bindings", ["tenant_id"], unique=False)
    op.create_index("account_im_bindings_account_idx", "account_im_bindings", ["account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("account_im_bindings_account_idx", table_name="account_im_bindings")
    op.drop_index("account_im_bindings_tenant_idx", table_name="account_im_bindings")
    op.drop_table("account_im_bindings")
