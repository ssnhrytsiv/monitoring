#!/usr/bin/env python3
"""
Видаляє задані інвайт-лінки/хеші з усіх дотичних таблиць SQLite.
За замовчуванням бере відомі "сирітні" інвайти:
  - https://t.me/+Ilrl0h5mA_9kNDli
  - https://t.me/+mk0UQztiaWczNzI0
  - https://t.me/+16H4h3EieSQ4YmQ6
  - https://t.me/+ngxF-XaaoA02MmI0
  - https://t.me/+wEbo8Vekpeo5MzVi
  - https://t.me/+YluwNEsaCfc1NzY6
  - https://t.me/+CV70e-cmC91iMGE0
  - https://t.me/+pWpfyiFhhT9lYThi

Чистить таблиці: url_cache, invite_status, invite_map, invite_owners (якщо є),
link_queue, links, membership, admin_channels, network_channels,
owner_conflicts, channel_links/subscriptions (якщо існують), channels.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from typing import Iterable, List, Set, Tuple

from dotenv import load_dotenv

DEFAULT_URLS = [
    "https://t.me/+Ilrl0h5mA_9kNDli",
    "https://t.me/+mk0UQztiaWczNzI0",
    "https://t.me/+16H4h3EieSQ4YmQ6",
    "https://t.me/+ngxF-XaaoA02MmI0",
    "https://t.me/+wEbo8Vekpeo5MzVi",
    "https://t.me/+YluwNEsaCfc1NzY6",
    "https://t.me/+CV70e-cmC91iMGE0",
    "https://t.me/+pWpfyiFhhT9lYThi",
]


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;", (name,))
    return cur.fetchone() is not None


def normalize_hash(inv_or_url: str) -> str | None:
    if not inv_or_url:
        return None
    s = inv_or_url.replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()
    try:
        if "/+" in s:
            return s.rsplit("/", 1)[-1].replace("+", "").strip()
        if "joinchat/" in s:
            return s.rsplit("joinchat/", 1)[-1].strip()
        if "/" not in s and " " not in s:
            return s
    except Exception:
        return None
    return None


def url_variants(url: str) -> List[str]:
    """Повертає https://t.me/+... та https://t.me/joinchat/... варіанти для одного хешу/URL."""
    h = normalize_hash(url)
    if not h:
        return []
    return [
        f"https://t.me/+{h}",
        f"https://t.me/joinchat/{h}",
    ]


def collect_sets(raw_urls: Iterable[str], raw_hashes: Iterable[str]) -> Tuple[List[str], List[str]]:
    urls: Set[str] = set()
    hashes: Set[str] = set()
    for u in raw_urls:
        if not u:
            continue
        for v in url_variants(u):
            urls.add(v)
        h = normalize_hash(u)
        if h:
            hashes.add(h)
    for h in raw_hashes:
        n = normalize_hash(h)
        if n:
            hashes.add(n)
            urls.update(url_variants(n))
    return sorted(urls), sorted(hashes)


def fetch_channel_ids(conn: sqlite3.Connection, urls: List[str], hashes: List[str]) -> List[int]:
    ids: Set[int] = set()
    if table_exists(conn, "links") and urls:
        q = "SELECT DISTINCT channel_id FROM links WHERE raw_url IN ({})".format(",".join("?" * len(urls)))
        for row in conn.execute(q, urls):
            if row[0] is not None:
                ids.add(int(row[0]))
    if table_exists(conn, "invite_map") and hashes:
        q = "SELECT DISTINCT channel_id FROM invite_map WHERE invite_hash IN ({})".format(",".join("?" * len(hashes)))
        for row in conn.execute(q, hashes):
            if row[0] is not None:
                ids.add(int(row[0]))
    return sorted(ids)


def delete_in(conn: sqlite3.Connection, table: str, column: str, values: List) -> int:
    if not values or not table_exists(conn, table):
        return 0
    placeholders = ",".join("?" * len(values))
    cur = conn.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", values)
    return cur.rowcount


def cleanup(db_path: Path, urls: List[str], hashes: List[str]) -> dict:
    if not urls and not hashes:
        return {}
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=3000;")
    try:
        urls, hashes = collect_sets(urls, hashes)
        channel_ids = fetch_channel_ids(conn, urls, hashes)

        res = {}
        # URL-based tables
        res["url_cache"] = delete_in(conn, "url_cache", "url", urls)
        res["link_queue"] = delete_in(conn, "link_queue", "url", urls)
        res["links"] = delete_in(conn, "links", "raw_url", urls)

        # Invite-hash tables
        res["invite_status"] = delete_in(conn, "invite_status", "invite_hash", hashes)
        res["invite_map"] = delete_in(conn, "invite_map", "invite_hash", hashes)
        res["invite_owners"] = delete_in(conn, "invite_owners", "invite_hash", hashes)

        # Channel-id tables
        res["membership"] = delete_in(conn, "membership", "channel_id", channel_ids)
        res["admin_channels"] = delete_in(conn, "admin_channels", "channel_id", channel_ids)
        res["network_channels"] = delete_in(conn, "network_channels", "channel_id", channel_ids)
        res["owner_conflicts"] = delete_in(conn, "owner_conflicts", "channel_id", channel_ids)
        res["channel_links"] = delete_in(conn, "channel_links", "channel_id", channel_ids)
        res["subscriptions"] = delete_in(conn, "subscriptions", "channel_id", channel_ids)

        # Channels last (прибираємо самі канали)
        res["channels"] = delete_in(conn, "channels", "channel_id", channel_ids)

        conn.commit()
        res["channel_ids_used"] = channel_ids
        res["urls_used"] = urls
        res["hashes_used"] = hashes
        return res
    finally:
        conn.close()


def main() -> None:
    load_dotenv()
    load_dotenv(".env.local", override=True)
    parser = argparse.ArgumentParser(description="Видалити задані інвайт-лінки/хеші з усіх таблиць SQLite.")
    parser.add_argument(
        "--db",
        default=os.getenv("DB_PATH", "post_watchdog.sqlite3"),
        help="Шлях до SQLite (default: post_watchdog.sqlite3 або DB_PATH).",
    )
    parser.add_argument(
        "--urls",
        nargs="*",
        default=None,
        help="Список URL для видалення. Якщо не задано — використає вбудований перелік.",
    )
    parser.add_argument(
        "--hashes",
        nargs="*",
        default=None,
        help="Додаткові invite-hash для видалення.",
    )
    args = parser.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB file not found: {db_path}")

    urls = args.urls if args.urls is not None else DEFAULT_URLS
    hashes = args.hashes if args.hashes is not None else []
    res = cleanup(db_path, urls, hashes)
    print("Done.")
    for k, v in res.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
