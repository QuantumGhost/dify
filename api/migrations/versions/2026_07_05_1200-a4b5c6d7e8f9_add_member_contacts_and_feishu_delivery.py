"""add member contacts and feishu delivery audit

Revision ID: a4b5c6d7e8f9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-05 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a4b5c6d7e8f9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "member_contacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="member_contact_pkey"),
        sa.UniqueConstraint("tenant_id", "account_id", name="unique_member_contact_tenant_account"),
    )
    op.create_index("member_contacts_tenant_id_idx", "member_contacts", ["tenant_id"])
    op.create_index("member_contacts_account_id_idx", "member_contacts", ["account_id"])

    op.create_table(
        "human_input_feishu_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("form_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_id", sa.String(length=36), nullable=False),
        sa.Column("member_contact_id", sa.String(length=36), nullable=True),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("open_id", sa.String(length=255), nullable=True),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.Column("delivery_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("card_payload", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="human_input_feishu_delivery_pkey"),
        sa.UniqueConstraint("form_id", "recipient_id", name="unique_form_recipient_feishu_delivery"),
    )
    op.create_index("human_input_feishu_deliveries_form_id_idx", "human_input_feishu_deliveries", ["form_id"])
    op.create_index(
        "human_input_feishu_deliveries_message_id_idx",
        "human_input_feishu_deliveries",
        ["message_id"],
    )


def downgrade():
    op.drop_index("human_input_feishu_deliveries_message_id_idx", table_name="human_input_feishu_deliveries")
    op.drop_index("human_input_feishu_deliveries_form_id_idx", table_name="human_input_feishu_deliveries")
    op.drop_table("human_input_feishu_deliveries")

    op.drop_index("member_contacts_account_id_idx", table_name="member_contacts")
    op.drop_index("member_contacts_tenant_id_idx", table_name="member_contacts")
    op.drop_table("member_contacts")
