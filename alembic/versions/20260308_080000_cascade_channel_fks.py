"""Set CASCADE on channel_id FKs in links and invite_cache

Revision ID: 20260308_080000
Revises: 20260308_070000
Create Date: 2026-03-08 08:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_080000"
down_revision = "20260308_070000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite не дозволяє просто змінити ondelete, тому використовуємо recreate="always".
    with op.batch_alter_table("links", recreate="always") as batch_op:
        batch_op.alter_column("channel_id", existing_type=sa.BigInteger(), nullable=True)
        batch_op.create_foreign_key(
            "fk_links_channel_id_channels",
            "channels",
            ["channel_id"],
            ["channel_id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("invite_cache", recreate="always") as batch_op:
        batch_op.alter_column("channel_id", existing_type=sa.BigInteger(), nullable=True)
        batch_op.create_foreign_key(
            "fk_invite_cache_channel_id_channels",
            "channels",
            ["channel_id"],
            ["channel_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("links", recreate="always") as batch_op:
        batch_op.alter_column("channel_id", existing_type=sa.BigInteger(), nullable=True)
        batch_op.create_foreign_key(
            "fk_links_channel_id_channels",
            "channels",
            ["channel_id"],
            ["channel_id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("invite_cache", recreate="always") as batch_op:
        batch_op.alter_column("channel_id", existing_type=sa.BigInteger(), nullable=True)
        batch_op.create_foreign_key(
            "fk_invite_cache_channel_id_channels",
            "channels",
            ["channel_id"],
            ["channel_id"],
            ondelete="SET NULL",
        )
