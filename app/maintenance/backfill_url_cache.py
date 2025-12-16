import logging
from typing import Optional, Set, Tuple, Iterable

from app.services import channel_db
from app.services import membership_db


log = logging.getLogger("backfill_url_cache")

# Статуси, які нас цікавлять у url_cache
FINAL_STATUSES = {"joined", "already", "requested", "invalid", "private"}


def iter_all_links() -> Iterable[Tuple[Optional[int], str]]:
    """
    Ітерує всі записані посилання в channel_db.links.
    Повертає (channel_id, raw_url).
    """
    conn = channel_db.raw_connection()
    # якщо не хочеш лізти в приватний _lock — можна обійтись і без нього,
    # але тоді краще запускати утиліту, коли основний код не пише в БД.
    try:
        lock = channel_db._lock  # type: ignore[attr-defined]
    except Exception:
        lock = None

    if lock is not None:
        lock.__enter__()  # type: ignore
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, raw_url
            FROM links
            WHERE raw_url IS NOT NULL AND raw_url <> ''
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall()
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)  # type: ignore

    for cid, url in rows:
        yield cid, url


def decide_status(channel_id: Optional[int]) -> Optional[str]:
    """
    Визначає фінальний статус каналу через membership_db.any_final_for_channel.
    Повертає один із FINAL_STATUSES або None.
    """
    if channel_id is None:
        return None
    try:
        final = membership_db.any_final_for_channel(int(channel_id))
    except Exception as e:
        log.debug("any_final_for_channel(%s) failed: %s", channel_id, e)
        return None
    if final in FINAL_STATUSES:
        return final
    return None


def backfill_url_cache(dry_run: bool = False) -> None:
    """
    Проходить по всіх URL у channel_db.links і заповнює url_cache для тих,
    де кешу ще немає, але є фінальний статус по каналу в membership_db.
    """
    channel_db.init()


    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    processed = 0
    updated = 0
    skipped_has_cache = 0
    skipped_no_status = 0

    seen_urls: Set[str] = set()

    for channel_id, url in iter_all_links():
        if not url:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        processed += 1

        current = membership_db.url_get(url)
        if current in FINAL_STATUSES:
            skipped_has_cache += 1
            continue

        status = decide_status(channel_id)
        if not status:
            skipped_no_status += 1
            log.debug("skip url=%s cid=%s (no final status)", url, channel_id)
            continue

        log.info("backfill url=%s cid=%s status=%s (prev=%s)", url, channel_id, status, current)
        if not dry_run:
            try:
                membership_db.url_put(url, status)
                updated += 1
            except Exception as e:
                log.error("url_put failed for url=%s: %s", url, e)

    log.info(
        "backfill_url_cache done: processed=%d updated=%d "
        "skipped_has_cache=%d skipped_no_status=%d unique_urls=%d",
        processed, updated, skipped_has_cache, skipped_no_status, len(seen_urls),
    )


if __name__ == "__main__":
    # Перший запуск можна зробити з dry_run=True, щоб подивитися, що він збирається міняти.
    backfill_url_cache(dry_run=False)