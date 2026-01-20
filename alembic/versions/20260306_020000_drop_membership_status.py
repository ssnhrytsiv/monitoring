"""
Drop unused membership_status table.

Revision ID: 20260306_020000_drop_membership_status
Revises: 20260306_010000_drop_owner_actions
Create Date: 2026-03-06 02:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260306_020000_drop_membership_status"
down_revision = "20260306_010000_drop_owner_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("membership_status")


def downgrade() -> None:
    op.create_table(
        "membership_status",
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
    )
    op.create_index("ix_membership_status_channel_id", "membership_status", ["channel_id"], unique=False)
