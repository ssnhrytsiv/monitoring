"""create channel_subscription_audit table

Revision ID: 20260313_010000_create_channel_subscription_audit
Revises: 20260312_050000_create_notifier_message_pages
Create Date: 2026-03-13 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260313_010000_create_channel_subscription_audit"
down_revision = "20260312_050000_create_notifier_message_pages"
branch_labels = None
depends_on = None


def upgrade():
    database_bind = op.get_bind()
    database_inspector = sa.inspect(database_bind)
    table_names = set(database_inspector.get_table_names())

    if "channel_subscription_audit" not in table_names:
        op.create_table(
            "channel_subscription_audit",
            sa.Column("channel_id", sa.BigInteger(), nullable=False),
            sa.Column("audit_status", sa.String(), nullable=False),
            sa.Column("checked_at", sa.Integer(), nullable=False),
            sa.Column("missing_detected_at", sa.Integer(), nullable=True),
            sa.Column("status_details", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("channel_id"),
        )
        database_inspector = sa.inspect(database_bind)

    existing_indexes = {
        index_metadata["name"]
        for index_metadata in database_inspector.get_indexes(
            "channel_subscription_audit"
        )
    }
    if "ix_channel_subscription_audit_audit_status" not in existing_indexes:
        op.create_index(
            "ix_channel_subscription_audit_audit_status",
            "channel_subscription_audit",
            ["audit_status"],
        )
    if "ix_channel_subscription_audit_checked_at" not in existing_indexes:
        op.create_index(
            "ix_channel_subscription_audit_checked_at",
            "channel_subscription_audit",
            ["checked_at"],
        )


def downgrade():
    database_bind = op.get_bind()
    database_inspector = sa.inspect(database_bind)
    table_names = set(database_inspector.get_table_names())

    if "channel_subscription_audit" not in table_names:
        return

    existing_indexes = {
        index_metadata["name"]
        for index_metadata in database_inspector.get_indexes(
            "channel_subscription_audit"
        )
    }
    if "ix_channel_subscription_audit_checked_at" in existing_indexes:
        op.drop_index(
            "ix_channel_subscription_audit_checked_at",
            table_name="channel_subscription_audit",
        )
    if "ix_channel_subscription_audit_audit_status" in existing_indexes:
        op.drop_index(
            "ix_channel_subscription_audit_audit_status",
            table_name="channel_subscription_audit",
        )
    op.drop_table("channel_subscription_audit")
