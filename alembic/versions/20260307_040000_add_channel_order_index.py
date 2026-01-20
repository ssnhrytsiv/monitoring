"""Add order_index to channels for stable ordering

Revision ID: 20260307_040000
Revises: 20260307_030000
Create Date: 2026-03-07 04:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260307_040000"
down_revision = "20260307_030000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS membership_with_title")
    op.add_column("channels", sa.Column("order_index", sa.BigInteger(), nullable=True))
    op.create_index("ix_channels_order_index", "channels", ["order_index"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_channels_order_index", table_name="channels")
    op.drop_column("channels", "order_index")
