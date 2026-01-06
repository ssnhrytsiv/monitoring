"""Add admin/network refs and ad snapshot fields

Revision ID: 20240229_010101
Revises: None
Create Date: 2024-02-29 01:01:01
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20240229_010101"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("watch_groups") as batch:
        batch.add_column(sa.Column("admin_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("network_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("watch_posts") as batch:
        batch.add_column(sa.Column("admin_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("network_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("posted_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("views_at_post", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("subs_at_post", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cpm_at_post", sa.Float(), nullable=True))
        batch.add_column(sa.Column("price_at_post", sa.Float(), nullable=True))

    op.create_index("idx_wp_posted_at", "watch_posts", ["posted_at"], unique=False)
    op.create_index("idx_wp_admin", "watch_posts", ["admin_id"], unique=False)
    op.create_index("idx_wp_network", "watch_posts", ["network_id"], unique=False)
    op.create_index("idx_wg_admin", "watch_groups", ["admin_id"], unique=False)
    op.create_index("idx_wg_network", "watch_groups", ["network_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_wg_network", table_name="watch_groups")
    op.drop_index("idx_wg_admin", table_name="watch_groups")
    op.drop_index("idx_wp_network", table_name="watch_posts")
    op.drop_index("idx_wp_admin", table_name="watch_posts")
    op.drop_index("idx_wp_posted_at", table_name="watch_posts")

    with op.batch_alter_table("watch_posts") as batch:
        batch.drop_column("price_at_post")
        batch.drop_column("cpm_at_post")
        batch.drop_column("subs_at_post")
        batch.drop_column("views_at_post")
        batch.drop_column("posted_at")
        batch.drop_column("network_id")
        batch.drop_column("admin_id")

    with op.batch_alter_table("watch_groups") as batch:
        batch.drop_column("network_id")
        batch.drop_column("admin_id")
