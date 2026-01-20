"""Drop invite_map and invite_status legacy tables

Revision ID: 20260305_120000
Revises: 20260305_050000_create_invite_cache
Create Date: 2026-03-05 12:00:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260305_120000"
down_revision = "20260305_051000_drop_invite_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("invite_map")
    op.drop_table("invite_status")


def downgrade() -> None:
    op.create_table(
        "invite_map",
        sa.Column("invite_hash", sa.Text(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Integer(), nullable=True),
    )
    op.create_table(
        "invite_status",
        sa.Column("invite_hash", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
    )
