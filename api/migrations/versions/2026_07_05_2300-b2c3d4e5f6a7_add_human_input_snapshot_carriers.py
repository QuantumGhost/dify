"""add human input snapshot carriers

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e6f7
Create Date: 2026-07-05 23:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e6f7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("human_input_forms", schema=None) as batch_op:
        batch_op.add_column(sa.Column("initiator_approval_snapshot", sa.Text(), nullable=True))

    with op.batch_alter_table("human_input_form_recipients", schema=None) as batch_op:
        batch_op.add_column(sa.Column("contact_snapshot", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("human_input_form_recipients", schema=None) as batch_op:
        batch_op.drop_column("contact_snapshot")

    with op.batch_alter_table("human_input_forms", schema=None) as batch_op:
        batch_op.drop_column("initiator_approval_snapshot")
