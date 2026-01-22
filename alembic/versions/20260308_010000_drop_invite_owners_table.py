"""Drop invite_owners table

Revision ID: 20260308_010000
Revises: 20260307_040000
Create Date: 2026-03-08 01:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_010000"
down_revision = "20260307_040000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS membership_with_title")
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "invite_owners" in insp.get_table_names():
        op.drop_table("invite_owners")


def downgrade() -> None:
    op.create_table(
        "invite_owners",
        sa.Column("invite_hash", sa.Text(), primary_key=True),
        sa.Column("owner_admin_id", sa.Integer()),
        sa.Column("owner_username", sa.Text()),
        sa.Column("created_at", sa.Text()),
    )
