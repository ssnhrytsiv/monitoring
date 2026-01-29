"""add title to watch_posts

Revision ID: 20260312_000000_add_title_to_watch_posts
Revises: 20260309_010000_add_owner_display_to_link_queue
Create Date: 2026-03-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260312_000000_add_title_to_watch_posts"
down_revision = "20260309_010000_add_owner_display_to_link_queue"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("watch_posts", sa.Column("title", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("watch_posts", "title")
