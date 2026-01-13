"""add watch tables to main db

Revision ID: 3a1b9c7d5e8f
Revises: 2d3b4a2f9d9c
Create Date: 2026-01-12 01:05:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# Note: tables may already exist (legacy). We skip creation if present to allow upgrading.
def _table_exists(conn, name: str) -> bool:
    res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name})
    return res.scalar() is not None

# revision identifiers, used by Alembic.
revision = "3a1b9c7d5e8f"
down_revision = "2d3b4a2f9d9c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "watch_groups"):
        op.create_table(
            "watch_groups",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("project", sa.Text(), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("created_by", sa.BigInteger(), nullable=True),
            sa.Column("created_via", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("admin_id", sa.Integer(), nullable=True),
            sa.Column("network_id", sa.Integer(), nullable=True),
            sa.Column("actual_views", sa.Integer(), nullable=True),
            sa.Column("actual_price", sa.Float(), nullable=True),
            sa.Column("actual_cpm", sa.Float(), nullable=True),
            sa.Column("subscribers", sa.Integer(), nullable=True),
        )

    if not _table_exists(conn, "watch_posts"):
        op.create_table(
            "watch_posts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("channel_id", sa.BigInteger(), nullable=True),
            sa.Column("template_id", sa.Integer(), nullable=True),
            sa.Column("expected_text_hash", sa.Text(), nullable=True),
            sa.Column("expected_text_norm_len", sa.Integer(), nullable=True),
            sa.Column("expected_links_json", sa.Text(), nullable=True),
            sa.Column("expected_media_fingerprint", sa.Text(), nullable=True),
            sa.Column("time_window_start", sa.Text(), nullable=True),
            sa.Column("time_window_end", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=True),
            sa.Column("matched_message_id", sa.BigInteger(), nullable=True),
            sa.Column("matched_at", sa.Text(), nullable=True),
            sa.Column("coverage_check_at", sa.Text(), nullable=True),
            sa.Column("final_views", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.Text(), nullable=True),
            sa.Column("matched_session", sa.Text(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("created_by", sa.BigInteger(), nullable=True),
            sa.Column("created_via", sa.Text(), nullable=True),
            sa.Column("project", sa.Text(), nullable=True),
            sa.Column("group_id", sa.BigInteger(), nullable=True),
            sa.Column("admin_id", sa.Integer(), nullable=True),
            sa.Column("network_id", sa.Integer(), nullable=True),
            sa.Column("posted_at", sa.Text(), nullable=True),
            sa.Column("views_at_post", sa.Integer(), nullable=True),
            sa.Column("subs_at_post", sa.Integer(), nullable=True),
            sa.Column("cpm_at_post", sa.Float(), nullable=True),
            sa.Column("price_at_post", sa.Float(), nullable=True),
        )
        op.create_index("idx_wp_channel", "watch_posts", ["channel_id"])
        op.create_index("idx_wp_status", "watch_posts", ["status"])
        op.create_index("idx_wp_covcheck", "watch_posts", ["coverage_check_at"])
        op.create_index("idx_wp_matched_session", "watch_posts", ["matched_session"])
        op.create_index("idx_wp_created_by", "watch_posts", ["created_by"])
        op.create_index("idx_wp_group", "watch_posts", ["group_id"])
        op.create_index("idx_wp_posted_at", "watch_posts", ["posted_at"])
        op.create_index("idx_wp_admin", "watch_posts", ["admin_id"])
        op.create_index("idx_wp_network", "watch_posts", ["network_id"])
        op.create_index(
            "uq_active_watch",
            "watch_posts",
            ["channel_id", "template_id", "expected_text_hash"],
            unique=True,
            sqlite_where=text("status IN ('pending','matched')"),
        )

    if not _table_exists(conn, "watch_events"):
        op.create_table(
            "watch_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("watch_id", sa.BigInteger(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("sent_to", sa.BigInteger(), nullable=True),
            sa.Column("sent_at", sa.Text(), nullable=True),
        )
        op.create_index("idx_we_sent_at", "watch_events", ["sent_at"])
        op.create_index("idx_we_unsent", "watch_events", ["sent_at", "id"])

    if not _table_exists(conn, "watch_candidates"):
        op.create_table(
            "watch_candidates",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("watch_id", sa.BigInteger(), nullable=False),
            sa.Column("channel_id", sa.BigInteger(), nullable=True),
            sa.Column("message_id", sa.BigInteger(), nullable=True),
            sa.Column("text_hash", sa.Text(), nullable=True),
            sa.Column("similarity", sa.Float(), nullable=True),
            sa.Column("message_text", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=True, default="pending"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.Text(), nullable=True),
        )
        op.create_index("idx_wc_watch", "watch_candidates", ["watch_id"])
        op.create_index("idx_wc_status", "watch_candidates", ["status"])
        op.create_index("idx_wc_expires", "watch_candidates", ["expires_at"])
        op.create_index("idx_wc_text_hash", "watch_candidates", ["text_hash"])


def downgrade() -> None:
    op.drop_index("idx_wc_text_hash", table_name="watch_candidates")
    op.drop_index("idx_wc_expires", table_name="watch_candidates")
    op.drop_index("idx_wc_status", table_name="watch_candidates")
    op.drop_index("idx_wc_watch", table_name="watch_candidates")
    op.drop_table("watch_candidates")

    op.drop_index("idx_we_unsent", table_name="watch_events")
    op.drop_index("idx_we_sent_at", table_name="watch_events")
    op.drop_table("watch_events")

    op.drop_index("uq_active_watch", table_name="watch_posts")
    op.drop_index("idx_wp_network", table_name="watch_posts")
    op.drop_index("idx_wp_admin", table_name="watch_posts")
    op.drop_index("idx_wp_posted_at", table_name="watch_posts")
    op.drop_index("idx_wp_group", table_name="watch_posts")
    op.drop_index("idx_wp_created_by", table_name="watch_posts")
    op.drop_index("idx_wp_matched_session", table_name="watch_posts")
    op.drop_index("idx_wp_covcheck", table_name="watch_posts")
    op.drop_index("idx_wp_status", table_name="watch_posts")
    op.drop_index("idx_wp_channel", table_name="watch_posts")
    op.drop_table("watch_posts")

    op.drop_table("watch_groups")
