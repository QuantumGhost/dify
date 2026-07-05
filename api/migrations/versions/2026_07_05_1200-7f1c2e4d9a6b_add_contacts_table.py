"""add contacts table

Revision ID: 7f1c2e4d9a6b
Revises: c3d4e5f6a7b8
Create Date: 2026-07-05 12:00:00.000000

"""

from alembic import op
import models as models
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7f1c2e4d9a6b"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contacts",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("tenant_id", models.types.StringUUID(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("account_id", models.types.StringUUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "(type != 'member') OR (account_id IS NOT NULL AND source = 'workspace_member')",
            name="contacts_member_shape_ck",
        ),
        sa.CheckConstraint(
            "(type != 'external') OR (account_id IS NULL AND trim(name) <> '' "
            "AND email IS NOT NULL AND trim(email) <> '' AND source = 'manual_external')",
            name="contacts_external_shape_ck",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("contacts_pkey")),
    )
    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.create_index("contacts_tenant_created_at_id_idx", ["tenant_id", "created_at", "id"], unique=False)
        batch_op.create_unique_constraint(
            "contacts_tenant_type_account_id_key",
            ["tenant_id", "type", "account_id"],
        )


def downgrade():
    op.drop_table("contacts")
