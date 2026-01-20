"""Drop owner_username column from channels

Revision ID: 20260307_020000
Revises: 20260307_010000_drop_invite_cache_updated_at
Create Date: 2026-03-07 02:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260307_020000"
down_revision = "20260307_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS membership_with_title")
    with op.batch_alter_table("channels", recreate="always") as batch:
        batch.drop_column("owner_username")


def downgrade() -> None:
    with op.batch_alter_table("channels", recreate="always") as batch:
        batch.add_column(sa.Column("owner_username", sa.String(), nullable=True))
