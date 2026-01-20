"""add owner_admin_id to links

Revision ID: 20260305_010200
Revises: 20260304_010100
Create Date: 2026-03-05 01:02:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260305_010200"
down_revision = "20260304_010100"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    cols = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(links)")).fetchall()]
    if "owner_admin_id" not in cols:
        with op.batch_alter_table("links") as batch:
            batch.add_column(sa.Column("owner_admin_id", sa.Integer(), nullable=True))


def downgrade():
    conn = op.get_bind()
    cols = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(links)")).fetchall()]
    if "owner_admin_id" in cols:
        with op.batch_alter_table("links") as batch:
            batch.drop_column("owner_admin_id")
