"""
Drop unused owner_actions table.

Revision ID: 20260306_010000_drop_owner_actions
Revises: 20260305_120000
Create Date: 2026-03-06 01:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260306_010000_drop_owner_actions"
down_revision = "20260305_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("owner_actions")


def downgrade() -> None:
    op.create_table(
        "owner_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint("owner", "source_ref", "action", name="ux_owner_actions_triplet"),
        sa.UniqueConstraint("idempotency_key", name="ux_owner_actions_idem"),
    )
