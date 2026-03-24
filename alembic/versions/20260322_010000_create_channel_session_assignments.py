"""create channel_session_assignments table

Revision ID: 20260322_010000_create_channel_session_assignments
Revises: 20260313_010000_create_channel_subscription_audit
Create Date: 2026-03-22 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260322_010000_create_channel_session_assignments"
down_revision = "20260313_010000_create_channel_subscription_audit"
branch_labels = None
depends_on = None


def upgrade():
    database_bind = op.get_bind()
    database_inspector = sa.inspect(database_bind)
    table_names = set(database_inspector.get_table_names())

    if "channel_session_assignments" not in table_names:
        op.create_table(
            "channel_session_assignments",
            sa.Column("channel_id", sa.BigInteger(), nullable=False),
            sa.Column("session_name", sa.Text(), nullable=False),
            sa.Column("admin_id", sa.Integer(), nullable=True),
            sa.Column("assigned_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.Column("last_ok_at", sa.Integer(), nullable=True),
            sa.Column("last_repair_at", sa.Integer(), nullable=True),
            sa.Column("assignment_source", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("channel_id"),
        )
        database_inspector = sa.inspect(database_bind)

    existing_indexes = {
        index_metadata["name"]
        for index_metadata in database_inspector.get_indexes(
            "channel_session_assignments"
        )
    }
    if "ix_channel_session_assignments_session_name" not in existing_indexes:
        op.create_index(
            "ix_channel_session_assignments_session_name",
            "channel_session_assignments",
            ["session_name"],
        )
    if "ix_channel_session_assignments_admin_id" not in existing_indexes:
        op.create_index(
            "ix_channel_session_assignments_admin_id",
            "channel_session_assignments",
            ["admin_id"],
        )
    if "ix_channel_session_assignments_updated_at" not in existing_indexes:
        op.create_index(
            "ix_channel_session_assignments_updated_at",
            "channel_session_assignments",
            ["updated_at"],
        )


def downgrade():
    database_bind = op.get_bind()
    database_inspector = sa.inspect(database_bind)
    table_names = set(database_inspector.get_table_names())

    if "channel_session_assignments" not in table_names:
        return

    existing_indexes = {
        index_metadata["name"]
        for index_metadata in database_inspector.get_indexes(
            "channel_session_assignments"
        )
    }
    if "ix_channel_session_assignments_updated_at" in existing_indexes:
        op.drop_index(
            "ix_channel_session_assignments_updated_at",
            table_name="channel_session_assignments",
        )
    if "ix_channel_session_assignments_admin_id" in existing_indexes:
        op.drop_index(
            "ix_channel_session_assignments_admin_id",
            table_name="channel_session_assignments",
        )
    if "ix_channel_session_assignments_session_name" in existing_indexes:
        op.drop_index(
            "ix_channel_session_assignments_session_name",
            table_name="channel_session_assignments",
        )
    op.drop_table("channel_session_assignments")
