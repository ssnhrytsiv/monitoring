# Project Map (auto-generated)

- Generated: 2025-08-30 10:11:11 UTC
- Branch: copilot/fix-fdbc6743-dcc5-4498-8381-99e5d6ad123e

## Structure (depth=4)

```text
.
├── ...43534.py
├── .env
├── .gitignore
├── README.md
├── REVERT-commit-3249799e1d55ab6707d5298fa360d53a7231fc8d.txt
├── app
│   ├── __init__.py
│   ├── config.py
│   ├── flows
│   │   └── batch_links
│   │       ├── __init__.py
│   │       ├── common.py
│   │       ├── process_links.py
│   │       └── queue_worker.py
│   ├── logging_json.py
│   ├── plugins
│   │   ├── __init__.py
│   │   ├── batch_links.py
│   │   ├── batch_links.py.zip
│   │   ├── help_and_ping.py
│   │   ├── metrics_watch.py
│   │   ├── needle_reply.py
│   │   ├── post_templates.py
│   │   └── progress_live.py
│   ├── services
│   │   ├── __init__.py
│   │   ├── account_pool.py
│   │   ├── db
│   │   │   └── bad_invites.py
│   │   ├── gsheets.py
│   │   ├── joiner.py
│   │   ├── link_queue.py
│   │   ├── membership_db.py
│   │   ├── post_match.py
│   │   ├── post_watch_db.py
│   │   └── subscription_check.py
│   ├── telethon_client.py
│   └── utils
│       ├── __init__.py
│       ├── formatting.py
│       ├── link_parser.py
│       ├── notices.py
│       ├── text_norm.py
│       ├── tg_links.py
│       └── throttle.py
├── docs
│   ├── ARCHITECTURE.md
│   └── PROJECT_MAP.md
├── fix-process_links.patch
├── main.py
├── post_watchdog.sqlite3
├── post_watchdog.sqlite3-shm
├── post_watchdog.sqlite3-wal
├── requirements.txt
├── scripts
│   └── generate-project-map.sh
└── tg_forward_patch.diff

10 directories, 48 files
```

## Symbols index (functions/classes)

```text
-1,6 +1,7        hunk          5 fix-process_links.patch @@ -1,6 +1,7 @@
-16,6 +17,13     hunk         13 fix-process_links.patch @@ -16,6 +17,13 @@
-224,7 +232,12   hunk         51 fix-process_links.patch @@ -224,7 +232,12 @@
-57,7 +65,7      hunk         27 fix-process_links.patch @@ -57,7 +65,7 @@
-79,7 +87,7      hunk         35 fix-process_links.patch @@ -79,7 +87,7 @@
-88,7 +96,7      hunk         43 fix-process_links.patch @@ -88,7 +96,7 @@
API_HASH         variable      8 app/config.py    API_HASH = os.getenv("API_HASH", "")
API_HASH         variable     25 app/services/account_pool.py API_HASH = _env("API_HASH", "")
API_ID           variable      7 app/config.py    API_ID = int(os.getenv("API_ID", "0"))
API_ID           variable     24 app/services/account_pool.py API_ID = int(_env("API_ID", "0") or "0")
Architecture overview chapter       1 docs/ARCHITECTURE.md # Architecture overview
CASE_SENSITIVE   variable     23 app/config.py    CASE_SENSITIVE = os.getenv("CASE_SENSITIVE", "false").lower() in ("1", "true", "yes")
CONTROL_PEER     variable     11 app/config.py    CONTROL_PEER = os.getenv("CONTROL_CHAT", "")
ClientSlot       class        46 app/services/account_pool.py class ClientSlot:
ClientSlot.busy  variable     50 app/services/account_pool.py busy: bool = False
ClientSlot.lock  variable     51 app/services/account_pool.py lock: asyncio.Lock = asyncio.Lock()
ClientSlot.next_ready variable     49 app/services/account_pool.py next_ready: float = 0.0 # unix-ts, коли клієнт знову доступний
Configuration    section      18 docs/ARCHITECTURE.md ## Configuration
Credentials      variable     10 app/services/gsheets.py Credentials = None
DB_PATH          variable      4 app/services/link_queue.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable      6 app/services/post_watch_db.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable      7 app/services/membership_db.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable     26 app/config.py    DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DDL              variable      6 app/services/link_queue.py DDL = """
DDL              variable      8 app/services/post_watch_db.py DDL = """
DDL              variable      9 app/services/membership_db.py DDL = """
DEFAULT_FIND_INTERVAL variable     15 app/config.py    DEFAULT_FIND_INTERVAL = os.getenv("DEFAULT_FIND_INTERVAL", "30m")
DEFAULT_FIND_WINDOW variable     17 app/config.py    DEFAULT_FIND_WINDOW = os.getenv("DEFAULT_FIND_WINDOW", "72h")
DEFAULT_FUZZ     variable     22 app/config.py    DEFAULT_FUZZ = int(os.getenv("DEFAULT_FUZZ", "85"))
DEFAULT_MODE     variable     21 app/config.py    DEFAULT_MODE = os.getenv("DEFAULT_MODE", "exact_strict")
DEFAULT_MON_INTERVAL variable     16 app/config.py    DEFAULT_MON_INTERVAL = os.getenv("DEFAULT_MON_INTERVAL", "1h")
DEFAULT_MON_WINDOW variable     18 app/config.py    DEFAULT_MON_WINDOW = os.getenv("DEFAULT_MON_WINDOW", "24h")
Data/Control flow section      12 docs/ARCHITECTURE.md ## Data/Control flow
DebouncedProgress class        10 app/plugins/progress_live.py class DebouncedProgress:
DebouncedProgress._bar member      129 app/plugins/progress_live.py def _bar(done: int, total: int, width: int = 20) -> str:
DebouncedProgress._changed variable     34 app/plugins/progress_live.py _changed: bool = False
DebouncedProgress._closed variable     37 app/plugins/progress_live.py _closed: bool = False
DebouncedProgress._debounced_edit member       89 app/plugins/progress_live.py async def _debounced_edit(self) -> None:
DebouncedProgress._edit member       99 app/plugins/progress_live.py async def _edit(self, final: bool) -> None:
DebouncedProgress._last_render variable     36 app/plugins/progress_live.py _last_render: str = ""
DebouncedProgress._mark_changed member       81 app/plugins/progress_live.py def _mark_changed(self) -> None:
DebouncedProgress._render member      113 app/plugins/progress_live.py def _render(self, header_suffix: str, final: bool = False) -> str:
DebouncedProgress.actor variable     30 app/plugins/progress_live.py actor: str = "" # session/slot label
DebouncedProgress.add_status member       53 app/plugins/progress_live.py def add_status(self, status: str) -> None:
DebouncedProgress.already variable     26 app/plugins/progress_live.py already: int = 0
DebouncedProgress.bad variable     27 app/plugins/progress_live.py bad: int = 0 # invalid/private/error
DebouncedProgress.current variable     29 app/plugins/progress_live.py current: str = "" # current url
DebouncedProgress.debounce variable     19 app/plugins/progress_live.py debounce: float = field(default_factory=lambda: float(_env("PROGRESS_DEBOUNCE", "3")))
DebouncedProgress.done variable     24 app/plugins/progress_live.py done: int = 0
DebouncedProgress.finish member       72 app/plugins/progress_live.py async def finish(self, footer: str = "") -> None:
DebouncedProgress.flood variable     28 app/plugins/progress_live.py flood: int = 0
DebouncedProgress.footer variable     31 app/plugins/progress_live.py footer: str = "" # optional summary
DebouncedProgress.ok variable     25 app/plugins/progress_live.py ok: int = 0 # joined
DebouncedProgress.set_current member       46 app/plugins/progress_live.py def set_current(self, url: str | None = None, actor: str | None = None) -> None:
DebouncedProgress.set_footer member       68 app/plugins/progress_live.py def set_footer(self, text: str) -> None:
DebouncedProgress.start member       40 app/plugins/progress_live.py async def start(self) -> None:
FINAL_GLOBAL     variable     46 app/services/membership_db.py FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
FINAL_PER_ACC    variable     47 app/services/membership_db.py FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")
GSHEET_CREDS_FILE variable     30 app/config.py    GSHEET_CREDS_FILE = os.getenv("GSHEET_CREDS_FILE", "service_account.json")
GSHEET_JOBS_SHEET variable     31 app/config.py    GSHEET_JOBS_SHEET = os.getenv("GSHEET_JOBS_SHEET", "Jobs")
GSHEET_SPREADSHEET_ID variable     29 app/config.py    GSHEET_SPREADSHEET_ID = os.getenv("GSHEET_SPREADSHEET_ID", "")
GSHEET_SUMMARY_SHEET variable     32 app/config.py    GSHEET_SUMMARY_SHEET = os.getenv("GSHEET_SUMMARY_SHEET", "Summary")
HELP_TEXT_MD     variable      4 app/plugins/help_and_ping.py HELP_TEXT_MD = """\
High-level components section       8 docs/ARCHITECTURE.md ## High-level components
Integrations/externals section      15 docs/ARCHITECTURE.md ## Integrations/externals
JSONFormatter    class         9 app/logging_json.py class JSONFormatter(logging.Formatter):
JSONFormatter.format member       10 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
LINK_DELAY_INVITE_MAX variable     31 app/utils/throttle.py LINK_DELAY_INVITE_MAX = _f("LINK_DELAY_INVITE_MAX", "10")
LINK_DELAY_INVITE_MAX variable     35 app/utils/throttle.py LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX = _clamp_pair(LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX)
LINK_DELAY_INVITE_MIN variable     30 app/utils/throttle.py LINK_DELAY_INVITE_MIN = _f("LINK_DELAY_INVITE_MIN", "6")
LINK_DELAY_INVITE_MIN variable     35 app/utils/throttle.py LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX = _clamp_pair(LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX)
LINK_DELAY_PUBLIC_MAX variable     29 app/utils/throttle.py LINK_DELAY_PUBLIC_MAX = _f("LINK_DELAY_PUBLIC_MAX", "4")
LINK_DELAY_PUBLIC_MAX variable     34 app/utils/throttle.py LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX = _clamp_pair(LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX)
LINK_DELAY_PUBLIC_MIN variable     28 app/utils/throttle.py LINK_DELAY_PUBLIC_MIN = _f("LINK_DELAY_PUBLIC_MIN", "2")
LINK_DELAY_PUBLIC_MIN variable     34 app/utils/throttle.py LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX = _clamp_pair(LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX)
LOG_LEVEL        variable     37 app/config.py    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
MONITOR_BUFFER   variable     16 app/telethon_client.py MONITOR_BUFFER = SimpleNamespace(
Operational notes section      21 docs/ARCHITECTURE.md ## Operational notes
PLUGINS_PACKAGE  variable     34 app/config.py    PLUGINS_PACKAGE = "app.plugins"
POOL_SESSIONS    variable     42 app/services/account_pool.py POOL_SESSIONS = _parse_accounts_env()
PRIMARY          variable     26 app/services/account_pool.py PRIMARY = _env("SESSION") or _env("SESSION_NAME") or "tg_session"
PROBE_DELAY_MAX  variable     25 app/utils/throttle.py PROBE_DELAY_MAX = _f("PROBE_DELAY_MAX", "1.10")
PROBE_DELAY_MAX  variable     33 app/utils/throttle.py PROBE_DELAY_MIN, PROBE_DELAY_MAX = _clamp_pair(PROBE_DELAY_MIN, PROBE_DELAY_MAX)
PROBE_DELAY_MIN  variable     24 app/utils/throttle.py PROBE_DELAY_MIN = _f("PROBE_DELAY_MIN", "0.45")
PROBE_DELAY_MIN  variable     33 app/utils/throttle.py PROBE_DELAY_MIN, PROBE_DELAY_MAX = _clamp_pair(PROBE_DELAY_MIN, PROBE_DELAY_MAX)
PlainFormatterClean class        48 app/logging_json.py class PlainFormatterClean(logging.Formatter):
PlainFormatterVerbose class        36 app/logging_json.py class PlainFormatterVerbose(logging.Formatter):
PlainFormatterVerbose.format member       37 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
Project Map (auto-generated) chapter       1 docs/PROJECT_MAP.md # Project Map (auto-generated)
Purpose          section       5 docs/ARCHITECTURE.md ## Purpose
REPORT_CHAT      variable     12 app/config.py    REPORT_CHAT = os.getenv("REPORT_CHAT", "")
RE_HTML_TG       variable     22 app/utils/link_parser.py RE_HTML_TG = re.compile(
RE_MD_TG         variable     16 app/utils/link_parser.py RE_MD_TG = re.compile(
RE_TG_RAW        variable     29 app/utils/link_parser.py RE_TG_RAW = re.compile(
SESSION          variable      9 app/config.py    SESSION = os.getenv("SESSION_NAME", "tg_session")
STATUS_ICON      variable      5 app/utils/formatting.py STATUS_ICON = {
Structure (depth=4) section       6 docs/PROJECT_MAP.md ## Structure (depth=4)
StructuredAdapter class        52 app/logging_json.py class StructuredAdapter(logging.LoggerAdapter):
StructuredAdapter.__init__ member       53 app/logging_json.py def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
StructuredAdapter.add_context member       56 app/logging_json.py def add_context(self, **ctx):
StructuredAdapter.log member       59 app/logging_json.py def log(self, level: int, msg: Any, *args, **kwargs):
Symbols index (functions/classes) section      71 docs/PROJECT_MAP.md ## Symbols index (functions/classes)
Telegram Post Watchdog — v13 (Full) chapter       1 README.md        # Telegram Post Watchdog — v13 (Full)
TgMessage        unknown       9 app/utils/link_parser.py from telethon.tl.custom.message import Message as TgMessage
TgMessage        variable     12 app/utils/link_parser.py TgMessage = None # type: ignore
VERBOSE_NOTICES  variable      3 app/utils/notices.py VERBOSE_NOTICES = False # set True to see debug notices
WHOLE_WORD       variable     24 app/config.py    WHOLE_WORD = os.getenv("WHOLE_WORD", "false").lower() in ("1", "true", "yes")
_CONTROL_PEER_ID variable     10 ...43534.py      _CONTROL_PEER_ID = None
_CONTROL_PEER_ID variable     14 app/plugins/post_templates.py _CONTROL_PEER_ID = None
_CONTROL_PEER_ID variable     15 app/plugins/batch_links.py _CONTROL_PEER_ID = None
_INVIS           variable     35 app/utils/link_parser.py _INVIS = ("\u200b", "\u200e", "\u200f")
_LINK_RE         variable     53 app/plugins/post_templates.py _LINK_RE = re.compile(
_META_PATH       variable     17 app/plugins/post_templates.py _META_PATH = "data/post_templates_meta.json"
_MONITOR_CHAT_ID variable     14 app/plugins/batch_links.py _MONITOR_CHAT_ID = None
_MONITOR_ENABLED variable     13 app/plugins/batch_links.py _MONITOR_ENABLED = False
_POOL            variable     53 app/services/account_pool.py _POOL: List[ClientSlot] = []
_POOL_LOCK       variable     54 app/services/account_pool.py _POOL_LOCK = asyncio.Lock()
_RESERVED        variable      7 app/logging_json.py _RESERVED = {"exc_info", "stack_info", "stacklevel", "extra"}
_TAG_RE          variable     91 app/plugins/post_templates.py _TAG_RE = re.compile(r"<[^>]+>")
_TG_RE           variable     37 app/utils/tg_links.py _TG_RE = re.compile(
_TRAIL_PUNCT     variable     36 app/utils/link_parser.py _TRAIL_PUNCT = ".,;:)]}>"
_TRIM_LEAD       variable      6 app/utils/tg_links.py _TRIM_LEAD = "(<[«\"' \u00A0\u200b\u200c\u200d\u2060"
_TRIM_TRAIL      variable      7 app/utils/tg_links.py _TRIM_TRAIL = ".,;:!?)]}>»\"' \u00A0\u200b\u200c\u200d\u2060"
__all__          variable      4 app/flows/batch_links/__init__.py __all__ = ["process_links", "run_link_queue_worker"]
__init__         member       53 app/logging_json.py def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
_add_tmpl        function    140 ...43534.py      async def _add_tmpl(evt):
_add_tmpl        function    277 app/plugins/post_templates.py async def _add_tmpl(evt):
_bar             member      129 app/plugins/progress_live.py def _bar(done: int, total: int, width: int = 20) -> str:
_build_full_footer function     26 app/flows/batch_links/process_links.py def _build_full_footer(items: List[dict]) -> str:
_canon           function     22 app/utils/tg_links.py def _canon(u: str) -> str:
_changed         variable     34 app/plugins/progress_live.py _changed: bool = False
_clamp_pair      function     16 app/utils/throttle.py def _clamp_pair(lo: float, hi: float) -> Tuple[float, float]:
_clean           function     39 app/utils/link_parser.py def _clean(s: str) -> str:
_client          function     12 app/services/gsheets.py def _client():
_closed          variable     37 app/plugins/progress_live.py _closed: bool = False
_collect_links   function     57 app/plugins/post_templates.py def _collect_links(msg, html_text: str) -> list:
_column_exists   function     25 app/services/post_watch_db.py def _column_exists(c: sqlite3.Connection, table: str, column: str) -> bool:
_conn            function     20 app/services/post_watch_db.py def _conn():
_conn            function     27 app/services/link_queue.py def _conn():
_conn            function     50 app/services/membership_db.py def _conn():
_debounced_edit  member       89 app/plugins/progress_live.py async def _debounced_edit(self) -> None:
_edit            member       99 app/plugins/progress_live.py async def _edit(self, final: bool) -> None:
_ensure_bad_invites_table function      8 app/services/db/bad_invites.py def _ensure_bad_invites_table() -> None:
_ensure_connected function    114 app/services/account_pool.py async def _ensure_connected(slot: ClientSlot) -> None:
_env             function      5 app/plugins/progress_live.py def _env(name: str, default: str = "") -> str:
_env             function     20 app/services/account_pool.py def _env(name: str, default: str = "") -> str:
_env_bool        function     96 app/logging_json.py def _env_bool(name: str, default: bool) -> bool:
_escape          unknown       2 ...43534.py      from html import escape as _escape
_escape          unknown       5 app/flows/batch_links/process_links.py from html import escape as _escape
_escape          unknown       5 app/plugins/post_templates.py from html import escape as _escape
_escape          unknown      18 ...43534.py      from html import escape as _escape
_extract_from_entities function    130 app/utils/link_parser.py def _extract_from_entities(text: str, entities: Iterable) -> List[str]:
_extract_hidden_links_from_message function     57 app/flows/batch_links/process_links.py def _extract_hidden_links_from_message(msg) -> List[str]:
_extract_invite_hash function     24 app/services/joiner.py def _extract_invite_hash(url: str) -> str | None:
_extract_invite_hash function     87 app/services/membership_db.py def _extract_invite_hash(inv_or_url: str) -> Optional[str]:
_extract_message_html function     13 ...43534.py      def _extract_message_html(msg) -> str:
_extract_message_html function    107 app/plugins/post_templates.py def _extract_message_html(msg) -> str:
_extract_message_html._escape unknown      18 ...43534.py      from html import escape as _escape
_extract_message_html._is_high function     96 ...43534.py      def _is_high(c: str) -> bool:
_extract_message_html._is_high function    177 app/plugins/post_templates.py def _is_high(c: str) -> bool:
_extract_message_html._is_low function    100 ...43534.py      def _is_low(c: str) -> bool:
_extract_message_html._is_low function    180 app/plugins/post_templates.py def _is_low(c: str) -> bool:
_extract_message_html.add_span function     35 ...43534.py      def add_span(off: int, ln: int, start_tag: str, end_tag: str):
_extract_message_html.add_span function    118 app/plugins/post_templates.py def add_span(off: int, ln: int, start_tag: str, end_tag: str):
_extract_message_html.ttypes unknown      19 ...43534.py      from telethon.tl import types as ttypes
_extract_title   function     93 app/plugins/post_templates.py def _extract_title(html_text: str) -> str:
_f               function     10 app/utils/throttle.py def _f(name: str, default: str) -> float:
_find_slot       function     72 app/services/account_pool.py def _find_slot(obj: Union[TelegramClient, ClientSlot]) -> Optional[ClientSlot]:
_fix_scheme      function      9 app/utils/tg_links.py def _fix_scheme(u: str) -> str:
_has_column      function     56 app/services/membership_db.py def _has_column(c: sqlite3.Connection, table: str, col: str) -> bool:
_is_high         function     96 ...43534.py      def _is_high(c: str) -> bool:
_is_high         function    177 app/plugins/post_templates.py def _is_high(c: str) -> bool:
_is_low          function    100 ...43534.py      def _is_low(c: str) -> bool:
_is_low          function    180 app/plugins/post_templates.py def _is_low(c: str) -> bool:
_last_render     variable     36 app/plugins/progress_live.py _last_render: str = ""
_lease_ctx       function    174 app/services/account_pool.py async def _lease_ctx(slot: ClientSlot):
_list            function    209 ...43534.py      async def _list(evt):
_list            function    379 app/plugins/post_templates.py async def _list(evt):
_load_meta       function     20 app/plugins/post_templates.py def _load_meta():
_main            function     16 main.py          async def _main():
_mark_changed    member       81 app/plugins/progress_live.py def _mark_changed(self) -> None:
_meta_cache      variable     18 app/plugins/post_templates.py _meta_cache = None
_msg             function     52 app/plugins/batch_links.py async def _msg(evt):
_off             function     37 app/plugins/batch_links.py async def _off(evt):
_on              function     28 app/plugins/batch_links.py async def _on(evt):
_parse_accounts_env function     28 app/services/account_pool.py def _parse_accounts_env() -> List[str]:
_parse_add_args  function    206 app/plugins/post_templates.py def _parse_add_args(arg_str: str):
_plausible_invite_hash function     48 app/services/joiner.py def _plausible_invite_hash(h: str | None) -> bool:
_record_meta     function     43 app/plugins/post_templates.py def _record_meta(tid: int, chat_id: int, message_id: int, has_media: bool):
_render          member      113 app/plugins/progress_live.py def _render(self, header_suffix: str, final: bool = False) -> str:
_rr              variable     55 app/services/account_pool.py _rr = 0 # round-robin індекс
_save_meta       function     34 app/plugins/post_templates.py def _save_meta():
_session_name    unknown       7 app/flows/batch_links/queue_worker.py iter_pool_clients, mark_flood, mark_limit, session_name as _session_name,
_set_ready_after function     80 app/services/account_pool.py def _set_ready_after(slot: ClientSlot, seconds: int) -> None:
_short_pause     function     50 app/flows/batch_links/process_links.py async def _short_pause():
_sleep           function    105 app/flows/batch_links/queue_worker.py async def _sleep(sec: int):
_status          function     46 app/plugins/batch_links.py async def _status(evt):
a/app/flows/batch_links/process_links.py modifiedFile    3 fix-process_links.patch --- a/app/flows/batch_links/process_links.py
actor            variable     30 app/plugins/progress_live.py actor: str = "" # session/slot label
add_context      member       56 app/logging_json.py def add_context(self, **ctx):
add_span         function     35 ...43534.py      def add_span(off: int, ln: int, start_tag: str, end_tag: str):
add_span         function    118 app/plugins/post_templates.py def add_span(off: int, ln: int, start_tag: str, end_tag: str):
add_status       member       53 app/plugins/progress_live.py def add_status(self, status: str) -> None:
add_template     function     52 app/services/post_watch_db.py def add_template(
already          variable     26 app/plugins/progress_live.py already: int = 0
any_final_for_channel function    133 app/services/membership_db.py def any_final_for_channel(channel_id: int) -> Optional[str]:
append_summary_row function     28 app/services/gsheets.py def append_summary_row(row: list) -> bool:
bad              variable     27 app/plugins/progress_live.py bad: int = 0 # invalid/private/error
bump_cooldown    function     86 app/services/account_pool.py def bump_cooldown(client: TelegramClient, seconds: int) -> None:
busy             variable     50 app/services/account_pool.py busy: bool = False
cleanup_expired  function     59 app/services/db/bad_invites.py def cleanup_expired() -> int:
client           variable     12 app/telethon_client.py client = TelegramClient(SESSION, API_ID, API_HASH)
collapse_ws      function     26 app/utils/text_norm.py def collapse_ws(s: str) -> str:
configure_logging function    102 app/logging_json.py def configure_logging(force_json: Optional[bool] = None,
current          variable     29 app/plugins/progress_live.py current: str = "" # current url
debounce         variable     19 app/plugins/progress_live.py debounce: float = field(default_factory=lambda: float(_env("PROGRESS_DEBOUNCE", "3")))
display_name     function      4 app/flows/batch_links/common.py def display_name(slot) -> str:
done             variable     24 app/plugins/progress_live.py done: int = 0
enqueue          function     41 app/services/link_queue.py def enqueue(urls: List[str], batch_id: Optional[str], origin_chat: Optional[int], origin_msg: Optional[int], delay_sec: int = 0) -> int:
ensure_join      function    121 app/services/joiner.py async def ensure_join(client, url: str):
exact_match      function      9 app/services/post_match.py def exact_match(a: str, b: str) -> bool:
extract_links    function     86 app/utils/link_parser.py def extract_links(text: str) -> List[str]:
extract_links_any function    165 app/utils/link_parser.py def extract_links_any(msg_or_text: Union[str, "TgMessage"]) -> List[str]:
fetch_due        function     59 app/services/link_queue.py def fetch_due(limit: int = 20) -> List[Tuple[int,str,int,Optional[int],Optional[int]]]:
finish           member       72 app/plugins/progress_live.py async def finish(self, footer: str = "") -> None:
flood            variable     28 app/plugins/progress_live.py flood: int = 0
fmt_result_line  function     20 app/utils/formatting.py def fmt_result_line(idx: int, url: str, status: str, who: str | None = None, extra: str | None = None) -> str:
fmt_summary      function     26 app/utils/formatting.py def fmt_summary(results: Iterable[str]) -> str:
footer           variable     31 app/plugins/progress_live.py footer: str = "" # optional summary
format           member       10 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
format           member       37 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
fuzzy_match      function     19 app/services/post_match.py def fuzzy_match(a: str, b: str, threshold: float = 0.70) -> bool:
fuzzy_ratio      function     12 app/services/post_match.py def fuzzy_ratio(a: str, b: str) -> float:
get_logger       function    144 app/logging_json.py def get_logger(name: str, **context) -> StructuredAdapter:
get_membership   function    123 app/services/membership_db.py def get_membership(account: str, channel_id: int) -> Optional[str]:
gspread          variable      9 app/services/gsheets.py gspread = None
help_cmd         function     34 app/plugins/help_and_ping.py async def help_cmd(event):
init             function     32 app/services/link_queue.py def init(db_path: Optional[str] = None):
init             function     32 app/services/post_watch_db.py def init(db_path: Optional[str] = None):
init             function     65 app/services/membership_db.py def init(db_path: Optional[str] = None):
invite_status_get function    223 app/services/membership_db.py def invite_status_get(invite_or_hash: str) -> Optional[str]:
invite_status_put function    207 app/services/membership_db.py def invite_status_put(invite_or_hash: str, status: str) -> None:
is_already_subscribed function    200 app/services/account_pool.py async def is_already_subscribed(url: str) -> Optional[str]:
is_already_subscribed_any function     12 app/services/subscription_check.py async def is_already_subscribed_any(url: str) -> Optional[str]:
is_bad           function     38 app/services/db/bad_invites.py def is_bad(invite_hash: str) -> Tuple[bool, Optional[int], Optional[str]]:
is_invite        function     78 app/utils/link_parser.py def is_invite(url: str) -> bool:
iter_pool_clients function    167 app/services/account_pool.py def iter_pool_clients() -> List[ClientSlot]:
lease            function    182 app/services/account_pool.py async def lease() -> Optional[asyncio.AbstractAsyncContextManager]:
list_templates   function    105 app/services/post_watch_db.py def list_templates(limit: int = 50) -> List[Tuple[int, str, str, float, int]]:
list_templates_full function    117 app/services/post_watch_db.py def list_templates_full(limit: int = 50) -> List[Tuple[int, str, str, float, int, Optional[str], Optional[str]]]:
load_plugins     function     23 app/telethon_client.py async def load_plugins():
lock             variable     51 app/services/account_pool.py lock: asyncio.Lock = asyncio.Lock()
log              member       59 app/logging_json.py def log(self, level: int, msg: Any, *args, **kwargs):
log              variable      2 app/flows/batch_links/common.py log = logging.getLogger("flow.batch_links.common")
log              variable      8 ...43534.py      log = logging.getLogger("plugin.post_templates")
log              variable      8 app/utils/throttle.py log = logging.getLogger("utils.throttle")
log              variable     10 app/services/subscription_check.py log = logging.getLogger("services.subscription_check")
log              variable     10 app/telethon_client.py log = logging.getLogger("telethon_client")
log              variable     11 app/plugins/batch_links.py log = logging.getLogger("plugin.batch_links")
log              variable     12 app/plugins/post_templates.py log = logging.getLogger("plugin.post_templates")
log              variable     17 app/flows/batch_links/queue_worker.py log = logging.getLogger("flow.batch_links.worker")
log              variable     17 app/services/account_pool.py log = logging.getLogger("services.account_pool")
log              variable     21 app/services/joiner.py log = logging.getLogger("services.joiner")
log              variable     23 app/flows/batch_links/process_links.py log = logging.getLogger("flow.batch_links.process")
lq_enqueue       unknown      20 app/flows/batch_links/process_links.py from app.services.link_queue import enqueue as lq_enqueue
lq_fetch_due     unknown      13 app/flows/batch_links/queue_worker.py fetch_due as lq_fetch_due, mark_processing as lq_mark_processing,
lq_init          unknown       8 app/plugins/batch_links.py from app.services.link_queue import init as lq_init
lq_mark_done     unknown      14 app/flows/batch_links/queue_worker.py mark_done as lq_mark_done, mark_failed as lq_mark_failed,
lq_mark_failed   unknown      14 app/flows/batch_links/queue_worker.py mark_done as lq_mark_done, mark_failed as lq_mark_failed,
lq_mark_processing unknown      13 app/flows/batch_links/queue_worker.py fetch_due as lq_fetch_due, mark_processing as lq_mark_processing,
map_invite_get   function    176 app/services/membership_db.py def map_invite_get(invite_or_hash: str) -> Tuple[Optional[int], Optional[str]]:
map_invite_set   function    147 app/services/membership_db.py def map_invite_set(invite_or_hash: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
mark_bad         function     23 app/services/db/bad_invites.py def mark_bad(invite_hash: str, ttl_seconds: int = 43200, reason: str = "") -> None:
mark_done        function     74 app/services/link_queue.py def mark_done(item_id: int):
mark_failed      function     78 app/services/link_queue.py def mark_failed(item_id: int, error: str, backoff_sec: int, max_retries: int = 5):
mark_flood       function     95 app/services/account_pool.py def mark_flood(client: TelegramClient, seconds: int) -> None:
mark_limit       function    104 app/services/account_pool.py def mark_limit(client_or_slot: Union[TelegramClient, ClientSlot], days: int = 2) -> None:
mark_processing  function     70 app/services/link_queue.py def mark_processing(item_id: int):
memb_init        unknown       7 app/plugins/batch_links.py from app.services.membership_db import init as memb_init
mon_new          function     11 app/plugins/metrics_watch.py async def mon_new(event):
mon_start        function     31 app/plugins/metrics_watch.py async def mon_start(event):
mon_status       function     21 app/plugins/metrics_watch.py async def mon_status(event):
needle_clear     function     10 app/plugins/needle_reply.py async def needle_clear(event):
needle_from_reply function     22 app/plugins/needle_reply.py async def needle_from_reply(event):
needle_show      function     15 app/plugins/needle_reply.py async def needle_show(event):
next_ready       variable     49 app/services/account_pool.py next_ready: float = 0.0 # unix-ts, коли клієнт знову доступний
normalize        function     54 app/utils/link_parser.py def normalize(url: str) -> str:
normalize_soft   function     23 app/utils/text_norm.py def normalize_soft(s: str) -> str:
normalize_strict function     12 app/utils/text_norm.py def normalize_strict(s: str) -> str:
normalize_text   function      3 app/services/post_match.py def normalize_text(s: str) -> str:
notice           function      5 app/utils/notices.py async def notice(client, control_peer: str | int = CONTROL_PEER, text: str = ""):
ok               variable     25 app/plugins/progress_live.py ok: int = 0 # joined
parse_links      function     44 app/utils/tg_links.py def parse_links(text: str) -> List[str]:
ping_cmd         function     38 app/plugins/help_and_ping.py async def ping_cmd(event):
postwatch_init   unknown       6 main.py          from app.services.post_watch_db import init as postwatch_init # ⇦ додано
probe_channel_id function     64 app/services/joiner.py async def probe_channel_id(client, url: str):
process_links    function     77 app/flows/batch_links/process_links.py async def process_links(message, text: str):
pt_init          unknown       6 ...43534.py      from app.services.post_watch_db import init as pt_init, add_template, list_templates
pt_init          unknown      10 app/plugins/post_templates.py from app.services.post_watch_db import init as pt_init, add_template, list_templates
run_link_queue_worker function     19 app/flows/batch_links/queue_worker.py async def run_link_queue_worker(client):
sanitize_link    function     29 app/utils/tg_links.py def sanitize_link(u: str) -> str:
session_name     function     58 app/services/account_pool.py def session_name(client: TelegramClient) -> str:
set_current      member       46 app/plugins/progress_live.py def set_current(self, url: str | None = None, actor: str | None = None) -> None:
set_footer       member       68 app/plugins/progress_live.py def set_footer(self, text: str) -> None:
setup            function      4 app/plugins/needle_reply.py def setup(client, control_peer, monitor_buffer):
setup            function      5 app/plugins/metrics_watch.py def setup(client, control_peer, monitor_buffer):
setup            function     18 app/plugins/batch_links.py def setup(client, control_peer=None, monitor_buffer=None, **kwargs):
setup            function     27 app/plugins/help_and_ping.py def setup(client, control_peer, monitor_buffer):
setup            function    132 ...43534.py      def setup(client, control_peer=None, **kwargs):
setup            function    269 app/plugins/post_templates.py def setup(client, control_peer=None, **kwargs):
setup._add_tmpl  function    140 ...43534.py      async def _add_tmpl(evt):
setup._add_tmpl  function    277 app/plugins/post_templates.py async def _add_tmpl(evt):
setup._list      function    209 ...43534.py      async def _list(evt):
setup._list      function    379 app/plugins/post_templates.py async def _list(evt):
setup._msg       function     52 app/plugins/batch_links.py async def _msg(evt):
setup._off       function     37 app/plugins/batch_links.py async def _off(evt):
setup._on        function     28 app/plugins/batch_links.py async def _on(evt):
setup._status    function     46 app/plugins/batch_links.py async def _status(evt):
setup.help_cmd   function     34 app/plugins/help_and_ping.py async def help_cmd(event):
setup.mon_new    function     11 app/plugins/metrics_watch.py async def mon_new(event):
setup.mon_start  function     31 app/plugins/metrics_watch.py async def mon_start(event):
setup.mon_status function     21 app/plugins/metrics_watch.py async def mon_status(event):
setup.needle_clear function     10 app/plugins/needle_reply.py async def needle_clear(event):
setup.needle_from_reply function     22 app/plugins/needle_reply.py async def needle_from_reply(event):
setup.needle_show function     15 app/plugins/needle_reply.py async def needle_show(event):
setup.ping_cmd   function     38 app/plugins/help_and_ping.py async def ping_cmd(event):
setup_logging    function      9 main.py          def setup_logging():
start            member       40 app/plugins/progress_live.py async def start(self) -> None:
start_pool       function    140 app/services/account_pool.py async def start_pool() -> None:
stop_pool        function    161 app/services/account_pool.py async def stop_pool() -> None:
strip_invisible  function      5 app/utils/text_norm.py def strip_invisible(s: str) -> str:
tg_types         unknown       8 app/utils/link_parser.py from telethon.tl import types as tg_types
tg_types         variable     11 app/utils/link_parser.py tg_types = None
throttle_between_links function     68 app/utils/throttle.py async def throttle_between_links(kind: str | None, url: str = "") -> None:
throttle_invite  function     51 app/utils/throttle.py async def throttle_invite() -> None:
throttle_probe   function     38 app/utils/throttle.py async def throttle_probe(url: str = "") -> None:
throttle_public  function     59 app/utils/throttle.py async def throttle_public() -> None:
ttypes           unknown       4 ...43534.py      from telethon.tl import types as ttypes
ttypes           unknown       5 app/plugins/batch_links.py from telethon.tl import types as ttypes # для перевірки entities/markup
ttypes           unknown       7 app/flows/batch_links/process_links.py from telethon.tl import types as ttypes # ➕ для читання MessageEntityTextUrl
ttypes           unknown       7 app/plugins/post_templates.py from telethon.tl import types as ttypes
ttypes           unknown      19 ...43534.py      from telethon.tl import types as ttypes
upsert_membership function    115 app/services/membership_db.py def upsert_membership(account: str, channel_id: int, status: str):
url_get          function    249 app/services/membership_db.py def url_get(url: str) -> Optional[str]:
url_put          function    241 app/services/membership_db.py def url_put(url: str, status: str):
Запуск у PyCharm section      22 README.md        ## Запуск у PyCharm
Команди   section      12 README.md        ## Команди
Можливості section       3 README.md        ## Можливості
```

## Notes

- This file is generated. Do not edit manually.
- Adjust MAX_DEPTH or excludes in scripts/generate-project-map.sh as needed.
