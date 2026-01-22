"""Drop owner_username column from link_queue

Revision ID: 20260308_070000
Revises: 20260308_060000
Create Date: 2026-03-08 07:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260308_070000"
down_revision = "20260308_060000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("link_queue")}
    if "owner_username" in cols:
        with op.batch_alter_table("link_queue") as batch_op:
            batch_op.drop_column("owner_username")


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("link_queue")}
    if "owner_username" not in cols:
        with op.batch_alter_table("link_queue") as batch_op:
            batch_op.add_column(sa.Column("owner_username", sa.String()))
