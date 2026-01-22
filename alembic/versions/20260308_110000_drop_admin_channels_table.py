"""Drop admin_channels table (now using channels.owner_admin_id)

Revision ID: 20260308_110000
Revises: 20260308_100000
Create Date: 2026-03-08 11:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_110000"
down_revision = "20260308_100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # admin_channels більше не використовується (власник зберігається в channels.owner_admin_id)
    op.drop_table("admin_channels")


def downgrade() -> None:
    op.create_table(
        "admin_channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint("admin_id", "channel_id", name="uq_admin_channel"),
    )
