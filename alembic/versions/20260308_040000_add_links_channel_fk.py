"""Add FK links.channel_id -> channels.channel_id

Revision ID: 20260308_040000
Revises: 20260308_030000
Create Date: 2026-03-08 04:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_040000"
down_revision = "20260308_030000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("links") as batch_op:
        batch_op.create_foreign_key(
            "fk_links_channel_id",
            "channels",
            ["channel_id"],
            ["channel_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("links") as batch_op:
        batch_op.drop_constraint("fk_links_channel_id", type_="foreignkey")
