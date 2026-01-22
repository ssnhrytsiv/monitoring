"""Drop origin_chat column from link_queue

Revision ID: 20260308_060000
Revises: 20260308_050000
Create Date: 2026-03-08 06:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260308_060000"
down_revision = "20260308_050000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("link_queue")}
    if "origin_chat" in cols:
        with op.batch_alter_table("link_queue") as batch_op:
            batch_op.drop_column("origin_chat")


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("link_queue")}
    if "origin_chat" not in cols:
        with op.batch_alter_table("link_queue") as batch_op:
            batch_op.add_column(sa.Column("origin_chat", sa.BigInteger()))
