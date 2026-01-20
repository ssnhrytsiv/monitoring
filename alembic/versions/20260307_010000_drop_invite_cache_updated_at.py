"""Drop updated_at column from invite_cache

Revision ID: 20260307_010000
Revises: 20250304_000001_invite_cache_channel_fk
Create Date: 2026-03-07 01:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260307_010000"
down_revision = "20250304_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invite_cache", recreate="always") as batch:
        batch.drop_column("updated_at")


def downgrade() -> None:
    with op.batch_alter_table("invite_cache", recreate="always") as batch:
        batch.add_column(sa.Column("updated_at", sa.Integer(), nullable=True))
