"""Backfill links.url_norm from raw_url"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260305_030500"
down_revision = "20260305_030000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    links = sa.table(
        "links",
        sa.column("id", sa.Integer),
        sa.column("raw_url", sa.Text),
        sa.column("url_norm", sa.Text),
    )

    # Спробуємо імпортувати ту ж функцію, що використовує код.
    try:
        from app.utils.link_parser import sanitize_link  # type: ignore
    except Exception:
        # Мінімальний резервний нормалізатор, якщо імпорт не вдався.
        import re
        from urllib.parse import urlsplit, urlunsplit

        def sanitize_link(u: str) -> str:  # type: ignore
            s = (u or "").strip()
            if not s:
                return s
            low = s.lower()
            if low.startswith("tg://resolve?domain="):
                name = s.split("=", 1)[-1].split("&", 1)[0].lstrip("@").strip()
                if name:
                    s = f"https://t.me/{name}"
                    low = s.lower()
            if s.startswith("@"):
                s = f"https://t.me/{s[1:].strip()}"
                low = s.lower()
            fixes = (("https//", "https://"), ("http//", "http://"), ("tps://", "https://"), ("htps://", "https://"))
            for bad, good in fixes:
                if s.startswith(bad):
                    s = good + s[len(bad) :]
                    low = s.lower()
                    break
            if low.startswith("t.me/"):
                s = "https://" + s
            m = re.match(r"^([a-zA-Z][a-zA-Z0-9+\\-.]*://)(.+)$", s)
            if m:
                scheme = m.group(1)
                rest = re.sub(r"^[a-zA-Z][a-zA-Z0-9+\\-.]*://", "", m.group(2))
                s = scheme + rest
            try:
                p = urlsplit(s)
            except Exception:
                return s
            if not p.scheme:
                s = "https://" + s.lstrip("/")
                p = urlsplit(s)
            if not p.netloc and p.path.startswith("t.me/"):
                s = "https://" + p.path
                p = urlsplit(s)
            if p.netloc.lower() == "t.me" and p.scheme != "https":
                p = p._replace(scheme="https")
            return urlunsplit(p)

    result = bind.execute(sa.select(links.c.id, links.c.raw_url).where(links.c.url_norm.is_(None)))
    rows = result.fetchall()
    for row_id, raw_url in rows:
        norm = None
        if raw_url:
            try:
                norm = sanitize_link(raw_url) or raw_url
            except Exception:
                norm = raw_url
            norm = (norm or "").strip() or None
        bind.execute(
            sa.update(links).where(links.c.id == row_id).values(url_norm=norm),
        )


def downgrade() -> None:
    # Просто обнуляємо url_norm, щоб повернути стан перед backfill.
    bind = op.get_bind()
    links = sa.table("links", sa.column("url_norm", sa.Text))
    bind.execute(sa.update(links).values(url_norm=None))
