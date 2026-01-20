"""
Drop legacy owner_display columns

Revision ID: 20260305_010101
Revises: 20260304_010100
Create Date: 2026-03-05 01:01:01
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260305_010101"
down_revision = "20260304_010100"
branch_labels = None
depends_on = None


TABLES = [
    "channels",
    "links",
    "link_queue",
    "invite_owners",
    "bot_links",
]


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    conn.execute(sa.text("DROP VIEW IF EXISTS membership_with_title"))
    # drop temp tables and indexes that reference owner_display
    for tbl in TABLES:
        conn.execute(sa.text(f"DROP TABLE IF EXISTS _alembic_tmp_{tbl}"))
        indexes = conn.execute(sa.text(f"PRAGMA index_list({tbl})")).fetchall()
        for idx in indexes:
            idx_name = idx[1]
            cols = {row[2] for row in conn.execute(sa.text(f"PRAGMA index_info({idx_name})")).fetchall()}
            if "owner_display" in cols:
                conn.execute(sa.text(f"DROP INDEX IF EXISTS {idx_name}"))
    for tbl in TABLES:
        cols = {c["name"] for c in insp.get_columns(tbl)}
        if "owner_display" not in cols:
            continue
        with op.batch_alter_table(tbl) as batch_op:
            batch_op.drop_column("owner_display")
    # recreate view without owner_display
    conn.execute(
        sa.text(
            """
            CREATE VIEW IF NOT EXISTS membership_with_title AS
            SELECT
                m.account,
                m.channel_id,
                m.status,
                m.ts,
                c.username,
                c.title,
                c.owner_admin_id,
                a.display AS owner_display,
                c.owner_username
            FROM membership AS m
            LEFT JOIN channels AS c ON c.channel_id = m.channel_id
            LEFT JOIN admins AS a ON a.id = c.owner_admin_id;
            """
        )
    )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    conn.execute(sa.text("DROP VIEW IF EXISTS membership_with_title"))
    for tbl in TABLES:
        cols = {c["name"] for c in insp.get_columns(tbl)}
        if "owner_display" in cols:
            continue
        with op.batch_alter_table(tbl) as batch_op:
            batch_op.add_column(sa.Column("owner_display", sa.Text()))
    # recreate legacy view with owner_display column
    conn.execute(
        sa.text(
            """
            CREATE VIEW IF NOT EXISTS membership_with_title AS
            SELECT
                m.account,
                m.channel_id,
                m.status,
                m.ts,
                c.username,
                c.title,
                c.owner_display,
                c.owner_username
            FROM membership AS m
            LEFT JOIN channels AS c ON c.channel_id = m.channel_id;
            """
        )
    )
