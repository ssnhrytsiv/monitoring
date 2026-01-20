"""add owner_admin_id to channels and unique channel owner

Revision ID: 20260304_000001
Revises: 3a1b9c7d5e8f
Create Date: 2026-03-04 00:00:01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = "20260304_000001"
down_revision = "3a1b9c7d5e8f"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    res = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    )
    return res.scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # 1) owner_admin_id on channels
    if _table_exists(conn, "channels"):
        with op.batch_alter_table("channels") as batch:
            batch.add_column(sa.Column("owner_admin_id", sa.Integer(), nullable=True))
        # backfill from admin_channels if present
        if _table_exists(conn, "admin_channels"):
            conn.execute(
                text(
                    """
                    UPDATE channels
                    SET owner_admin_id = (
                        SELECT admin_id
                        FROM admin_channels ac
                        WHERE ac.channel_id = channels.channel_id
                        ORDER BY ac.id DESC
                        LIMIT 1
                    )
                    WHERE owner_admin_id IS NULL
                    """
                )
            )
    # 2) unique channel_id in admin_channels
    if _table_exists(conn, "admin_channels"):
        conn.execute(
            text(
                """
                DELETE FROM admin_channels
                WHERE id NOT IN (
                    SELECT MAX(id) FROM admin_channels GROUP BY channel_id
                )
                """
            )
        )
        with op.batch_alter_table("admin_channels") as batch:
            batch.create_unique_constraint("uq_admin_channels_channel", ["channel_id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("admin_channels") as batch:
            batch.drop_constraint("uq_admin_channels_channel", type_="unique")
        with op.batch_alter_table("channels") as batch:
            batch.drop_column("owner_admin_id")
    else:
        op.drop_constraint("uq_admin_channels_channel", "admin_channels", type_="unique")
        op.drop_column("channels", "owner_admin_id")
