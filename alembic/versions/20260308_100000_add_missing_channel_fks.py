"""Add missing FKs and unify channel id types

Revision ID: 20260308_100000
Revises: 20260308_090000
Create Date: 2026-03-08 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_100000"
down_revision = "20260308_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # networks.admin_id -> admins.id (cascade)
    op.execute(
        """
        UPDATE networks
        SET admin_id = NULL
        WHERE admin_id IS NOT NULL
          AND admin_id NOT IN (SELECT id FROM admins)
        """
    )
    with op.batch_alter_table("networks", recreate="always") as batch_op:
        batch_op.create_foreign_key(
            "fk_networks_admin_id_admins",
            "admins",
            ["admin_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # link_queue.owner_admin_id -> admins.id (cascade)
    op.execute(
        """
        UPDATE link_queue
        SET owner_admin_id = NULL
        WHERE owner_admin_id IS NOT NULL
          AND owner_admin_id NOT IN (SELECT id FROM admins)
        """
    )
    with op.batch_alter_table("link_queue", recreate="always") as batch_op:
        batch_op.create_foreign_key(
            "fk_link_queue_owner_admin_id_admins",
            "admins",
            ["owner_admin_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # network_channels: add FKs, change channel_id to BigInteger
    op.execute(
        """
        DELETE FROM network_channels
        WHERE network_id NOT IN (SELECT id FROM networks)
           OR channel_id NOT IN (SELECT channel_id FROM channels)
        """
    )
    with op.batch_alter_table("network_channels", recreate="always") as batch_op:
        batch_op.alter_column(
            "channel_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_network_channels_network_id_networks",
            "networks",
            ["network_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_network_channels_channel_id_channels",
            "channels",
            ["channel_id"],
            ["channel_id"],
            ondelete="CASCADE",
        )

    # requested_check: channel_id -> BigInteger + FK to channels
    op.execute(
        """
        DELETE FROM requested_check
        WHERE channel_id NOT IN (SELECT channel_id FROM channels)
        """
    )
    with op.batch_alter_table("requested_check", recreate="always") as batch_op:
        batch_op.alter_column(
            "channel_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_requested_check_channel_id_channels",
            "channels",
            ["channel_id"],
            ["channel_id"],
            ondelete="CASCADE",
        )

    # owner_conflicts.channel_id -> BigInteger (no FK)
    with op.batch_alter_table("owner_conflicts", recreate="always") as batch_op:
        batch_op.alter_column(
            "channel_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("owner_conflicts", recreate="always") as batch_op:
        batch_op.alter_column(
            "channel_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            nullable=True,
        )

    with op.batch_alter_table("requested_check", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_requested_check_channel_id_channels", type_="foreignkey")
        batch_op.alter_column(
            "channel_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            nullable=False,
        )

    with op.batch_alter_table("network_channels", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_network_channels_channel_id_channels", type_="foreignkey")
        batch_op.drop_constraint("fk_network_channels_network_id_networks", type_="foreignkey")
        batch_op.alter_column(
            "channel_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            nullable=False,
        )

    with op.batch_alter_table("link_queue", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_link_queue_owner_admin_id_admins", type_="foreignkey")

    with op.batch_alter_table("networks", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_networks_admin_id_admins", type_="foreignkey")
