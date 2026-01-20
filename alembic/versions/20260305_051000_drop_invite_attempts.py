"""
Drop unused invite_attempts table.

Revision ID: 20260305_051000_drop_invite_attempts
Revises: 20260305_050000_create_invite_cache
Create Date: 2026-03-05 05:10:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260305_051000_drop_invite_attempts"
down_revision = "20260305_050000_create_invite_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("invite_attempts")


def downgrade() -> None:
    op.create_table(
        "invite_attempts",
        sa.Column("invite_hash", sa.String(), primary_key=True),
        sa.Column("day", sa.Integer(), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
