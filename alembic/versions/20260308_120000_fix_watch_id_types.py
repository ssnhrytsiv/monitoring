"""Fix watch-related id column types

Revision ID: 20260308_120000
Revises: 20260308_110000
Create Date: 2026-03-08 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_120000"
down_revision = "20260308_110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("watch_posts", recreate="always") as batch_op:
        batch_op.alter_column(
            "group_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            nullable=True,
        )

    with op.batch_alter_table("watch_events", recreate="always") as batch_op:
        batch_op.alter_column(
            "watch_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            nullable=False,
        )

    with op.batch_alter_table("watch_candidates", recreate="always") as batch_op:
        batch_op.alter_column(
            "watch_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("watch_candidates", recreate="always") as batch_op:
        batch_op.alter_column(
            "watch_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            nullable=False,
        )

    with op.batch_alter_table("watch_events", recreate="always") as batch_op:
        batch_op.alter_column(
            "watch_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            nullable=False,
        )

    with op.batch_alter_table("watch_posts", recreate="always") as batch_op:
        batch_op.alter_column(
            "group_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            nullable=True,
        )
