"""add owner_display to link_queue

Revision ID: 20260309_010000
Revises: 20260305_130000_add_link_cache_table
Create Date: 2026-03-09 01:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260309_010000_add_owner_display_to_link_queue"
down_revision = "add_sort_order_to_network_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("link_queue")]
    if "owner_display" not in cols:
        op.add_column("link_queue", sa.Column("owner_display", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("link_queue", "owner_display")
