"""Drop owner_username from links

Revision ID: 20260308_030000
Revises: 20260308_020000
Create Date: 2026-03-08 03:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_030000"
down_revision = "20260308_020000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("links") as batch_op:
        batch_op.drop_column("owner_username")


def downgrade() -> None:
    with op.batch_alter_table("links") as batch_op:
        batch_op.add_column(sa.Column("owner_username", sa.String()))
