"""Drop raw_url column from links

Revision ID: 20260308_050000
Revises: 20260308_040000
Create Date: 2026-03-08 05:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_050000"
down_revision = "20260308_040000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("links") as batch_op:
        batch_op.drop_column("raw_url")


def downgrade() -> None:
    with op.batch_alter_table("links") as batch_op:
        batch_op.add_column(sa.Column("raw_url", sa.Text()))
