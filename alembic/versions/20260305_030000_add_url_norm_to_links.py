"""Add url_norm to links"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260305_030000"
down_revision = "20260305_020000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("links", sa.Column("url_norm", sa.Text(), nullable=True))
    op.create_index("ix_links_url_norm", "links", ["url_norm"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_links_url_norm", table_name="links")
    op.drop_column("links", "url_norm")
