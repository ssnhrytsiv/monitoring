"""
Create invite_cache table and backfill from invite_map/invite_status.

Revision ID: 20260305_050000_create_invite_cache
Revises: 20260305_041000_drop_channel_links
Create Date: 2026-03-05 05:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260305_050000_create_invite_cache"
down_revision = "20260305_041000_drop_channel_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    has_invite_cache = inspector.has_table("invite_cache")

    if not has_invite_cache:
        op.create_table(
            "invite_cache",
            sa.Column("invite_hash", sa.String(), primary_key=True),
            sa.Column("channel_id", sa.Integer(), index=True, nullable=True),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("session", sa.String(), nullable=True),
            sa.Column("updated_at", sa.Integer(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
        )
        op.create_index("ix_invite_cache_channel_id", "invite_cache", ["channel_id"], unique=False)
    else:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("invite_cache")}
        if "ix_invite_cache_channel_id" not in existing_indexes:
            op.create_index("ix_invite_cache_channel_id", "invite_cache", ["channel_id"], unique=False)

    # Backfill із invite_map + invite_status
    conn.execute(
        sa.text(
            """
            INSERT INTO invite_cache (invite_hash, channel_id, title, status, updated_at)
            SELECT im.invite_hash,
                   im.channel_id,
                   im.title,
                   isq.status,
                   COALESCE(isq.ts, im.updated_at)
            FROM invite_map im
            LEFT JOIN invite_status isq ON isq.invite_hash = im.invite_hash
            WHERE im.invite_hash NOT IN (SELECT invite_hash FROM invite_cache)
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_invite_cache_channel_id", table_name="invite_cache")
    op.drop_table("invite_cache")
