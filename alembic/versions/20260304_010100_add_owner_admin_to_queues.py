"""Add owner_admin_id to queues/bots/invites

Revision ID: 20260304_010100
Revises: 20260304_000001
Create Date: 2026-03-04 01:01:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = "20260304_010100"
down_revision = "20260304_000001"
branch_labels = None
depends_on = None


def _has_column(conn, table: str, column: str) -> bool:
    try:
        insp = sa.inspect(conn)
        cols = [c["name"] for c in insp.get_columns(table)]
        if column in cols:
            return True
    except Exception:
        pass
    res = conn.execute(
        text("SELECT 1 FROM pragma_table_info(:t) WHERE name = :c"),
        {"t": table, "c": column},
    )
    return res.scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    for table in ("link_queue", "bot_links", "invite_owners"):
        if not _has_column(conn, table, "owner_admin_id"):
            try:
                op.add_column(table, sa.Column("owner_admin_id", sa.Integer(), nullable=True))
            except Exception:
                pass


def downgrade() -> None:
    for table in ("link_queue", "bot_links", "invite_owners"):
        try:
            op.drop_column(table, "owner_admin_id")
        except Exception:
            pass
