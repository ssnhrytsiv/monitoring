"""create planning_request_receiver_contexts table

Revision ID: 20260312_040000_create_planning_request_receiver_contexts
Revises: 20260312_030000_create_planning_requests
Create Date: 2026-03-12 04:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260312_040000_create_planning_request_receiver_contexts"
down_revision = "20260312_030000_create_planning_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planning_request_receiver_contexts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("planning_request_id", sa.Integer(), nullable=True),
        sa.Column("receiver_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("order_message_id", sa.BigInteger(), nullable=False),
        sa.Column("administrator_name", sa.Text(), nullable=True),
        sa.Column("order_message_text", sa.Text(), nullable=False),
        sa.Column("order_links_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_added_to_schedule", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "receiver_chat_id",
            "order_message_id",
            name="uq_planning_request_receiver_context_message",
        ),
    )
    op.create_index(
        "idx_planning_request_receiver_contexts_planning_request_id",
        "planning_request_receiver_contexts",
        ["planning_request_id"],
    )
    op.create_index(
        "idx_planning_request_receiver_contexts_receiver_chat_id",
        "planning_request_receiver_contexts",
        ["receiver_chat_id"],
    )


def downgrade():
    op.drop_index(
        "idx_planning_request_receiver_contexts_receiver_chat_id",
        table_name="planning_request_receiver_contexts",
    )
    op.drop_index(
        "idx_planning_request_receiver_contexts_planning_request_id",
        table_name="planning_request_receiver_contexts",
    )
    op.drop_table("planning_request_receiver_contexts")
