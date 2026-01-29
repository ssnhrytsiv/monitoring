"""create watch_post_templates table

Revision ID: 20260312_010000_create_watch_post_templates
Revises: 20260312_000000_add_title_to_watch_posts
Create Date: 2026-03-12 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260312_010000_create_watch_post_templates"
down_revision = "20260312_000000_add_title_to_watch_posts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "watch_post_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_table("watch_post_templates")
