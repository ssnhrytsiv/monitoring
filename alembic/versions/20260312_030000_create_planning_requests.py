"""create planning_requests table

Revision ID: 20260312_030000_create_planning_requests
Revises: 20260312_020000_drop_watch_post_templates
Create Date: 2026-03-12 03:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260312_030000_create_planning_requests"
down_revision = "20260312_020000_drop_watch_post_templates"
branch_labels = None
depends_on = None


def upgrade():
    database_bind = op.get_bind()
    database_inspector = sa.inspect(database_bind)
    table_names = set(database_inspector.get_table_names())

    if "planning_requests" not in table_names:
        op.create_table(
            "planning_requests",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("request_source", sa.Text(), nullable=False),
            sa.Column("request_kind", sa.Text(), nullable=False),
            sa.Column("source_query_text", sa.Text(), nullable=True),
            sa.Column("source_message_text", sa.Text(), nullable=True),
            sa.Column("source_message_id", sa.BigInteger(), nullable=True),
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
            sa.Column("telegram_username", sa.Text(), nullable=True),
            sa.Column("telegram_first_name", sa.Text(), nullable=True),
            sa.Column("telegram_last_name", sa.Text(), nullable=True),
            sa.Column("client_name", sa.Text(), nullable=True),
            sa.Column("administrator_name", sa.Text(), nullable=True),
            sa.Column("client_reference_number", sa.Text(), nullable=True),
            sa.Column("price_amount", sa.Integer(), nullable=True),
            sa.Column("posts_count", sa.Integer(), nullable=True),
            sa.Column("thousand_message_price", sa.Integer(), nullable=True),
            sa.Column("comment_text", sa.Text(), nullable=True),
            sa.Column("links_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
        )
        database_inspector = sa.inspect(database_bind)

    existing_indexes = {
        index_metadata["name"]
        for index_metadata in database_inspector.get_indexes("planning_requests")
    }

    if "idx_planning_requests_created_at" not in existing_indexes:
        op.create_index(
            "idx_planning_requests_created_at",
            "planning_requests",
            ["created_at"],
        )
    if "idx_planning_requests_telegram_user_id" not in existing_indexes:
        op.create_index(
            "idx_planning_requests_telegram_user_id",
            "planning_requests",
            ["telegram_user_id"],
        )
    if "idx_planning_requests_request_source" not in existing_indexes:
        op.create_index(
            "idx_planning_requests_request_source",
            "planning_requests",
            ["request_source"],
        )


def downgrade():
    database_bind = op.get_bind()
    database_inspector = sa.inspect(database_bind)
    table_names = set(database_inspector.get_table_names())

    if "planning_requests" not in table_names:
        return

    existing_indexes = {
        index_metadata["name"]
        for index_metadata in database_inspector.get_indexes("planning_requests")
    }

    if "idx_planning_requests_request_source" in existing_indexes:
        op.drop_index("idx_planning_requests_request_source", table_name="planning_requests")
    if "idx_planning_requests_telegram_user_id" in existing_indexes:
        op.drop_index("idx_planning_requests_telegram_user_id", table_name="planning_requests")
    if "idx_planning_requests_created_at" in existing_indexes:
        op.drop_index("idx_planning_requests_created_at", table_name="planning_requests")

    op.drop_table("planning_requests")
