"""Add admin/network refs and ad snapshot fields

Revision ID: 20240229_010101
Revises: None
Create Date: 2024-02-29 01:01:01
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20240229_010101"
down_revision = None
branch_labels = None
depends_on = None


def _has_column(conn, table: str, column: str) -> bool:
    insp = sa.inspect(conn)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
        if column in cols:
            return True
    except Exception:
        pass
    res = conn.execute(
        sa.text("SELECT 1 FROM pragma_table_info(:t) WHERE name = :c"),
        {"t": table, "c": column},
    )
    return res.scalar() is not None


def _has_index(conn, table: str, name: str) -> bool:
    res = conn.execute(
        sa.text("SELECT 1 FROM pragma_index_list(:t) WHERE name = :n"),
        {"t": table, "n": name},
    )
    return res.scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    wg_missing = []
    for col, typ in (("admin_id", sa.Integer()), ("network_id", sa.Integer())):
        if not _has_column(conn, "watch_groups", col):
            wg_missing.append(sa.Column(col, typ, nullable=True))
    if wg_missing:
        with op.batch_alter_table("watch_groups") as batch:
            for col in wg_missing:
                try:
                    batch.add_column(col)
                except Exception:
                    pass

    wp_missing = []
    for col, typ in (
        ("admin_id", sa.Integer()),
        ("network_id", sa.Integer()),
        ("posted_at", sa.Text()),
        ("views_at_post", sa.Integer()),
        ("subs_at_post", sa.Integer()),
        ("cpm_at_post", sa.Float()),
        ("price_at_post", sa.Float()),
    ):
        if not _has_column(conn, "watch_posts", col):
            wp_missing.append(sa.Column(col, typ, nullable=True))
    if wp_missing:
        with op.batch_alter_table("watch_posts") as batch:
            for col in wp_missing:
                try:
                    batch.add_column(col)
                except Exception:
                    pass

    if not _has_index(conn, "watch_posts", "idx_wp_posted_at"):
        op.create_index("idx_wp_posted_at", "watch_posts", ["posted_at"], unique=False)
    if not _has_index(conn, "watch_posts", "idx_wp_admin"):
        op.create_index("idx_wp_admin", "watch_posts", ["admin_id"], unique=False)
    if not _has_index(conn, "watch_posts", "idx_wp_network"):
        op.create_index("idx_wp_network", "watch_posts", ["network_id"], unique=False)
    if not _has_index(conn, "watch_groups", "idx_wg_admin"):
        op.create_index("idx_wg_admin", "watch_groups", ["admin_id"], unique=False)
    if not _has_index(conn, "watch_groups", "idx_wg_network"):
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
