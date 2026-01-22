"""Add FK on channels.owner_admin_id -> admins.id (CASCADE)

Revision ID: 20260308_090000
Revises: 20260308_080000
Create Date: 2026-03-08 09:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_090000"
down_revision = "20260308_080000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # очистити невалідні owner_admin_id
    op.execute(
        """
        UPDATE channels
        SET owner_admin_id = NULL
        WHERE owner_admin_id IS NOT NULL
          AND owner_admin_id NOT IN (SELECT id FROM admins)
        """
    )
    with op.batch_alter_table("channels", recreate="always") as batch_op:
        batch_op.alter_column("owner_admin_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key(
            "fk_channels_owner_admin_id_admins",
            "admins",
            ["owner_admin_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("channels", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_channels_owner_admin_id_admins", type_="foreignkey")
        batch_op.alter_column("owner_admin_id", existing_type=sa.Integer(), nullable=True)
