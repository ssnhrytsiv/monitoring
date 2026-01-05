from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from zoneinfo import ZoneInfo
import asyncio

from telethon import events

from app.telethon_client import client as main_client  # базовий клієнт
from app.logging_json import get_logger
from app.utils.link_parser import extract_links, extract_links_any
from app.utils.tg_links import sanitize_link

from app.services.joiner import probe_channel_id
from app.services.membership_db import map_invite_get
from app.notificator_bot.db.posts_watch_result_db import create_watch, create_watch_group, raw_connection

try:
    from app.services.post_watch_db import list_templates_full
except Exception:
    from app.services import list_templates_full  # type: ignore

# ⬇️ Google Sheets writer (те, що ми тестували у REPL)
try:
    from app.sheet_bot.services.gsheets_writer import (
        create_or_get_daily_sheet,
        append_daily_row,
    )
    # Спробуємо також підтягнути HEADER, щоб адаптуватися під 8 або 9 колонок.
    try:
        from app.sheet_bot.services.gsheets_writer import HEADER as GS_HEADER  # type: ignore
    except Exception:
        GS_HEADER = None  # type: ignore
    _GS_OK = True
except Exception:
    create_or_get_daily_sheet = append_daily_row = None  # type: ignore
    GS_HEADER = None  # type: ignore
    _GS_OK = False

log = get_logger("plugin.monitor_watch")
_pylog = logging.getLogger("plugin.monitor_watch")

MOSCOW_TZ = ZoneInfo("Europe/Moscow")  # єдина TZ для цього плагіна


def _now_msq_str() -> str:
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _delta_minutes_msq_str(minutes: int) -> str:
    return (datetime.now(MOSCOW_TZ) + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _parse_window_spec(spec: str) -> Optional[int]:
    """
    Повертає кількість хвилин або None для 'none'.
    Допускає: '30m', '6h', '2d', просто число (вважається хвилинами).
    """
    s = (spec or "").strip().lower()
    if not s:
        return None
    if s in {"none", "no", "off"}:
        return None
    try:
        if s.endswith("m"):
            return max(1, int(s[:-1]))
        if s.endswith("h"):
            return max(1, int(float(s[:-1]) * 60))
        if s.endswith("d"):
            return max(1, int(float(s[:-1]) * 1440))
        return max(1, int(float(s)))
    except Exception:
        return None


async def _resolve_channel_id_from_link(url: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    url = sanitize_link(url) or url
    cid, title, kind, invite = await probe_channel_id(main_client, url)

    if cid:
        return int(cid), kind, invite

    if kind == "invite" and invite:
        try:
            cached_cid, _ = map_invite_get(invite)
            if cached_cid:
                return int(cached_cid), kind, invite
        except Exception:
            pass

    return None, kind, invite


def _has_active_duplicate(channel_id: int, template_id: Optional[int], expected_text_hash: Optional[str]) -> Optional[dict]:
    """
    Перевіряє, чи існує активний (pending|matched) моніторинг з тим самим ключем.
    Повертає словник з короткою інформацією або None.
    """
    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, status, created_at, time_window_end, matched_message_id
            FROM watch_posts
            WHERE channel_id = ?
              AND ((template_id IS NULL AND ? IS NULL) OR template_id = ?)
              AND ((expected_text_hash IS NULL AND ? IS NULL) OR expected_text_hash = ?)
              AND status IN ('pending','matched')
            ORDER BY id DESC
            LIMIT 1
            """,
            (channel_id, template_id, template_id, expected_text_hash, expected_text_hash),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "status": str(row[1]),
            "created_at": row[2],
            "time_window_end": row[3],
            "matched_message_id": row[4],
        }
    except Exception:
        _pylog.exception("duplicate check failed (cid=%s tpl=%s)", channel_id, template_id)
    return None


# ⬇️ Витяг метаданих каналу з БД (таблиця channels)
def _db_channel_meta(channel_id: int) -> Tuple[Optional[str], Optional[str]]:
    """
    Читає назву каналу та owner_display з таблиці channels.
    Повертає (title, owner_display) або (None, None), якщо немає запису.
    """
    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT title, owner_display FROM channels WHERE channel_id = ? LIMIT 1",
            (int(channel_id),),
        )
        row = cur.fetchone()
        if row:
            title = row[0] if row[0] else None
            owner = row[1] if row[1] else None
            return title, owner
    except Exception:
        _pylog.exception("channels lookup failed (cid=%s)", channel_id)
    return None, None


def setup(*, client=None, control_peer=None, monitor_buffer=None):
    """
    Команда:
      /watch_from_links <template_id> [--window-min N] [--window <spec>] [--project <ALI|PATRON|EXPRESS>]

    Де <spec> може бути:
      • 30m  — 30 хвилин
      • 6h   — 6 годин
      • 2d   — 2 доби
      • N    — хвилини
      • none — без дедлайну (не протухає)

    Посилання — у тілі повідомлення, кожне з нового рядка.
    """
    tg = client or main_client

    WINDOW_MIN_DEFAULT = 180  # 3h, лише якщо жоден window не вказаний

    @tg.on(events.NewMessage(pattern=r"^/watch_from_links(\s+|$)"))
    async def _(ev: events.NewMessage.Event):
        try:
            text = ev.raw_text.strip()
            parts = text.split()
            if len(parts) < 2:
                await ev.reply(
                    "❌ Формат: <code>/watch_from_links &lt;template_id&gt; "
                    "[--window-min N] [--window &lt;30m|6h|2d|none&gt;]</code>"
                )
                return

            template_id: Optional[int] = None
            window_minutes: Optional[int] = None  # None => безстроково (якщо взагалі не задано — беремо дефолт)
            project: Optional[str] = None

            i = 1
            while i < len(parts):
                p = parts[i]

                # --- новий універсальний прапор ---
                if p == "--window":
                    if i + 1 < len(parts):
                        wm = _parse_window_spec(parts[i + 1])
                        window_minutes = wm
                        i += 2
                        continue
                    else:
                        i += 1
                        continue
                if p.startswith("--window="):
                    wm = _parse_window_spec(p.split("=", 1)[1])
                    window_minutes = wm
                    i += 1
                    continue

                if p == "--project":
                    if i + 1 < len(parts):
                        project = parts[i + 1].strip()
                        i += 2
                        continue
                    else:
                        i += 1
                        continue
                if p.startswith("--project="):
                    project = p.split("=", 1)[1].strip()
                    i += 1
                    continue

                # --- бекворд-сов: старий прапор ---
                if p.startswith("--window-min"):
                    if "=" in p:
                        _, val = p.split("=", 1)
                        try:
                            window_minutes = max(1, int(val.strip()))
                        except Exception:
                            pass
                        i += 1
                        continue
                    else:
                        if i + 1 < len(parts):
                            try:
                                window_minutes = max(1, int(parts[i + 1].strip()))
                            except Exception:
                                pass
                            i += 2
                            continue
                        else:
                            i += 1
                            continue

                # --- template_id ---
                if template_id is None:
                    try:
                        template_id = int(p)
                    except Exception:
                        pass

                i += 1

            if not template_id:
                await ev.reply("❌ Не вказано <code>template_id</code>")
                return

            templates = list_templates_full(limit=200)
            tpl = next((t for t in templates if t[0] == template_id), None)
            if not tpl:
                log.warning("watch_from_links: template not found first try tpl=%s, retrying", template_id)
                await asyncio.sleep(0.3)
                templates = list_templates_full(limit=200)
                tpl = next((t for t in templates if t[0] == template_id), None)
                if not tpl:
                    await ev.reply(f"❌ Шаблон #{template_id} не знайдено (після retry)")
                    return

            tpl_id, tpl_html, tpl_mode, tpl_thr, created_at, tpl_title, tpl_links_json = tpl

            body = ev.raw_text.split("\n", 1)[1] if "\n" in ev.raw_text else ""
            raw_links = extract_links(body)
            ent_links = extract_links_any(ev.message)
            links: List[str] = []
            seen = set()
            for u in (raw_links + ent_links):
                su = sanitize_link(u) or u
                if su not in seen:
                    seen.add(su)
                    links.append(su)

            log.info(
                "watch_from_links: parsed cmd tpl=%s window_minutes=%s project=%s links=%s",
                template_id, window_minutes, project, len(links)
            )

            if not links:
                await ev.reply("❌ Не знайдено посилань у повідомленні (нижче команди).")
                return

            # якщо користувач не задав window — беремо дефолт у хвилинах
            if window_minutes is ...:  # на всяк випадок (не трапиться)
                window_minutes = None
            if window_minutes is None and "--window" not in text and "--window-min" not in text:
                window_minutes = WINDOW_MIN_DEFAULT

            created = 0
            duplicates: List[tuple[str, dict]] = []
            skipped = []

            # 🕒 ЄДИНИЙ час для всієї партії вотчів
            now_msq = datetime.now(MOSCOW_TZ)

            # Старт для всіх однаковий
            time_window_start = now_msq.strftime("%Y-%m-%d %H:%M:%S")

            # Дедлайн (може бути None для безстрокового моніторингу)
            if isinstance(window_minutes, int) and window_minutes > 0:
                tw_end_dt = now_msq + timedelta(minutes=int(window_minutes))
                # Нормалізуємо: секунда = 0, microsecond = 0
                tw_end_dt = tw_end_dt.replace(second=0, microsecond=0)
                time_window_end = tw_end_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                time_window_end = None

            # Група вотчів для цього запиту (щоб потім відобразити pending у нотіфікаторі)
            group_id = None
            try:
                group_id = create_watch_group(
                    project=project,
                    title=tpl_title,
                    created_by=getattr(ev, "sender_id", None),
                    created_via="control_chat",
                )
            except Exception:
                log.warning("watch_from_links: create_watch_group failed", exc_info=True)

            for url in links:
                try:
                    cid, kind, inv = await _resolve_channel_id_from_link(url)
                    if not cid:
                        skipped.append((url, kind or "?", inv or "?"))
                        continue

                    # ---- ПЕРЕВІРКА НА ДУБЛЬ ----
                    dup = _has_active_duplicate(cid, template_id, tpl_html)
                    if dup:
                        duplicates.append((url, dup))
                        log.info(
                            "watch_from_links: duplicate skipped url=%s cid=%s tpl=%s wid=%s status=%s",
                            url, cid, template_id, dup.get("id"), dup.get("status")
                        )
                        continue

                    # --- створення watch (з підтримкою нового аргументу source_url, але без ламання старої сигнатури) ---
                    try:
                        wid = create_watch(
                            channel_id=cid,
                            template_id=template_id,
                            expected_text_hash=tpl_html,  # HTML шаблону
                            expected_text_norm_len=len(tpl_html or ""),
                            expected_links_json=tpl_links_json,
                            expected_media_fingerprint=None,
                            time_window_start=time_window_start,
                            time_window_end=time_window_end,
                            source_url=url,  # нове поле (лише якщо воно вже є)
                            project=project,
                            group_id=group_id,
                        )
                    except TypeError:
                        # стара сигнатура без source_url/group_id
                        wid = create_watch(
                            channel_id=cid,
                            template_id=template_id,
                            expected_text_hash=tpl_html,
                            expected_text_norm_len=len(tpl_html or ""),
                            expected_links_json=tpl_links_json,
                            expected_media_fingerprint=None,
                            time_window_start=time_window_start,
                            time_window_end=time_window_end,
                        )
                    created += 1
                    log.info(
                        "watch_from_links: watch_id=%s created for cid=%s url=%s window_end=%s project=%s",
                        wid, cid, url, time_window_end, project
                    )

                    # -------- Google Sheets: запис у денний аркуш (на моменті створення) --------
                    if _GS_OK and create_or_get_daily_sheet and append_daily_row:
                        try:
                            # 1) дата аркуша — день старту вікна
                            date_str = (time_window_start or "")[:10] or datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
                            create_or_get_daily_sheet(date_str)

                            # 2) назва поста з шаблону (або #id)
                            post_name = tpl_title or f"#{template_id}"

                            # 3) перетворення links JSON -> багаторядковий текст
                            links_text = ""
                            try:
                                if tpl_links_json:
                                    import json as _json
                                    arr = _json.loads(tpl_links_json)
                                    if isinstance(arr, list):
                                        links_text = "\n".join(str(x) for x in arr if x)
                                    else:
                                        links_text = str(arr)
                            except Exception:
                                links_text = tpl_links_json or ""

                            # 4) назва каналу + адмін з таблиці channels
                            ch_title, owner_display = _db_channel_meta(cid)
                            ch_title = ch_title or ""  # якщо не знайшли — лишаємо порожньо
                            owner_display = owner_display or ""

                            # 5) формуємо рядок під поточну версію HEADER:
                            #    - якщо 9 колонок і B == "Посилання на канал" -> новий формат (A..I)
                            #    - інакше -> легасі (A..H) як було.
                            use_new_header = False
                            if isinstance(GS_HEADER, list) and len(GS_HEADER) == 9:
                                try:
                                    use_new_header = (GS_HEADER[1].strip().lower() == "посилання на канал")
                                except Exception:
                                    use_new_header = True

                            if use_new_header:
                                # Новий порядок A..I:
                                # A Назва каналу
                                # B Посилання на канал (source_url)
                                # C Дата виходу і час
                                # D Перегляди
                                # E Дата видалення і час
                                # F Назва поста
                                # G Посилання
                                # H Адмін
                                # I Watch ID
                                row_vals = [
                                    ch_title,  # A
                                    url,  # B (source_url)
                                    "",  # C (PostedAt — заповниться при MATCH)
                                    "",  # D (Views)
                                    "",  # E (DeletedAt)
                                    post_name,  # F
                                    links_text,  # G
                                    owner_display,  # H
                                    wid,  # I
                                ]
                            else:
                                # Легасі A..H (повністю як було):
                                # A Назва каналу
                                # B Назва поста
                                # C Посилання
                                # D Дата виходу і час
                                # E Перегляди
                                # F Дата видалення і час
                                # G Адмін (owner_display)
                                # H Watch ID
                                row_vals = [
                                    ch_title,  # A
                                    post_name,  # B
                                    links_text,  # C
                                    "",  # D
                                    "",  # E
                                    "",  # F
                                    owner_display,  # G
                                    wid,  # H
                                ]

                            append_daily_row(date_str, row_vals)
                            log.debug(
                                "gsheets: initial row appended (date=%s wid=%s cols=%s A..?=%r)",
                                date_str, wid, len(row_vals), row_vals
                            )
                        except Exception:
                            _pylog.exception("gsheets: initial append failed (wid=%s)", wid)
                    # ---------------------------------------------------------------------------

                except Exception:
                    _pylog.exception("watch_from_links: failed for url=%s", url)

            # --- Формуємо відповідь ---
            msg = [f"✅ Створено задач: {created}"]
            if window_minutes is None:
                msg.append("🕒 Вікно: безстроково (expire не застосовується)")
            else:
                msg.append(f"🕒 Вікно: {window_minutes} хв (час: Europe/Moscow)")

            if duplicates:
                msg.append(f"⚠️ Пропущено як дубль: {len(duplicates)}")
                for url, dup in duplicates[:10]:
                    wid = dup.get("id")
                    st = dup.get("status")
                    tw = dup.get("time_window_end")
                    msg.append(f" – {url} (існує wid={wid}, status={st}, window_end={tw})")
                if len(duplicates) > 10:
                    msg.append(f" …і ще {len(duplicates) - 10}")

            if skipped:
                msg.append(f"⚠️ Пропущено (без channel_id у кеші): {len(skipped)}")
                for (u, k, inv) in skipped[:10]:
                    msg.append(f" – {u} (kind={k}, invite={inv})")
                if len(skipped) > 10:
                    msg.append(f" …і ще {len(skipped) - 10}")

            await ev.reply("\n".join(msg))
        except Exception:
            _pylog.exception("watch_from_links: handler error")
            await ev.reply("❌ Внутрішня помилка під час створення задач.")
