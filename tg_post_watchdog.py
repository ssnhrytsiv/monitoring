# -*- coding: utf-8 -*-
import asyncio
import os
import re
from typing import Optional, List
import asyncio
import random




from telethon.tl.types import Message, MessageEntityUrl, MessageEntityTextUrl
try:
    from telethon.tl.types import PeerChannel, MessageFwdHeader
except Exception:  # fallback
    PeerChannel = None
    MessageFwdHeader = None

try:
    from telethon.errors.rpcerrorlist import FloodWaitError
except Exception:  # fallback
    class FloodWaitError(Exception):
        def __init__(self, seconds=30): self.seconds = seconds

import sqlite3
import random
import unicodedata
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple

from dotenv import load_dotenv
from telethon import TelegramClient, events
#from telethon.tl.types import Message, MessageEntityUrl, MessageEntityTextUrl
from telethon.errors import FloodWaitError, UserAlreadyParticipantError, InviteHashExpiredError, InviteHashInvalidError, ChannelPrivateError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from rapidfuzz import fuzz

# --- monitor input state ---
try:
    from types import SimpleNamespace
    MONITOR_BUFFER = SimpleNamespace(active=False)
except Exception:
    class _Buf:
        active = False
    MONITOR_BUFFER = _Buf()

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "tg_session")

CONTROL_CHAT = os.getenv("CONTROL_CHAT", "me")
REPORT_CHAT_ENV = os.getenv("REPORT_CHAT", "").strip()

DEFAULT_FIND_INTERVAL = os.getenv("DEFAULT_FIND_INTERVAL", "30m")
DEFAULT_MON_INTERVAL  = os.getenv("DEFAULT_MON_INTERVAL", "1h")
DEFAULT_FIND_WINDOW   = os.getenv("DEFAULT_FIND_WINDOW", "72h")
DEFAULT_MON_WINDOW    = os.getenv("DEFAULT_MON_WINDOW", "24h")

DEFAULT_MODE = os.getenv("DEFAULT_MODE", "exact_strict").lower()
DEFAULT_FUZZ = int(os.getenv("DEFAULT_FUZZ", "85"))
CASE_SENSITIVE = os.getenv("CASE_SENSITIVE", "false").lower() == "true"
WHOLE_WORD = os.getenv("WHOLE_WORD", "false").lower() == "true"

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

GSHEET_SPREADSHEET_ID = os.getenv("GSHEET_SPREADSHEET_ID", "").strip()
GSHEET_CREDS_FILE = os.getenv("GSHEET_CREDS_FILE", "service_account.json").strip()
GSHEET_JOBS_SHEET = os.getenv("GSHEET_JOBS_SHEET", "Jobs").strip()
GSHEET_SUMMARY_SHEET = os.getenv("GSHEET_SUMMARY_SHEET", "Summary").strip()


NEEDLE_TEXT: Optional[str] = None
NEEDLE_MODE: str = DEFAULT_MODE
NEEDLE_FUZZ: int = int(DEFAULT_FUZZ)

# ---------------- forwarded-message helpers ----------------
# ловимо https/http/tps/tp/ttp/www + t.me/telegram.me + username/c/<id>/msg/+invite
_TG_RE = re.compile(
    r'((?:https?://|tps://|tp://|ttp://|www\.)?'
    r'(?:t\.me|telegram\.me)'
    r'/(?:\+[\w-]+|[A-Za-z0-9_]+(?:/\d+)?|c/\d+(?:/\d+)?))',
    re.IGNORECASE
)






# ---------- helpers ----------
def parse_timedelta(s: str) -> timedelta:
    s = s.strip().lower()
    if s.endswith("m"): return timedelta(minutes=int(s[:-1]))
    if s.endswith("h"): return timedelta(hours=int(s[:-1]))
    if s.endswith("d"): return timedelta(days=int(s[:-1]))
    return timedelta(seconds=int(s))

def dt_utc() -> datetime:
    return datetime.utcnow().replace(tzinfo=None)

import re
import unicodedata

def strip_invisible(s: str) -> str:
    """Прибрати zero-width, BOM, привести переноси рядків."""
    if not s:
        return s
    for ch in ["\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"]:
        s = s.replace(ch, "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s

def normalize_strict(s: str) -> str:
    """Сувора нормалізація для точного порівняння."""
    if s is None:
        return ""
    s = strip_invisible(s)
    s = unicodedata.normalize("NFC", s)      # канонічна форма
    s = s.replace("\u00a0", " ")  # NBSP → звичайний пробіл
    # одинарні пробіли, прибрати пробіли на краях рядків
    s = "\n".join(line.strip() for line in s.split("\n"))
    s = re.sub(r"[ \t]+", " ", s)
    # стислий багаторазовий перенос
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def normalize_soft(s: str) -> str:
    """М’якша нормалізація (залишає форматування, але чистить сміття)."""
    s = normalize_strict(s)
    return s

# ------------------------------------------------------------
# Telegram links: canonicalization + robust extraction
# ------------------------------------------------------------

_TRIM_LEAD  = "(<[«\"' \u00A0\u200b\u200c\u200d\u2060"
_TRIM_TRAIL = ".,;:!?)]}>»\"' \u00A0\u200b\u200c\u200d\u2060"

def _fix_scheme(u: str) -> str:
    u = u.strip(_TRIM_LEAD + _TRIM_TRAIL)
    lu = u.lower()
    if lu.startswith("tps://"):   u = "h" + u
    elif lu.startswith("tp://"):  u = "ht" + u
    elif lu.startswith("ttp://"): u = "h" + u
    elif lu.startswith("www."):   u = "https://" + u
    elif lu.startswith("t.me") or lu.startswith("telegram.me"):
        u = "https://" + u
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u.lstrip("/")
    return u

def _canon(u: str) -> str:
    u = _fix_scheme(u)
    # telegram.me -> t.me
    u = re.sub(r'^(https?://)telegram\.me', r'\1t.me', u, flags=re.IGNORECASE)
    # joinchat -> +
    u = re.sub(r'/joinchat/', '/', u, flags=re.IGNORECASE)
    return u

def _sanitize_link(u: str) -> str:
    """Зрізає сміття по краях і лікує схему/домен."""
    u = (u or "").strip()
    # прибрати маркери/тире/дужки по краях
    u = u.strip(_TRIM_LEAD + _TRIM_TRAIL).lstrip("—–-•· ").strip()
    # привести до канону (https://, t.me, тощо)
    u = _canon(_fix_scheme(u))
    # ще раз зрізати випадкові символи після канонізації
    u = u.strip(_TRIM_LEAD + _TRIM_TRAIL)
    return u


def parse_telegram_links_from_text(text: str) -> list[str]:
    """Повертає унікальні канонічні t.me-посилання у порядку появи."""
    if not text:
        return []
    seen = {}
    for m in _TG_RE.finditer(text):
        raw = m.group(1)
        url = _canon(raw).strip(_TRIM_LEAD + _TRIM_TRAIL)
        seen[url] = None
    return list(seen.keys())

def collapse_ws(s: str) -> str:
    """Зводить усі пробіли/переноси до одного пробілу."""
    return re.sub(r"\s+", " ", s).strip()

def whole_word_pattern(p: str) -> str:
    if not WHOLE_WORD: return p
    return rf"(?<![A-Za-zА-Яа-я0-9_])(?:{p})(?![A-Za-zА-Яа-я0-9_])"

def match_text(text: str, needle: str, mode: str, fuzz_thresh: int) -> bool:
    if not text or not needle: return False
    if mode == "exact_strict":
        return collapse_ws(normalize_strict(text)) == collapse_ws(normalize_strict(needle))
    if mode == "exact_norm":
        a = collapse_ws(normalize_soft(text)); b = collapse_ws(normalize_soft(needle)); return a == b
    if mode == "regex":
        flags = 0 if CASE_SENSITIVE else re.IGNORECASE
        try: return re.search(whole_word_pattern(needle), text, flags=flags) is not None
        except re.error: return False
    a, b = (text, needle) if CASE_SENSITIVE else (text.lower(), needle.lower())
    return fuzz.partial_ratio(a, b) >= fuzz_thresh

_TME_LINK_RE = re.compile(r"(?:https?://)?t\.me/(?:joinchat/[\w-]+|\+[\w-]+|c/\d+/\d+|[\w_]+/\d+|[\w_]+)", re.IGNORECASE)
_TME_POST_RE = re.compile(r"(?:https?://)?t\.me/([\w_]+)/(\d+)", re.IGNORECASE)
_TME_POST_PRIVATE_RE = re.compile(r"(?:https?://)?t\.me/c/(\d+)/(\d+)", re.IGNORECASE)
_INVITE_HASH_RE = re.compile(r"(?:https?://)?t\.me/(?:\+|joinchat/)([A-Za-z0-9_-]+)", re.IGNORECASE)

from telethon.tl.types import Message, MessageEntityUrl, MessageEntityTextUrl
def extract_tme_links_from_text(text: str) -> List[str]:
    return list({m.group(0) for m in _TME_LINK_RE.finditer(text or "")})

def extract_hidden_links_from_entities(msg: Message) -> List[str]:
    urls = []
    if msg and msg.entities:
        for ent in msg.entities:
            if isinstance(ent, MessageEntityTextUrl) and ent.url:
                urls.append(ent.url)
            elif isinstance(ent, MessageEntityUrl):
                try:
                    start, end = ent.offset, ent.offset + ent.length
                    urls.append((msg.message or "")[start:end])
                except Exception: pass
    return [u for u in urls if "t.me" in (u or "")]

# ---------- Google Sheets (Jobs + Summary) ----------
class JobsSheet:
    HEADERS = ["Адмін","Subset","Канал","Посилання","JobID","Пост був випущений","MsgID","Дата посту","Перегляди 24","Переглядів загалом","Видалено о","Комент"]
    def __init__(self):
        self.enabled = False
        self.gc = None
        self.sh = None
        self.jobs_ws = None
        self.summary_ws = None
        if GSHEET_SPREADSHEET_ID and os.path.exists(GSHEET_CREDS_FILE):
            try:
                import gspread
                from oauth2client.service_account import ServiceAccountCredentials
                scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
                creds = ServiceAccountCredentials.from_json_keyfile_name(GSHEET_CREDS_FILE, scope)
                gc = gspread.authorize(creds)
                sh = gc.open_by_key(GSHEET_SPREADSHEET_ID)
                # Jobs
                try:
                    jobs_ws = sh.worksheet(GSHEET_JOBS_SHEET)
                except Exception:
                    jobs_ws = sh.add_worksheet(title=GSHEET_JOBS_SHEET, rows="2000", cols=str(len(self.HEADERS)+5))
                    jobs_ws.append_row(self.HEADERS, value_input_option="RAW")
                # Summary
                try:
                    summary_ws = sh.worksheet(GSHEET_SUMMARY_SHEET)
                except Exception:
                    summary_ws = sh.add_worksheet(title=GSHEET_SUMMARY_SHEET, rows="2000", cols="10")
                    summary_ws.append_row(["ID","Дата","Назва власника","Канали (всі посилання)","К-сть посилань","Перегляди (сума всіх)","Видалено вчасно"], value_input_option="RAW")

                self.enabled = True
                self.gc, self.sh = gc, sh
                self.jobs_ws = jobs_ws
                self.summary_ws = summary_ws
            except Exception as e:
                print(f"[GSHEET] init failed: {e}")

    # Jobs helpers
    def _jobs_find_row(self, job_id: int, link: str) -> Optional[int]:
        try:
            records = self.jobs_ws.get_all_records()
            for idx, r in enumerate(records, start=2):
                if str(r.get("JobID","")).strip() == str(job_id) and str(r.get("Посилання","")).strip() == str(link):
                    return idx
        except Exception: pass
        return None

    def jobs_upsert_base(self, admin: str, subset: str, channel_disp: str, link: str, job_id: int, comment: str = ""):
        if not self.enabled: return
        row_idx = self._jobs_find_row(job_id, link)
        base = [admin or "", subset or "", channel_disp or "", link or "", job_id, "", "", "", "", "", comment or ""]
        if row_idx:
            self.jobs_ws.update(
    values=[base],
    range_name=f"A{row_idx}:L{row_idx}",
    value_input_option="RAW",
)

        else:
            self.jobs_ws.append_row(base, value_input_option="RAW")

    def jobs_set_released(self, job_id: int, link: str, msg_id: int, published_iso: str, views_initial: int):
        if not self.enabled: return
        row_idx = self._jobs_find_row(job_id, link)
        if not row_idx:
            self.jobs_upsert_base("", "", "", link, job_id, "")
            row_idx = self._jobs_find_row(job_id, link)
        self.jobs_ws.update_cell(row_idx, 6, "Так")
        self.jobs_ws.update_cell(row_idx, 7, msg_id)
        self.jobs_ws.update_cell(row_idx, 8, published_iso or "")
        self.jobs_ws.update_cell(row_idx, 10, views_initial)

    def jobs_set_not_released(self, job_id: int, link: str):
        if not self.enabled: return
        row_idx = self._jobs_find_row(job_id, link)
        if not row_idx:
            self.jobs_upsert_base("", "", "", link, job_id, "")
            row_idx = self._jobs_find_row(job_id, link)
        self.jobs_ws.update_cell(row_idx, 6, "Ні")

    def jobs_set_views24(self, job_id: int, link: str, views24: int):
        if not self.enabled: return
        row_idx = self._jobs_find_row(job_id, link)
        if row_idx: self.jobs_ws.update_cell(row_idx, 9, views24)

    def jobs_set_views_max(self, job_id: int, link: str, max_views: int):
        if not self.enabled: return
        row_idx = self._jobs_find_row(job_id, link)
        if row_idx: self.jobs_ws.update_cell(row_idx, 10, max_views)

    def jobs_set_deleted(self, job_id: int, link: str, deleted_iso: str):
        if not self.enabled: return
        row_idx = self._jobs_find_row(job_id, link)
        if row_idx: self.jobs_ws.update_cell(row_idx, 11, deleted_iso)

    def jobs_append_comment(self, job_id: int, link: str, note: str):
        if not self.enabled: return
        row_idx = self._jobs_find_row(job_id, link)
        if row_idx:
            try: val = self.jobs_ws.cell(row_idx, 12).value or ""
            except Exception: val = ""
            new_val = (val + (" | " if val and note else "") + (note or "")).strip()
            self.jobs_ws.update_cell(row_idx, 12, new_val)

    # Summary
    def _summary_find_row(self, job_id: int) -> Optional[int]:
        try:
            col = self.summary_ws.col_values(1)
            for idx, v in enumerate(col[1:], start=2):
                if str(v).strip() == str(job_id):
                    return idx
        except Exception: pass
        return None

    def summary_upsert(self, job_id: int, date_iso: str, owner: str, channels_list: List[str], total_count: int, views_sum: int, deleted_on_time_yesno: str):
        if not self.enabled: return
        row = [job_id, date_iso or "", owner or "", ", ".join(channels_list), total_count, views_sum, deleted_on_time_yesno]
        row_idx = self._summary_find_row(job_id)
        if row_idx:
            self.summary_ws.update(
                values=[row],
                range_name=f"A{row_idx}:G{row_idx}",
                value_input_option="RAW",
            )
        else:
            self.summary_ws.append_row(row, value_input_option="RAW")

# ---------- DB ----------
def db_init():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS monitors(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin TEXT NOT NULL,
        subset TEXT,
        owner TEXT,
        start_date TEXT NOT NULL,
        cpm REAL NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'collecting',
        first_found_at TEXT
    );

    CREATE TABLE IF NOT EXISTS monitor_channels(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        monitor_id INTEGER NOT NULL,
        input TEXT NOT NULL,
        channel_id INTEGER,
        username TEXT,
        title TEXT,
        note TEXT,
        joined INTEGER DEFAULT 0,
        found_msg_id INTEGER,
        found_at TEXT,
        published_at TEXT,
        max_views INTEGER DEFAULT 0,
        views24 INTEGER,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(monitor_id,input),
        FOREIGN KEY(monitor_id) REFERENCES monitors(id)
    );

    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    conn.commit()
    return conn

def db_monitor_list_links(conn, monitor_id: int):
    cur = conn.cursor()
    cur.execute("SELECT input, username, title FROM monitor_channels WHERE monitor_id=? ORDER BY id", (monitor_id,))
    return cur.fetchall()

def db_monitor_meta(conn, monitor_id: int):
    cur = conn.cursor()
    cur.execute("SELECT admin,subset,owner,first_found_at FROM monitors WHERE id=?", (monitor_id,))
    return cur.fetchone()

def db_set_first_found(conn, monitor_id: int, when: datetime):
    cur = conn.cursor()
    cur.execute("UPDATE monitors SET first_found_at=? WHERE id=?", (when.isoformat(), monitor_id))
    conn.commit()

def db_monitor_mark_found(conn, monitor_id: int, link: str, msg_id: int, published_at: datetime, start_views: int):
    cur = conn.cursor()
    cur.execute("""UPDATE monitor_channels
                   SET found_msg_id=?, found_at=?, published_at=?, max_views=MAX(max_views, ?)
                   WHERE monitor_id=? AND input=?""",
                (msg_id, dt_utc().isoformat(), published_at.isoformat(), start_views, monitor_id, link))
    conn.commit()

def db_monitor_update_views(conn, monitor_id: int, link: str, v: int):
    cur = conn.cursor()
    cur.execute("UPDATE monitor_channels SET max_views=MAX(max_views, ?) WHERE monitor_id=? AND input=?", (v, monitor_id, link))
    conn.commit()

def db_monitor_set_views24(conn, monitor_id: int, link: str, v24: int):
    cur = conn.cursor()
    cur.execute("UPDATE monitor_channels SET views24=? WHERE monitor_id=? AND input=?", (v24, monitor_id, link))
    conn.commit()

def db_monitor_mark_deleted(conn, monitor_id: int, link: str):
    cur = conn.cursor()
    cur.execute("UPDATE monitor_channels SET deleted_at=? WHERE monitor_id=? AND input=? AND deleted_at IS NULL", (dt_utc().isoformat(), monitor_id, link))
    conn.commit()

def db_summary_recompute(conn, monitor_id: int):
    cur = conn.cursor()
    cur.execute("""SELECT input,published_at,max_views,deleted_at FROM monitor_channels 
                   WHERE monitor_id=? AND found_msg_id IS NOT NULL""", (monitor_id,))
    rows = cur.fetchall()
    if not rows:
        return None, [], 0, 0, "Ні"
    links = []
    dates = []
    views_sum = 0
    ok_all = True
    for link, pub, mv, del_at in rows:
        links.append(link)
        if pub:
            dates.append(pub)
        views_sum += int(mv or 0)
        if pub:
            pub_dt = datetime.fromisoformat(pub)
            if del_at:
                del_dt = datetime.fromisoformat(del_at)
                if del_dt < pub_dt + timedelta(hours=23):
                    ok_all = False
    date_iso = min(dates) if dates else ""
    return date_iso, links, len(rows), views_sum, ("Так" if ok_all else "Ні")

# ---------- Telethon helpers ----------
async def ensure_joined(client: TelegramClient, raw: str):
    uname = None
    m_inv = _INVITE_HASH_RE.match(raw.strip()) if "t.me" in raw else None
    if m_inv:
        invite_hash = m_inv.group(1)
        try:
            await client(ImportChatInviteRequest(invite_hash))
        except UserAlreadyParticipantError:
            pass
        except (InviteHashExpiredError, InviteHashInvalidError) as e:
            return None, False, f"інвайт недійсний: {e}"
        except FloodWaitError as e:
            return None, False, f"FLOOD_WAIT {e.seconds}s на join по інвайту"
        except Exception as e:
            return None, False, f"не вдалося зайти по інвайту: {e}"
    m_user = re.match(r"(?:https?://)?t\.me/([\w_]+)$", raw, re.IGNORECASE)
    if raw.startswith("@"): uname = raw[1:]
    elif m_user: uname = m_user.group(1)
    try:
        entity = await client.get_entity(uname if uname else raw)
    except Exception as e:
        return None, False, f"не вдалося resolve: {e}"
    try:
        await client(JoinChannelRequest(entity))
        return entity, True, "приєднався"
    except UserAlreadyParticipantError:
        return entity, False, "вже підписаний"
    except ChannelPrivateError:
        return entity, False, "приватний канал без доступу"
    except FloodWaitError as e:
        return entity, False, f"FLOOD_WAIT {e.seconds}s на join"
    except Exception as e:
        return entity, False, f"не вдалося підписатися: {e}"

async def fetch_message_text_by_link(client: TelegramClient, link: str):
    m_pub = _TME_POST_RE.match(link)
    m_priv = _TME_POST_PRIVATE_RE.match(link)
    try:
        if m_pub:
            username, mid = m_pub.group(1), int(m_pub.group(2))
            ent = await client.get_entity(username)
            msg = await client.get_messages(ent, ids=mid)
            return (msg.message or "").strip() if msg else None
        if m_priv:
            inner, mid = int(m_priv.group(1)), int(m_priv.group(2))
            ent = await client.get_entity(int(f"-100{inner}"))
            msg = await client.get_messages(ent, ids=mid)
            return (msg.message or "").strip() if msg else None
    except Exception:
        return None
    return None

async def poll_for_post_in_channel(client: TelegramClient, entity, needle: str, mode: str, fuzz: int,
                                   since_dt: datetime, until_dt: datetime):
    async for msg in client.iter_messages(entity=entity, offset_date=until_dt, reverse=True):
        if not msg.date: continue
        if msg.date <= since_dt: break
        text = (msg.message or "").strip()
        if not text: continue
        if match_text(text, needle, mode, fuzz):
            return msg
    return None

# ---------- Report routing & status ----------
def db_setting_get(conn, key: str):
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else None

def db_setting_set(conn, key: str, value: str):
    cur = conn.cursor()
    cur.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()

async def resolve_report_peer(client: TelegramClient, conn):
    val = db_setting_get(conn, "report_chat")
    target = val or REPORT_CHAT_ENV or CONTROL_CHAT
    try:
        if re.fullmatch(r"-?\d{6,}", target):
            return await client.get_entity(int(target))
        return await client.get_entity(target)
    except Exception:
        return await client.get_entity(CONTROL_CHAT)

def compose_status_lines(conn, monitor_id: int):
    cur = conn.cursor()
    cur.execute("SELECT admin FROM monitors WHERE id=?", (monitor_id,))
    row = cur.fetchone()
    admin = row[0] if row else ""
    cur.execute("SELECT input, username, found_msg_id, published_at, deleted_at, max_views FROM monitor_channels WHERE monitor_id=? ORDER BY id", (monitor_id,))
    rows = cur.fetchall()
    lines = []
    for idx, (link, uname, mid, pub, deleted, mv) in enumerate(rows, start=1):
        if mid and deleted:
            lines.append(f"{idx}) {link} — Видалено о {deleted} (охоплення {mv or 0})")
        elif mid:
            lines.append(f"{idx}) {link} — Вийшов о {pub} | views={mv or 0}")
        else:
            lines.append(f"{idx}) {link} — Немає поста")
    return admin, lines

# ---------- Alerts ----------
scheduled_alerts: Dict[int, bool] = {}

async def schedule_missing_alert_after_1h(client: TelegramClient, conn, jobs: JobsSheet, monitor_id: int, report_peer):
    if scheduled_alerts.get(monitor_id):
        return
    scheduled_alerts[monitor_id] = True
    meta = db_monitor_meta(conn, monitor_id)
    if not meta:
        scheduled_alerts.pop(monitor_id, None); 
        return
    _, _, _, first_found = meta
    if not first_found:
        scheduled_alerts.pop(monitor_id, None)
        return
    first_dt = datetime.fromisoformat(first_found)
    delay = (first_dt + timedelta(hours=1) - dt_utc()).total_seconds()
    if delay > 0:
        await asyncio.sleep(max(delay, 0))
    cur = conn.cursor()
    cur.execute("""SELECT input, username, title FROM monitor_channels 
                   WHERE monitor_id=? AND found_msg_id IS NULL""", (monitor_id,))
    rows = cur.fetchall()
    for link, uname, title in rows:
        name = f"@{uname}" if uname else (title or "канал")
        try:
            await client.send_message(report_peer, f"{link} ({name}) - Немає поста")
        except Exception:
            pass
        if jobs.enabled:
            jobs.jobs_set_not_released(monitor_id, link)
    scheduled_alerts.pop(monitor_id, None)

# ---------- 24h monitor ----------
async def monitor_message_with_24h(client: TelegramClient, monitor_id: int, link: str, entity, channel_username: Optional[str], msg_id: int,
                                   interval: timedelta, window: timedelta,
                                   jobs: JobsSheet, conn, report_peer):
    start_time = dt_utc()
    found24_logged = False

    try:
        msg = await client.get_messages(entity, ids=msg_id)
        if not msg:
            db_monitor_mark_deleted(conn, monitor_id, link)
            if jobs.enabled: jobs.jobs_set_deleted(monitor_id, link, dt_utc().isoformat())
            await client.send_message(report_peer, f"❌ Видалено при старті. {channel_username or entity} msg_id={msg_id}")
            return
        v0 = int(msg.views or 0)
        if jobs.enabled: jobs.jobs_set_views_max(monitor_id, link, v0)
        db_monitor_update_views(conn, monitor_id, link, v0)
    except Exception:
        pass

    end_time = start_time + window
    while dt_utc() < end_time:
        try:
            await asyncio.sleep(interval.total_seconds())
            msg = await client.get_messages(entity, ids=msg_id)
            if not msg:
                db_monitor_mark_deleted(conn, monitor_id, link)
                if jobs.enabled: jobs.jobs_set_deleted(monitor_id, link, dt_utc().isoformat())
                await client.send_message(report_peer, f"❌ Видалено (опитуванням). {channel_username or entity} msg_id={msg_id}")
                break
            v = int(msg.views or 0)
            db_monitor_update_views(conn, monitor_id, link, v)
            if jobs.enabled: jobs.jobs_set_views_max(monitor_id, link, v)

            if not found24_logged:
                ref = (msg.date.replace(tzinfo=None) if msg and msg.date else start_time)
                if dt_utc() >= ref + timedelta(hours=24):
                    if jobs.enabled: jobs.jobs_set_views24(monitor_id, link, v)
                    db_monitor_set_views24(conn, monitor_id, link, v)
                    found24_logged = True
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception:
            await asyncio.sleep(5)

    owner = (db_monitor_meta(conn, monitor_id) or ("","","",""))[2] or ""
    date_iso, links, count, views_sum, ok = db_summary_recompute(conn, monitor_id)
    if jobs.enabled and date_iso is not None:
        jobs.summary_upsert(monitor_id, date_iso, owner, links, count, views_sum, ok)

    await client.send_message(report_peer, f"✅ Моніторинг завершено. {channel_username or entity} msg_id={msg_id}")

# ---------- Commands ----------
HELP = (
"Команди:\n"
"/monitor_new admin=@manager start=YYYY-MM-DD cpm=1.2 owner=@owner [subset=o]\n"
"  → далі кидай лінки окремими повідомленнями → /monitor_links_done\n"
"/needle text=\"...\" | link=https://t.me/source/123  [mode=exact_strict|exact_norm|fuzzy|regex] [fuzz=85]\n"
"/arm_job id=123 find_interval=30m find_window=72h mon_interval=1h mon_window=24h [mode=...] [fuzz=...]\n"
"/report_chat set=@my_reports_group  (або chat id: -100...)\n"
"/status id=123  — надіслати зведення вручну\n"
)

def parse_kv(body: str) -> Dict[str, str]:
    """
    Парсить key=value пари з команди.
    Підтримує як /cmd key=value так і /cmd key="multi word".
    Працює і коли команда в один рядок, і коли параметри на наступних рядках.
    """
    body = body.strip()

    # Відокремлюємо саму команду від аргументів
    args = ""
    if body.startswith("/"):
        parts = body.split(None, 1)  # розбити тільки один раз
        args = parts[1] if len(parts) > 1 else ""
    else:
        args = body

    # Якщо аргументи розбиті по рядках — склеїмо їх у один рядок
    # (без першого рядка, якщо він був командою)
    if not args:
        lines = [x.strip() for x in body.splitlines() if x.strip()]
        if lines:
            # якщо перший рядок починається з /, беремо решту
            if lines[0].startswith("/"):
                args = " ".join(lines[1:])
            else:
                args = " ".join(lines)

    kv: Dict[str, str] = {}

    # Підтримка key="..." і key=bareword
    pattern = r'(\w+)\s*=\s*"(.*?)"|(\w+)\s*=\s*([^\s]+)'
    for m in re.finditer(pattern, args):
        if m.group(1):       # ключ у лапках
            kv[m.group(1).lower()] = m.group(2)
        else:                # bareword
            kv[m.group(3).lower()] = m.group(4)
    return kv

async def run():
    global NEEDLE_TEXT, NEEDLE_MODE, NEEDLE_FUZZ
    conn = db_init()
    jobs = JobsSheet()
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    async with client:
        control_peer = await client.get_entity(CONTROL_CHAT)
        report_peer = await resolve_report_peer(client, conn)

        MONITOR_LINKS_MODE = False
        CURRENT_MONITOR_ID: Optional[int] = None
        CURRENT_MONITOR_META: Dict[str,str] = {"admin":"", "subset":"", "owner":""}

        async def send_status(monitor_id: int):
            admin, lines = compose_status_lines(conn, monitor_id)
            msg = "Адмін: " + (admin or "") + "\n" + ("\n".join(lines) if lines else "немає каналів")
            try:
                await client.send_message(report_peer, msg)
            except Exception:
                await client.send_message(control_peer, msg)

        @client.on(events.NewMessage(chats=[control_peer]))
        async def on_msg(event):
            global NEEDLE_TEXT, NEEDLE_MODE, NEEDLE_FUZZ
            nonlocal MONITOR_LINKS_MODE, CURRENT_MONITOR_ID, CURRENT_MONITOR_META, report_peer
            text = (event.message.message or "").strip()

            from telethon import events

            @client.on(events.NewMessage(pattern=r'^/debug_links$', chats=[control_peer]))
            async def debug_links_cmd(event):
                """Показати, які t.me-посилання екстрактор реально бачить у цьому повідомленні/реплаї."""
                # 1) беремо текст із самого повідомлення
                text = event.raw_text or ""

                # якщо команда кинута у reply на велике повідомлення — тестуємо реплай
                if event.is_reply:
                    rep = await event.get_reply_message()
                    if rep and (rep.raw_text or "").strip():
                        text = rep.raw_text

                links = parse_telegram_links_from_text(text)
                if not links:
                    return await event.reply("Нічого не знайшов ¯\\_(ツ)_/¯")

                out = ["Знайдено посилань: " + str(len(links))]
                out += [f"{i + 1}. {u}" for i, u in enumerate(links)]
                await event.reply("\n".join(out))

            if text.startswith(("/start","/help")):
                await event.reply(HELP + f"\n[NEEDLE: {'SET' if NEEDLE_TEXT else 'NOT SET'} mode={NEEDLE_MODE}]")
                return

            # set report chat
            if text.startswith("/report_chat"):
                m = re.match(r"/report_chat\s+set\s*=\s*(.+)", text)
                if not m:
                    await event.reply("Приклад: /report_chat set=@my_reports_group або /report_chat set=-1001234567890")
                    return
                dest = m.group(1).strip()
                db_setting_set(conn, "report_chat", dest)
                report_peer = await resolve_report_peer(client, conn)
                await event.reply(f"Готово. Звіти тепер летять у: {dest}")
                return

            @client.on(events.NewMessage(chats=[control_peer]))
            async def _fw_auto_add_links(event):
                if (event.raw_text or "").strip().startswith("/"):
                    return
                try:
                    active = getattr(MONITOR_BUFFER, 'active', False)
                except NameError:
                    active = False
                if not active:
                    return

                links = parse_telegram_links_from_text(event.raw_text or "")
                if not links:
                    return

                report = []
                ok_count = 0
                bad_count = 0

                for link in links:
                    norm = _sanitize_link(link)
                    title = "-"
                    try:
                        # invite-посилання: t.me/+HASH або t.me/joinchat/HASH
                        if re.search(r"t\.me/(?:\+|joinchat/)", norm, re.IGNORECASE):
                            m = re.search(r"t\.me/(?:\+|joinchat/)([A-Za-z0-9_-]+)", norm, re.IGNORECASE)
                            if not m:
                                raise ValueError("BadInviteLink")
                            invite_hash = m.group(1)
                            # приєднання по інвайту
                            try:
                                res = await client(ImportChatInviteRequest(invite_hash))
                                # отримати об'єкт каналу/чату з результату
                                ent = None
                                if getattr(res, "chats", None):
                                    ent = res.chats[0]
                                elif getattr(res, "users", None):
                                    ent = res.users[0]
                                entity = ent or await client.get_entity(norm)
                            except UserAlreadyParticipantError:
                                entity = await client.get_entity(norm)
                            title = getattr(entity, "title", None) or getattr(entity, "username", "") or "-"
                            status = "✅ додано"
                            ok_count += 1

                        else:
                            # звичайний публічний канал/чат
                            entity = await client.get_entity(norm)
                            try:
                                await client(JoinChannelRequest(entity))
                                title = getattr(entity, "title", None) or getattr(entity, "username", "") or "-"
                                status = "✅ додано"
                                ok_count += 1
                            except UserAlreadyParticipantError:
                                title = getattr(entity, "title", None) or getattr(entity, "username", "") or "-"
                                status = "↪️ вже підписаний"
                                ok_count += 1

                    except FloodWaitError as fw:
                        status = f"⏸ FLOOD_WAIT {fw.seconds}s"
                        bad_count += 1
                        await asyncio.sleep(fw.seconds + 2)

                    except (InviteHashExpiredError, InviteHashInvalidError):
                        status = "❌ BadInviteHash"
                        bad_count += 1

                    except ChannelPrivateError:
                        status = "❌ ChannelPrivate"
                        bad_count += 1

                    except Exception as e:
                        status = f"❌ {type(e).__name__}"
                        bad_count += 1

                    report.append(f"{norm} – {title} – {status}")
                    await asyncio.sleep(random.uniform(0.3, 0.6))  # невелика пауза між запитами

                if report:
                    text = "\n".join(f"{i + 1}. {row}" for i, row in enumerate(report))
                    text += f"\n\nУнікальних: {ok_count}\nНевалідних: {bad_count}"
                    await event.reply(text)
                else:
                    await event.reply("Жодного посилання не знайшов")

            # create monitor
            if text.startswith("/monitor_new"):
                kv = parse_kv(text)
                admin = kv.get("admin","")
                subset = kv.get("subset","")
                owner = kv.get("owner","")
                start = kv.get("start")
                try: cpm = float(kv.get("cpm","1"))
                except ValueError:
                    await event.reply("Невалідний cpm.")
                    return
                if not (admin and start):
                    await event.reply("Приклад: /monitor_new admin=@manager start=2025-08-24 cpm=1.2 owner=@owner [subset=o]")
                    return
                try: datetime.strptime(start, "%Y-%m-%d")
                except Exception:
                    await event.reply("Дата має бути YYYY-MM-DD")
                    return
                cur = conn.cursor()
                cur.execute("INSERT INTO monitors(admin,subset,owner,start_date,cpm,created_at,status,first_found_at) VALUES(?,?,?,?,?,?,?,NULL)",
                            (admin, subset, owner, start, cpm, dt_utc().isoformat(), "collecting"))
                conn.commit()
                mid = cur.lastrowid
                CURRENT_MONITOR_ID = mid
                CURRENT_MONITOR_META = {"admin":admin, "subset":subset, "owner":owner}
                MONITOR_LINKS_MODE = True
                await event.reply(f"Монітор #{mid} створено. Кидай лінки на канали окремими повідомленнями. Завершити: /monitor_links_done")
                return

            if text.startswith("/monitor_links_done"):
                MONITOR_LINKS_MODE = False
                CURRENT_MONITOR_ID = None
                await event.reply("Режим додавання лінків для монітора вимкнено.")
                return

            @client.on(events.NewMessage(pattern=r'^/_needle(\s|$)', chats=[control_peer]))
            async def needle_from_reply(event):
                global NEEDLE_TEXT, NEEDLE_MODE, NEEDLE_FUZZ
                if not event.is_reply:
                    return await event.reply(
                        "Зроби reply цією командою на потрібний пост (можна пересланий).\nПриклад: відповісти на пост → /_needle")

                msg = await event.get_reply_message()
                text = (getattr(msg, 'message', '') or '').strip()
                if not text:
                    return await event.reply("У реплаї немає тексту/підпису. OCR не підтримуємо.")

                NEEDLE_TEXT = text
                NEEDLE_MODE = "exact_norm"
                try:
                    NEEDLE_FUZZ = int(os.getenv("DEFAULT_FUZZ", "85"))
                except Exception:
                    NEEDLE_FUZZ = 85

                await event.reply(
                    f"NEEDLE з пересланого. mode={NEEDLE_MODE}, fuzz={NEEDLE_FUZZ}, len={len(NEEDLE_TEXT)}")

            # needle
            if text.startswith("/needle"):
                kv = parse_kv(text)
                if "text" in kv:
                    NEEDLE_TEXT = kv["text"].strip()
                elif "link" in kv:
                    t = await fetch_message_text_by_link(client, kv["link"].strip())
                    NEEDLE_TEXT = (t or "").strip()
                    if not NEEDLE_TEXT:
                        await event.reply("Не вдалося отримати текст з лінка.")
                        return
                NEEDLE_MODE = kv.get("mode", DEFAULT_MODE).lower()
                NEEDLE_FUZZ = int(kv.get("fuzz", str(DEFAULT_FUZZ)))
                await event.reply(f"NEEDLE встановлено. mode={NEEDLE_MODE}, fuzz={NEEDLE_FUZZ}, len={len(NEEDLE_TEXT or '')}")
                return

            # arm_job
            if text.startswith("/arm_job"):
                if not NEEDLE_TEXT:
                    await event.reply("Спочатку встанови еталонний пост: /needle text=\"...\" або /needle link=...")
                    return
                kv = parse_kv(text)
                try: monitor_id = int(kv.get("id","0"))
                except ValueError:
                    await event.reply("Вкажи валідний id монітора.")
                    return

                find_interval = parse_timedelta(kv.get("find_interval", DEFAULT_FIND_INTERVAL))
                find_window   = parse_timedelta(kv.get("find_window", DEFAULT_FIND_WINDOW))
                mon_interval  = parse_timedelta(kv.get("mon_interval", DEFAULT_MON_INTERVAL))
                mon_window    = parse_timedelta(kv.get("mon_window", DEFAULT_MON_WINDOW))
                mode = kv.get("mode", NEEDLE_MODE).lower()
                fuzz_thr = int(kv.get("fuzz", str(NEEDLE_FUZZ)))

                meta = db_monitor_meta(conn, monitor_id)
                if not meta:
                    await event.reply("Монітор не знайдено.")
                    return
                admin, subset, owner, first_found_at = meta

                # load links
                link_rows = db_monitor_list_links(conn, monitor_id)
                if not link_rows:
                    await event.reply("У монітора немає лінків.")
                    return

                await event.reply(f"🔔 ARM_JOB по #{monitor_id}: {len(link_rows)} каналів | mode={mode} fuzz={fuzz_thr}\nfind_interval={find_interval}, find_window={find_window}\nmon_interval={mon_interval}, mon_window={mon_window}")

                # ensure base rows in Jobs
                jobs_sheet = JobsSheet()
                if jobs_sheet.enabled:
                    for link, uname, _ in link_rows:
                        ch_disp = f"@{uname}" if uname else ""
                        jobs_sheet.jobs_upsert_base(admin, subset, ch_disp, link, monitor_id, "")

                # send initial status
                await send_status(monitor_id)

                start_ts = dt_utc()

                # worker to poll for appearance
                async def worker_per_channel(link: str, uname: Optional[str], title: Optional[str]):
                    # resolve entity once
                    try:
                        entity = await client.get_entity(uname if uname else link)
                    except Exception as e:
                        if jobs_sheet.enabled: jobs_sheet.jobs_append_comment(monitor_id, link, f"resolve error: {e}")
                        return

                    since = start_ts
                    deadline = start_ts + find_window
                    while dt_utc() < deadline:
                        try:
                            msg = await poll_for_post_in_channel(client, entity, NEEDLE_TEXT, mode, fuzz_thr, since, dt_utc())
                            if msg:
                                v0 = int(msg.views or 0)
                                published_iso = msg.date.isoformat() if msg.date else ""
                                # first_found scheduling
                                cur = conn.cursor()
                                cur.execute("SELECT first_found_at FROM monitors WHERE id=?", (monitor_id,))
                                v = cur.fetchone()
                                if v and not v[0]:
                                    db_set_first_found(conn, monitor_id, msg.date.replace(tzinfo=None) if msg.date else dt_utc())
                                    asyncio.create_task(schedule_missing_alert_after_1h(client, conn, jobs_sheet, monitor_id, report_peer))

                                # mark found
                                db_monitor_mark_found(conn, monitor_id, link, msg.id, msg.date or dt_utc(), v0)
                                if jobs_sheet.enabled: jobs_sheet.jobs_set_released(monitor_id, link, msg.id, published_iso, v0)

                                try:
                                    await client.send_message(report_peer, f"✅ Знайшов пост у {('@'+uname) if uname else link}\nmsg_id={msg.id} | views(старт): {v0}")
                                except Exception:
                                    await client.send_message(control_peer, f"✅ Знайшов пост у {('@'+uname) if uname else link}\nmsg_id={msg.id} | views(старт): {v0}")

                                # recompute summary
                                date_iso, links_agg, count, views_sum, ok = db_summary_recompute(conn, monitor_id)
                                if jobs_sheet.enabled and date_iso is not None:
                                    jobs_sheet.summary_upsert(monitor_id, date_iso, owner or "", links_agg, count, views_sum, ok)

                                # start 24h monitor for this message
                                asyncio.create_task(monitor_message_with_24h(client, monitor_id, link, entity, uname, msg.id, mon_interval, mon_window, jobs_sheet, conn, report_peer))
                                return
                        except FloodWaitError as e:
                            await asyncio.sleep(e.seconds)
                        except Exception:
                            pass
                        await asyncio.sleep(find_interval.total_seconds())
                        since = dt_utc() - timedelta(minutes=5)
                    try:
                        await client.send_message(report_peer, f"⏱️ Не знайдено пост у {('@'+uname) if uname else link} за відведений час.")
                    except Exception:
                        await client.send_message(control_peer, f"⏱️ Не знайдено пост у {('@'+uname) if uname else link} за відведений час.")

                # spawn workers
                for link, uname, title in link_rows:
                    asyncio.create_task(worker_per_channel(link, uname, title))

                # periodic status reports during find_window
                async def periodic_status_loop():
                    deadline = start_ts + find_window
                    while dt_utc() < deadline:
                        await asyncio.sleep(find_interval.total_seconds())
                        await send_status(monitor_id)
                asyncio.create_task(periodic_status_loop())
                return

            # adding links while in monitor collect mode
            if MONITOR_LINKS_MODE and not text.startswith("/"):
                links = list({*extract_tme_links_from_text(text), *extract_hidden_links_from_entities(event.message)})
                if not links:
                    await event.reply("Немає лінків у повідомленні.")
                    return
                admin = CURRENT_MONITOR_META.get("admin","")
                subset = CURRENT_MONITOR_META.get("subset","")
                jobs_sheet = JobsSheet()
                for idx, link in enumerate(links, 1):
                    # insert row
                    try:
                        cur2 = conn.cursor()
                        cur2.execute("INSERT INTO monitor_channels(monitor_id,input,created_at) VALUES(?,?,?)",
                                    (CURRENT_MONITOR_ID, link, dt_utc().isoformat()))
                        conn.commit()
                        duplicate = False
                    except sqlite3.IntegrityError:
                        duplicate = True

                    if duplicate:
                        if jobs_sheet.enabled: jobs_sheet.jobs_upsert_base(admin, subset, "", link, CURRENT_MONITOR_ID, "дубль")
                        await event.reply(f"— {link}: дубль, пропущено.")
                        continue
                    # join
                    entity, joined, jnote = await ensure_joined(client, link)
                    if not entity:
                        if jobs_sheet.enabled: jobs_sheet.jobs_upsert_base(admin, subset, "", link, CURRENT_MONITOR_ID, jnote or "")
                        await event.reply(f"— {link}: {jnote}")
                    else:
                        title = getattr(entity, "title", "") or getattr(entity, "first_name", "") or ""
                        username = getattr(entity, "username", None)
                        chan_id = getattr(entity, "id", None)
                        cur3 = conn.cursor()
                        cur3.execute("""UPDATE monitor_channels SET channel_id=?, username=?, title=?, joined=?, note=?
                                        WHERE monitor_id=? AND input=?""",
                                    (chan_id, username, title, 1 if joined else 0, jnote, CURRENT_MONITOR_ID, link))
                        conn.commit()
                        ch_disp = f"@{username}" if username else f"id:{chan_id}"
                        if jobs_sheet.enabled: jobs_sheet.jobs_upsert_base(admin, subset, ch_disp, link, CURRENT_MONITOR_ID, jnote or "")
                        await event.reply(f"— {link}: {ch_disp} — {jnote or 'ok'}")

                    if idx < len(links):
                        m = re.search(r"FLOOD_WAIT (\d+)s", jnote or "")
                        if m:
                            sec = int(m.group(1))
                            if jobs_sheet.enabled: jobs_sheet.jobs_append_comment(CURRENT_MONITOR_ID, link, f"FLOOD_WAIT {sec}s")
                            await event.reply(f"⏳ FLOOD_WAIT: пауза {sec}s…")
                            await asyncio.sleep(sec)
                        else:
                            delay = random.randint(2,8)
                            await event.reply(f"⏳ Затримка {delay}s…")
                            await asyncio.sleep(delay)
                return

        print("[*] v13 loaded. Waiting...")
        await client.run_until_disconnected()

if __name__ == "__main__":
    import sys
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())

