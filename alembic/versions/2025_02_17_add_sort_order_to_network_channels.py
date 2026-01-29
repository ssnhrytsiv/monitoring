"""
Add sort_order to network_channels
"""

from alembic import op
import sqlalchemy as sa


revision = "add_sort_order_to_network_channels"
down_revision = "3a1b9c7d5e8f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("network_channels", sa.Column("sort_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("network_channels", "sort_order")
