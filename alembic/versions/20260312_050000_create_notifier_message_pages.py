"""create notifier_message_pages table

Revision ID: 20260312_050000_create_notifier_message_pages
Revises: 20260312_040000_create_planning_request_receiver_contexts
Create Date: 2026-03-12 05:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260312_050000_create_notifier_message_pages"
down_revision = "20260312_040000_create_planning_request_receiver_contexts"
branch_labels = None
depends_on = None


def upgrade():
    database_bind = op.get_bind()
    database_inspector = sa.inspect(database_bind)
    table_names = set(database_inspector.get_table_names())

    if "notifier_message_pages" not in table_names:
        op.create_table(
            "notifier_message_pages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("notification_page_session_identifier", sa.String(length=64), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=False),
            sa.Column("page_text", sa.Text(), nullable=False),
            sa.Column("chat_id", sa.Integer(), nullable=True),
            sa.Column("message_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "notification_page_session_identifier",
                "page_number",
                name="uq_notifier_message_page_session_number",
            ),
        )
        database_inspector = sa.inspect(database_bind)

    existing_indexes = {
        index_metadata["name"]
        for index_metadata in database_inspector.get_indexes("notifier_message_pages")
    }

    if "idx_notifier_message_page_session" not in existing_indexes:
        op.create_index(
            "idx_notifier_message_page_session",
            "notifier_message_pages",
            ["notification_page_session_identifier"],
        )
    if "idx_notifier_message_page_chat_message" not in existing_indexes:
        op.create_index(
            "idx_notifier_message_page_chat_message",
            "notifier_message_pages",
            ["chat_id", "message_id"],
        )


def downgrade():
    database_bind = op.get_bind()
    database_inspector = sa.inspect(database_bind)
    table_names = set(database_inspector.get_table_names())

    if "notifier_message_pages" not in table_names:
        return

    existing_indexes = {
        index_metadata["name"]
        for index_metadata in database_inspector.get_indexes("notifier_message_pages")
    }

    if "idx_notifier_message_page_chat_message" in existing_indexes:
        op.drop_index(
            "idx_notifier_message_page_chat_message",
            table_name="notifier_message_pages",
        )
    if "idx_notifier_message_page_session" in existing_indexes:
        op.drop_index(
            "idx_notifier_message_page_session",
            table_name="notifier_message_pages",
        )

    op.drop_table("notifier_message_pages")
