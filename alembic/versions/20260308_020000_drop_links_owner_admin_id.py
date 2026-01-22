"""Drop owner_admin_id from links

Revision ID: 20260308_020000
Revises: 20260308_010000
Create Date: 2026-03-08 02:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_020000"
down_revision = "20260308_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("links") as batch_op:
        batch_op.drop_column("owner_admin_id")


def downgrade() -> None:
    with op.batch_alter_table("links") as batch_op:
        batch_op.add_column(sa.Column("owner_admin_id", sa.Integer()))
