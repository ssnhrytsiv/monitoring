"""Add FK from invite_cache.channel_id to channels.channel_id

Revision ID: 20250304_000001
Revises: 2d3b4a2f9d9c
Create Date: 2025-03-04 00:00:01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250304_000001"
down_revision = "20260306_020000_drop_membership_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invite_cache", recreate="always") as batch:
        batch.alter_column(
            "channel_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
            nullable=True,
        )
        batch.create_foreign_key(
            "fk_invite_cache_channel",
            "channels",
            ["channel_id"],
            ["channel_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("invite_cache", recreate="always") as batch:
        batch.drop_constraint("fk_invite_cache_channel", type_="foreignkey")
        batch.alter_column(
            "channel_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
            nullable=True,
        )
