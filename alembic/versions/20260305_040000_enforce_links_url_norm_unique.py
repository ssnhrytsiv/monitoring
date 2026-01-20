"""
Deduplicate links.url_norm and add unique constraint.

Revision ID: 20260305_040000_enforce_links_url_norm_unique
Revises: 20260305_030500
Create Date: 2026-03-05 04:00:00.000000
"""
from __future__ import annotations

from typing import Optional

from alembic import op
import sqlalchemy as sa

from app.utils.link_parser import sanitize_link

# revision identifiers, used by Alembic.
revision = "20260305_040000_enforce_links_url_norm_unique"
down_revision = "20260305_030500"
branch_labels = None
depends_on = None


def _normalize(raw_url: Optional[str]) -> Optional[str]:
    if not raw_url:
        return None
    try:
        norm = sanitize_link(raw_url) or raw_url
    except Exception:
        norm = raw_url
    norm = str(norm).strip()
    return norm or None


def upgrade() -> None:
    conn = op.get_bind()

    # Доповнюємо url_norm для рядків, що залишились без значення
    rows = conn.execute(sa.text("SELECT id, raw_url FROM links WHERE url_norm IS NULL OR url_norm = ''"))
    for row in rows:
        norm = _normalize(row.raw_url)
        if norm:
            conn.execute(sa.text("UPDATE links SET url_norm = :norm WHERE id = :id"), {"norm": norm, "id": row.id})

    # Видаляємо дублікати: залишаємо найстаріший запис для кожного url_norm
    conn.execute(
        sa.text(
            """
            DELETE FROM links
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (PARTITION BY url_norm ORDER BY id) AS rn
                    FROM links
                    WHERE url_norm IS NOT NULL
                ) tmp
                WHERE rn > 1
            )
            """
        )
    )

    # Унікальність нормалізованих URL
    # SQLite не підтримує ALTER TABLE ADD CONSTRAINT, тому використовуємо batch_alter_table
    with op.batch_alter_table("links", recreate="always") as batch:
        batch.create_unique_constraint("uq_links_url_norm", ["url_norm"])


def downgrade() -> None:
    with op.batch_alter_table("links", recreate="always") as batch:
        batch.drop_constraint("uq_links_url_norm", type_="unique")
