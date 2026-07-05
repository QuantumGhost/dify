"""add im message correlations

Revision ID: 9a1b2c3d4e5f
Revises: 8c2d4e6f7a9b
Create Date: 2026-07-05 22:00:00.000000

"""

from alembic import op
import models as models
import sqlalchemy as sa


revision = "9a1b2c3d4e5f"
down_revision = "8c2d4e6f7a9b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "im_message_correlations",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("form_id", models.types.StringUUID(), nullable=False),
        sa.Column("recipient_id", models.types.StringUUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_workspace_id", sa.String(length=255), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("last_provider_event_id", sa.String(length=255), nullable=True),
        sa.Column("delivery_status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("target_card_status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("interaction_mapping_snapshot", sa.Text(), nullable=False),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("im_message_correlations_pkey")),
    )
    with op.batch_alter_table("im_message_correlations", schema=None) as batch_op:
        batch_op.create_index("im_message_correlations_form_id_idx", ["form_id"], unique=False)
        batch_op.create_index("im_message_correlations_recipient_id_idx", ["recipient_id"], unique=False)
        batch_op.create_index(
            "im_message_correlations_provider_message_id_idx",
            ["provider_message_id"],
            unique=False,
        )


def downgrade():
    op.drop_table("im_message_correlations")
