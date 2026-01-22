"""Add unified link_cache table"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260308_130000_add_link_cache_table"
down_revision = "20260308_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "link_cache",
        sa.Column("url_norm", sa.Text(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("session", sa.Text(), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), sa.ForeignKey("channels.channel_id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("join_time", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("kind in ('public','invite','bot')", name="ck_link_cache_kind"),
    )
    op.create_index("idx_link_cache_kind", "link_cache", ["kind"])
    op.create_index("idx_link_cache_join_time", "link_cache", ["join_time"])
    op.create_index("idx_link_cache_channel_id", "link_cache", ["channel_id"])


def downgrade() -> None:
    op.drop_index("idx_link_cache_channel_id", table_name="link_cache")
    op.drop_index("idx_link_cache_join_time", table_name="link_cache")
    op.drop_index("idx_link_cache_kind", table_name="link_cache")
    op.drop_table("link_cache")
