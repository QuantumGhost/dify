"""add im processed callback events

Revision ID: a1b2c3d4e6f7
Revises: 9a1b2c3d4e5f
Create Date: 2026-07-05 22:30:00.000000

"""

from alembic import op
import models as models
import sqlalchemy as sa


revision = "a1b2c3d4e6f7"
down_revision = "9a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "im_processed_callback_events",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("im_processed_callback_events_pkey")),
    )
    with op.batch_alter_table("im_processed_callback_events", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "im_processed_callback_events_provider_event_id_key",
            ["provider", "event_id"],
        )


def downgrade():
    op.drop_table("im_processed_callback_events")
