"""
Drop legacy bot tables and subscriptions

Revision ID: 20260305_020000
Revises: 20260305_010300
Create Date: 2026-03-05 02:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260305_020000"
down_revision = "20260305_010300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("bot_watch")
    op.drop_table("bot_template")
    op.drop_table("subscriptions")


def downgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("channel_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("joined", sa.Integer(), nullable=True),
        sa.Column("session_alias", sa.Text(), nullable=True),
        sa.Column("last_join_try_ts", sa.Integer(), nullable=True),
        sa.Column("join_error", sa.Text(), nullable=True),
    )
    op.create_table(
        "bot_template",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("links", sa.Text(), nullable=True),
    )
    op.create_table(
        "bot_watch",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("expected_html", sa.Text(), nullable=True),
        sa.Column("expected_norm", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("session", sa.Text(), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("matched_session", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.Column("time_window_end", sa.Text(), nullable=True),
    )

