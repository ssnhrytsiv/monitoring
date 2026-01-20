"""
Drop legacy channel_links table.

Revision ID: 20260305_041000_drop_channel_links
Revises: 20260305_040000_enforce_links_url_norm_unique
Create Date: 2026-03-05 04:10:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260305_041000_drop_channel_links"
down_revision = "20260305_040000_enforce_links_url_norm_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # channel_links більше не використовується після переходу на links.url_norm
    op.drop_table("channel_links")


def downgrade() -> None:
    op.create_table(
        "channel_links",
        sa.Column("link_url_norm", sa.Text(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), index=True),
        sa.Column("first_seen_ts", sa.Integer()),
        sa.Column("last_seen_ts", sa.Integer()),
    )
    op.create_index("ix_channel_links_channel_id", "channel_links", ["channel_id"], unique=False)
