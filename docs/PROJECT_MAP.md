# Project Map (auto-generated)

- Generated: 2025-09-16 07:53:30 UTC
- Branch: feature/owner-conflict-guard

## Structure (depth=4)

```text
.
├── ...43534.py
├── .env
├── .gitignore
├── README.md
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
│   │   ├── channel_info.py
│   │   ├── help_and_ping.py
│   │   ├── metrics_watch.py
│   │   ├── needle_reply.py
│   │   ├── owner_set.py
│   │   ├── post_templates.py
│   │   └── progress_live.py
│   ├── services
│   │   ├── __init__.py
│   │   ├── account_pool.py
│   │   ├── channel_db.py
│   │   ├── db
│   │   │   └── bad_invites.py
│   │   ├── gsheets.py
│   │   ├── joiner.py
│   │   ├── link_queue.py
│   │   ├── membership_db.py
│   │   ├── models.py
│   │   ├── post_match.py
│   │   ├── post_watch_db.py
│   │   ├── requested_reconciler.py
│   │   ├── requested_reconciler_db.py
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
├── filelist_clean.txt
├── filelist_sizes.tsv
├── main.py
├── post_watchdog.sqlite3
├── requirements.txt
└── scripts
    └── generate-project-map.sh

10 directories, 51 files
```

## Symbols index (functions/classes)

```text
API_HASH         variable      8 app/config.py    API_HASH = os.getenv("API_HASH", "")
API_HASH         variable     25 app/services/account_pool.py API_HASH = _env("API_HASH", "")
API_ID           variable      7 app/config.py    API_ID = int(os.getenv("API_ID", "0"))
API_ID           variable     24 app/services/account_pool.py API_ID = int(_env("API_ID", "0") or "0")
Architecture overview chapter       1 docs/ARCHITECTURE.md # Architecture overview
BATCH_LIMIT      variable     19 app/services/requested_reconciler.py BATCH_LIMIT = int(os.getenv("REQUESTED_RECONCILER_BATCH", "30") or "30")
Base             class        34 app/services/requested_reconciler_db.py class Base(DeclarativeBase):
Base             variable     67 app/services/models.py Base = declarative_base()
CASE_SENSITIVE   variable     23 app/config.py    CASE_SENSITIVE = os.getenv("CASE_SENSITIVE", "false").lower() in ("1", "true", "yes")
CONTROL_PEER     variable     11 app/config.py    CONTROL_PEER = os.getenv("CONTROL_CHAT", "")
CREATE_TABLE_SQL variable      9 app/services/link_queue.py CREATE_TABLE_SQL = """
ClientSlot       class        46 app/services/account_pool.py class ClientSlot:
ClientSlot.busy  variable     50 app/services/account_pool.py busy: bool = False
ClientSlot.lock  variable     51 app/services/account_pool.py lock: asyncio.Lock = asyncio.Lock()
ClientSlot.next_ready variable     49 app/services/account_pool.py next_ready: float = 0.0 # unix-ts, коли клієнт знову доступний
Configuration    section      18 docs/ARCHITECTURE.md ## Configuration
Credentials      variable     10 app/services/gsheets.py Credentials = None
DB_PATH          variable      6 app/services/link_queue.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable      6 app/services/post_watch_db.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable      7 app/services/membership_db.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable     22 app/services/requested_reconciler_db.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable     26 app/config.py    DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable     32 app/services/models.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
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
INDEXES          variable     27 app/services/link_queue.py INDEXES = {
INVITE_BACKOFF_BASE variable     26 app/services/requested_reconciler_db.py INVITE_BACKOFF_BASE = int(os.getenv("REQUESTED_INVITE_BACKOFF_BASE", "15")) # сек
INVITE_BACKOFF_MAX variable     27 app/services/requested_reconciler_db.py INVITE_BACKOFF_MAX = int(os.getenv("REQUESTED_INVITE_BACKOFF_MAX", "3600")) # сек
Integrations/externals section      15 docs/ARCHITECTURE.md ## Integrations/externals
InviteCheck      class        37 app/services/requested_reconciler_db.py class InviteCheck(Base):
InviteCheck      class       158 app/services/models.py class InviteCheck(Base):
InviteCheck.__repr__ member      185 app/services/models.py def __repr__(self) -> str:
InviteCheck.__table_args__ variable     46 app/services/requested_reconciler_db.py __table_args__ = (
InviteCheck.__table_args__ variable    179 app/services/models.py __table_args__ = (
InviteCheck.__tablename__ variable     38 app/services/requested_reconciler_db.py __tablename__ = "invite_check"
InviteCheck.__tablename__ variable    171 app/services/models.py __tablename__ = "invite_check"
InviteCheck.invite_hash variable     40 app/services/requested_reconciler_db.py invite_hash: Mapped[str] = mapped_column(String, nullable=False)
InviteCheck.invite_hash variable    174 app/services/models.py invite_hash = Column(Text, nullable=False)
InviteCheck.next_check_at variable     43 app/services/requested_reconciler_db.py next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
InviteCheck.next_check_at variable    176 app/services/models.py next_check_at = Column(Integer, nullable=False)
InviteCheck.noted_at variable     42 app/services/requested_reconciler_db.py noted_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
InviteCheck.noted_at variable    175 app/services/models.py noted_at = Column(Integer, nullable=False)
InviteCheck.session variable     41 app/services/requested_reconciler_db.py session: Mapped[str] = mapped_column(String, nullable=False)
InviteCheck.session variable    173 app/services/models.py session = Column(Text, nullable=False)
InviteCheck.tries variable     44 app/services/requested_reconciler_db.py tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
InviteCheck.tries variable    177 app/services/models.py tries = Column(Integer, nullable=False, default=0)
InviteMap        class       102 app/services/models.py class InviteMap(Base):
InviteMap.__repr__ member      118 app/services/models.py def __repr__(self) -> str:
InviteMap.__tablename__ variable    111 app/services/models.py __tablename__ = "invite_map"
InviteMap.channel_id variable    114 app/services/models.py channel_id = Column(Integer, nullable=True)
InviteMap.invite_hash variable    113 app/services/models.py invite_hash = Column(Text, primary_key=True)
InviteMap.title  variable    115 app/services/models.py title = Column(Text, nullable=True)
InviteMap.updated_at variable    116 app/services/models.py updated_at = Column(Integer, nullable=True)
InviteStatus     class       122 app/services/models.py class InviteStatus(Base):
InviteStatus.__repr__ member      136 app/services/models.py def __repr__(self) -> str:
InviteStatus.__tablename__ variable    130 app/services/models.py __tablename__ = "invite_status"
InviteStatus.invite_hash variable    132 app/services/models.py invite_hash = Column(Text, primary_key=True)
InviteStatus.status variable    133 app/services/models.py status = Column(Text, nullable=False)
InviteStatus.ts  variable    134 app/services/models.py ts = Column(Integer, nullable=False)
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
MONITOR_BUFFER   variable     15 app/telethon_client.py MONITOR_BUFFER = SimpleNamespace(
Membership       class        73 app/services/models.py class Membership(Base):
Membership.__repr__ member       98 app/services/models.py def __repr__(self) -> str:
Membership.__table_args__ variable     92 app/services/models.py __table_args__ = (
Membership.__tablename__ variable     85 app/services/models.py __tablename__ = "membership"
Membership.account variable     88 app/services/models.py account = Column(Text, nullable=False)
Membership.channel_id variable     87 app/services/models.py channel_id = Column(Integer, nullable=False)
Membership.status variable     89 app/services/models.py status = Column(Text, nullable=False)
Membership.ts    variable     90 app/services/models.py ts = Column(Integer, nullable=False)
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
REQ_BACKOFF_BASE variable     28 app/services/requested_reconciler_db.py REQ_BACKOFF_BASE = int(os.getenv("REQUESTED_BACKOFF_BASE", "30")) # сек
REQ_BACKOFF_MAX  variable     29 app/services/requested_reconciler_db.py REQ_BACKOFF_MAX = int(os.getenv("REQUESTED_BACKOFF_MAX", "3600")) # сек
RE_HTML_TG       variable     22 app/utils/link_parser.py RE_HTML_TG = re.compile(
RE_MD_TG         variable     16 app/utils/link_parser.py RE_MD_TG = re.compile(
RE_TG_RAW        variable     29 app/utils/link_parser.py RE_TG_RAW = re.compile(
RequestedCheck   class        51 app/services/requested_reconciler_db.py class RequestedCheck(Base):
RequestedCheck   class       192 app/services/models.py class RequestedCheck(Base):
RequestedCheck.__repr__ member      219 app/services/models.py def __repr__(self) -> str:
RequestedCheck.__table_args__ variable     60 app/services/requested_reconciler_db.py __table_args__ = (
RequestedCheck.__table_args__ variable    213 app/services/models.py __table_args__ = (
RequestedCheck.__tablename__ variable     52 app/services/requested_reconciler_db.py __tablename__ = "requested_check"
RequestedCheck.__tablename__ variable    205 app/services/models.py __tablename__ = "requested_check"
RequestedCheck.channel_id variable     55 app/services/requested_reconciler_db.py channel_id: Mapped[int] = mapped_column(Integer, nullable=False)
RequestedCheck.channel_id variable    208 app/services/models.py channel_id = Column(Integer, nullable=False)
RequestedCheck.next_check_at variable     57 app/services/requested_reconciler_db.py next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
RequestedCheck.next_check_at variable    210 app/services/models.py next_check_at = Column(Integer, nullable=False)
RequestedCheck.noted_at variable     56 app/services/requested_reconciler_db.py noted_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
RequestedCheck.noted_at variable    209 app/services/models.py noted_at = Column(Integer, nullable=False)
RequestedCheck.session variable     54 app/services/requested_reconciler_db.py session: Mapped[str] = mapped_column(String, nullable=False)
RequestedCheck.session variable    207 app/services/models.py session = Column(Text, nullable=False)
RequestedCheck.tries variable     58 app/services/requested_reconciler_db.py tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
RequestedCheck.tries variable    211 app/services/models.py tries = Column(Integer, nullable=False, default=0)
SESSION          variable      9 app/config.py    SESSION = os.getenv("SESSION_NAME", "tg_session")
SQLALCHEMY_DATABASE_URI variable     40 app/services/models.py SQLALCHEMY_DATABASE_URI = _mk_sqlite_url(DB_PATH)
SQLITE_URL       variable     23 app/services/requested_reconciler_db.py SQLITE_URL = f"sqlite:///{DB_PATH}"
STATUS_ICON      variable      5 app/utils/formatting.py STATUS_ICON = {
SessionLocal     variable     65 app/services/models.py SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
SessionLocal     variable     84 app/services/requested_reconciler_db.py SessionLocal = sessionmaker(bind=engine, class_=Session, autoflush=False, autocommit=False, future=True)
Structure (depth=4) section       6 docs/PROJECT_MAP.md ## Structure (depth=4)
StructuredAdapter class        52 app/logging_json.py class StructuredAdapter(logging.LoggerAdapter):
StructuredAdapter.__init__ member       53 app/logging_json.py def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
StructuredAdapter.add_context member       56 app/logging_json.py def add_context(self, **ctx):
StructuredAdapter.log member       59 app/logging_json.py def log(self, level: int, msg: Any, *args, **kwargs):
Symbols index (functions/classes) section      74 docs/PROJECT_MAP.md ## Symbols index (functions/classes)
TICK_SEC         variable     18 app/services/requested_reconciler.py TICK_SEC = int(os.getenv("REQUESTED_RECONCILER_TICK", "15") or "15")
Telegram Post Watchdog — v13 (Full) chapter       1 README.md        # Telegram Post Watchdog — v13 (Full)
TgMessage        unknown       9 app/utils/link_parser.py from telethon.tl.custom.message import Message as TgMessage
TgMessage        variable     12 app/utils/link_parser.py TgMessage = None # type: ignore
UrlCache         class       140 app/services/models.py class UrlCache(Base):
UrlCache.__repr__ member      154 app/services/models.py def __repr__(self) -> str:
UrlCache.__tablename__ variable    148 app/services/models.py __tablename__ = "url_cache"
UrlCache.status  variable    151 app/services/models.py status = Column(Text, nullable=False)
UrlCache.ts      variable    152 app/services/models.py ts = Column(Integer, nullable=False)
UrlCache.url     variable    150 app/services/models.py url = Column(Text, primary_key=True)
VERBOSE_NOTICES  variable      3 app/utils/notices.py VERBOSE_NOTICES = False # set True to see debug notices
WHOLE_WORD       variable     24 app/config.py    WHOLE_WORD = os.getenv("WHOLE_WORD", "false").lower() in ("1", "true", "yes")
_CONTROL_PEER_ID variable     10 ...43534.py      _CONTROL_PEER_ID = None
_CONTROL_PEER_ID variable     14 app/plugins/post_templates.py _CONTROL_PEER_ID = None
_CONTROL_PEER_ID variable     17 app/plugins/batch_links.py _CONTROL_PEER_ID = None
_DB_PATH         variable     65 app/services/channel_db.py _DB_PATH = (
_INVIS           variable     35 app/utils/link_parser.py _INVIS = ("\u200b", "\u200e", "\u200f")
_LINK_RE         variable     53 app/plugins/post_templates.py _LINK_RE = re.compile(
_META_PATH       variable     17 app/plugins/post_templates.py _META_PATH = "data/post_templates_meta.json"
_MONITOR_CHAT_ID variable     16 app/plugins/batch_links.py _MONITOR_CHAT_ID = None
_MONITOR_ENABLED variable     15 app/plugins/batch_links.py _MONITOR_ENABLED = False
_POOL            variable     53 app/services/account_pool.py _POOL: List[ClientSlot] = []
_POOL_LOCK       variable     54 app/services/account_pool.py _POOL_LOCK = asyncio.Lock()
_RESERVED        variable      7 app/logging_json.py _RESERVED = {"exc_info", "stack_info", "stacklevel", "extra"}
_TAG_RE          variable     91 app/plugins/post_templates.py _TAG_RE = re.compile(r"<[^>]+>")
_TG_RE           variable     37 app/utils/tg_links.py _TG_RE = re.compile(
_TRAIL_PUNCT     variable     36 app/utils/link_parser.py _TRAIL_PUNCT = ".,;:)]}>"
_TRIM_LEAD       variable      6 app/utils/tg_links.py _TRIM_LEAD = "(<[«\"' \u00A0\u200b\u200c\u200d\u2060"
_TRIM_TRAIL      variable      7 app/utils/tg_links.py _TRIM_TRAIL = ".,;:!?)]}>»\"' \u00A0\u200b\u200c\u200d\u2060"
__all__          variable      4 app/flows/batch_links/__init__.py __all__ = ["process_links", "run_link_queue_worker"]
__all__          variable     52 app/services/channel_db.py __all__ = [
__init__         member       53 app/logging_json.py def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
__repr__         member       98 app/services/models.py def __repr__(self) -> str:
__repr__         member      118 app/services/models.py def __repr__(self) -> str:
__repr__         member      136 app/services/models.py def __repr__(self) -> str:
__repr__         member      154 app/services/models.py def __repr__(self) -> str:
__repr__         member      185 app/services/models.py def __repr__(self) -> str:
__repr__         member      219 app/services/models.py def __repr__(self) -> str:
__table_args__   variable     46 app/services/requested_reconciler_db.py __table_args__ = (
__table_args__   variable     60 app/services/requested_reconciler_db.py __table_args__ = (
__table_args__   variable     92 app/services/models.py __table_args__ = (
__table_args__   variable    179 app/services/models.py __table_args__ = (
__table_args__   variable    213 app/services/models.py __table_args__ = (
__tablename__    variable     38 app/services/requested_reconciler_db.py __tablename__ = "invite_check"
__tablename__    variable     52 app/services/requested_reconciler_db.py __tablename__ = "requested_check"
__tablename__    variable     85 app/services/models.py __tablename__ = "membership"
__tablename__    variable    111 app/services/models.py __tablename__ = "invite_map"
__tablename__    variable    130 app/services/models.py __tablename__ = "invite_status"
__tablename__    variable    148 app/services/models.py __tablename__ = "url_cache"
__tablename__    variable    171 app/services/models.py __tablename__ = "invite_check"
__tablename__    variable    205 app/services/models.py __tablename__ = "requested_check"
_add_tmpl        function    140 ...43534.py      async def _add_tmpl(evt):
_add_tmpl        function    277 app/plugins/post_templates.py async def _add_tmpl(evt):
_bar             member      129 app/plugins/progress_live.py def _bar(done: int, total: int, width: int = 20) -> str:
_batch_cancel    function     84 app/plugins/batch_links.py async def _batch_cancel(evt):
_build_full_footer function     32 app/flows/batch_links/process_links.py def _build_full_footer(items: List[dict]) -> str:
_calc_next       function    109 app/services/requested_reconciler_db.py def _calc_next(base: int, tries: int, max_cap: int) -> int:
_canon           function     22 app/utils/tg_links.py def _canon(u: str) -> str:
_changed         variable     34 app/plugins/progress_live.py _changed: bool = False
_chat_allowed    function    157 app/plugins/channel_info.py def _chat_allowed(event) -> bool:
_check_invite_with_session function     42 app/services/requested_reconciler.py async def _check_invite_with_session(client, invite_hash: str) -> Optional[types.TypeMessage]:
_clamp_pair      function     16 app/utils/throttle.py def _clamp_pair(lo: float, hi: float) -> Tuple[float, float]:
_clean           function     39 app/utils/link_parser.py def _clean(s: str) -> str:
_client          function     12 app/services/gsheets.py def _client():
_client_by_session function     34 app/services/requested_reconciler.py def _client_by_session(sess: str):
_closed          variable     37 app/plugins/progress_live.py _closed: bool = False
_cmd_channel_info function    104 app/plugins/channel_info.py async def _cmd_channel_info(event: events.NewMessage.Event):
_cmd_channels_help function    140 app/plugins/channel_info.py async def _cmd_channels_help(event: events.NewMessage.Event):
_cmd_channels_owner function     53 app/plugins/channel_info.py async def _cmd_channels_owner(event: events.NewMessage.Event):
_cmd_recent_channels function     72 app/plugins/channel_info.py async def _cmd_recent_channels(event: events.NewMessage.Event):
_cmd_recent_links function     89 app/plugins/channel_info.py async def _cmd_recent_links(event: events.NewMessage.Event):
_collect_links   function     57 app/plugins/post_templates.py def _collect_links(msg, html_text: str) -> list:
_column_exists   function     25 app/services/post_watch_db.py def _column_exists(c: sqlite3.Connection, table: str, column: str) -> bool:
_conn            function     20 app/services/post_watch_db.py def _conn():
_conn            function     36 app/services/link_queue.py def _conn():
_conn            function     50 app/services/membership_db.py def _conn():
_conn            variable     71 app/services/channel_db.py _conn: Optional[sqlite3.Connection] = None
_debounced_edit  member       89 app/plugins/progress_live.py async def _debounced_edit(self) -> None:
_edit            member       99 app/plugins/progress_live.py async def _edit(self, final: bool) -> None:
_engine          variable     44 app/services/models.py _engine: Engine = create_engine(
_ensure_bad_invites_table function      8 app/services/db/bad_invites.py def _ensure_bad_invites_table() -> None:
_ensure_conn     function     82 app/services/channel_db.py def _ensure_conn() -> sqlite3.Connection:
_ensure_connected function    114 app/services/account_pool.py async def _ensure_connected(slot: ClientSlot) -> None:
_env             function      5 app/plugins/progress_live.py def _env(name: str, default: str = "") -> str:
_env             function     20 app/services/account_pool.py def _env(name: str, default: str = "") -> str:
_env_bool        function     96 app/logging_json.py def _env_bool(name: str, default: bool) -> bool:
_esc             function     16 app/plugins/channel_info.py def _esc(s: Optional[str]) -> str:
_escape          unknown       2 ...43534.py      from html import escape as _escape
_escape          unknown       5 app/plugins/post_templates.py from html import escape as _escape
_escape          unknown       6 app/flows/batch_links/process_links.py from html import escape as _escape
_escape          unknown      18 ...43534.py      from html import escape as _escape
_extract_args    function     44 app/plugins/channel_info.py def _extract_args(raw: str, command: str) -> str:
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
_guarded         function    162 app/plugins/channel_info.py async def _guarded(handler, event):
_has_column      function     56 app/services/membership_db.py def _has_column(c: sqlite3.Connection, table: str, col: str) -> bool:
_index_exists    function     42 app/services/link_queue.py def _index_exists(c: sqlite3.Connection, name: str) -> bool:
_is_high         function     96 ...43534.py      def _is_high(c: str) -> bool:
_is_high         function    177 app/plugins/post_templates.py def _is_high(c: str) -> bool:
_is_low          function    100 ...43534.py      def _is_low(c: str) -> bool:
_is_low          function    180 app/plugins/post_templates.py def _is_low(c: str) -> bool:
_last_render     variable     36 app/plugins/progress_live.py _last_render: str = ""
_lease_ctx       function    174 app/services/account_pool.py async def _lease_ctx(slot: ClientSlot):
_list            function    209 ...43534.py      async def _list(evt):
_list            function    379 app/plugins/post_templates.py async def _list(evt):
_load_meta       function     20 app/plugins/post_templates.py def _load_meta():
_lock            variable     72 app/services/channel_db.py _lock = threading.Lock()
_main            function     20 main.py          async def _main():
_mark_changed    member       81 app/plugins/progress_live.py def _mark_changed(self) -> None:
_meta_cache      variable     18 app/plugins/post_templates.py _meta_cache = None
_mk_sqlite_url   function     34 app/services/models.py def _mk_sqlite_url(path: str) -> str:
_msg             function    124 app/plugins/batch_links.py async def _msg(evt):
_norm_user       function     23 app/flows/batch_links/queue_worker.py def _norm_user(u: Optional[str]) -> Optional[str]:
_norm_user       function     86 app/flows/batch_links/process_links.py def _norm_user(u: Optional[str]) -> Optional[str]:
_now             function     78 app/services/channel_db.py def _now() -> str:
_now             function    106 app/services/requested_reconciler_db.py def _now() -> int:
_off             function     59 app/plugins/batch_links.py async def _off(evt):
_on              function     46 app/plugins/batch_links.py async def _on(evt):
_on_owner_clear  function     78 app/plugins/owner_set.py async def _on_owner_clear(event):
_on_owner_set    function     18 app/plugins/owner_set.py async def _on_owner_set(event):
_owner_conflict  function     29 app/flows/batch_links/queue_worker.py def _owner_conflict(channel_id: Optional[int],
_owner_conflict  function     92 app/flows/batch_links/process_links.py def _owner_conflict(channel_id: Optional[int],
_owner_skip      function     97 app/plugins/batch_links.py async def _owner_skip(evt):
_parse_accounts_env function     28 app/services/account_pool.py def _parse_accounts_env() -> List[str]:
_parse_add_args  function    206 app/plugins/post_templates.py def _parse_add_args(arg_str: str):
_parse_int       function     22 app/plugins/channel_info.py def _parse_int(maybe: Optional[str], default: int, min_v=1, max_v=200) -> int:
_plausible_invite_hash function     48 app/services/joiner.py def _plausible_invite_hash(h: str | None) -> bool:
_pool_sessions   function     22 app/services/requested_reconciler.py def _pool_sessions() -> List[str]:
_record_meta     function     43 app/plugins/post_templates.py def _record_meta(tid: int, chat_id: int, message_id: int, has_media: bool):
_render          member      113 app/plugins/progress_live.py def _render(self, header_suffix: str, final: bool = False) -> str:
_reply           function     34 app/plugins/channel_info.py async def _reply(msg: Message, text: str):
_rr              variable     55 app/services/account_pool.py _rr = 0 # round-robin індекс
_save_meta       function     34 app/plugins/post_templates.py def _save_meta():
_session_name    unknown       7 app/flows/batch_links/queue_worker.py iter_pool_clients, mark_flood, mark_limit, session_name as _session_name,
_session_name    unknown      16 app/flows/batch_links/process_links.py iter_pool_clients, bump_cooldown, mark_flood, mark_limit, session_name as _session_name
_set_ready_after function     80 app/services/account_pool.py def _set_ready_after(slot: ClientSlot, seconds: int) -> None:
_set_sqlite_pragma function     75 app/services/requested_reconciler_db.py def _set_sqlite_pragma(dbapi_conn, connection_record):
_short_pause     function     47 app/flows/batch_links/process_links.py async def _short_pause():
_sleep           function    374 app/flows/batch_links/queue_worker.py async def _sleep(sec: int):
_sqlite_pragmas  function     53 app/services/models.py def _sqlite_pragmas(dbapi_conn, _):
_status          function     71 app/plugins/batch_links.py async def _status(evt):
_table_exists    function     47 app/services/link_queue.py def _table_exists(c: sqlite3.Connection, name: str) -> bool:
account          variable     88 app/services/models.py account = Column(Text, nullable=False)
actor            variable     30 app/plugins/progress_live.py actor: str = "" # session/slot label
add_context      member       56 app/logging_json.py def add_context(self, **ctx):
add_link         function    225 app/services/channel_db.py def add_link(
add_span         function     35 ...43534.py      def add_span(off: int, ln: int, start_tag: str, end_tag: str):
add_span         function    118 app/plugins/post_templates.py def add_span(off: int, ln: int, start_tag: str, end_tag: str):
add_status       member       53 app/plugins/progress_live.py def add_status(self, status: str) -> None:
add_template     function     52 app/services/post_watch_db.py def add_template(
already          variable     26 app/plugins/progress_live.py already: int = 0
any_final_for_channel function    133 app/services/membership_db.py def any_final_for_channel(channel_id: int) -> Optional[str]:
append_summary_row function     28 app/services/gsheets.py def append_summary_row(row: list) -> bool:
backoff_invite_miss function    162 app/services/requested_reconciler_db.py def backoff_invite_miss(session: str, invite_hash: str) -> None:
backoff_miss     function    237 app/services/requested_reconciler_db.py def backoff_miss(session: str, channel_id: int) -> None:
bad              variable     27 app/plugins/progress_live.py bad: int = 0 # invalid/private/error
bump_cooldown    function     86 app/services/account_pool.py def bump_cooldown(client: TelegramClient, seconds: int) -> None:
busy             variable     50 app/services/account_pool.py busy: bool = False
channel_id       variable     55 app/services/requested_reconciler_db.py channel_id: Mapped[int] = mapped_column(Integer, nullable=False)
channel_id       variable     87 app/services/models.py channel_id = Column(Integer, nullable=False)
channel_id       variable    114 app/services/models.py channel_id = Column(Integer, nullable=True)
channel_id       variable    208 app/services/models.py channel_id = Column(Integer, nullable=False)
cleanup_expired  function     59 app/services/db/bad_invites.py def cleanup_expired() -> int:
clear            function    255 app/services/requested_reconciler_db.py def clear(session: str, channel_id: int) -> None:
clear_invite     function    179 app/services/requested_reconciler_db.py def clear_invite(session: str, invite_hash: str) -> None:
client           variable     11 app/telethon_client.py client = TelegramClient(SESSION, API_ID, API_HASH)
collapse_ws      function     26 app/utils/text_norm.py def collapse_ws(s: str) -> str:
configure_logging function    102 app/logging_json.py def configure_logging(force_json: Optional[bool] = None,
current          variable     29 app/plugins/progress_live.py current: str = "" # current url
debounce         variable     19 app/plugins/progress_live.py debounce: float = field(default_factory=lambda: float(_env("PROGRESS_DEBOUNCE", "3")))
display_name     function      4 app/flows/batch_links/common.py def display_name(slot) -> str:
done             variable     24 app/plugins/progress_live.py done: int = 0
due_invites      function    142 app/services/requested_reconciler_db.py def due_invites(sessions: Sequence[str], limit: int) -> List[InviteCheck]:
due_requested    function    215 app/services/requested_reconciler_db.py def due_requested(sessions: Sequence[str], per_account: int, limit: int) -> List[RequestedCheck]:
engine           variable     66 app/services/requested_reconciler_db.py engine = create_engine(
enqueue          function     97 app/services/link_queue.py def enqueue(
ensure_join      function    121 app/services/joiner.py async def ensure_join(client, url: str):
exact_match      function      9 app/services/post_match.py def exact_match(a: str, b: str) -> bool:
extract_links    function     86 app/utils/link_parser.py def extract_links(text: str) -> List[str]:
extract_links_any function    165 app/utils/link_parser.py def extract_links_any(msg_or_text: Union[str, "TgMessage"]) -> List[str]:
fetch_due        function    137 app/services/link_queue.py def fetch_due(limit: int = 20) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
find_channel     function    280 app/services/channel_db.py def find_channel(channel_id: int) -> Optional[Dict[str, Any]]:
finish           member       72 app/plugins/progress_live.py async def finish(self, footer: str = "") -> None:
flood            variable     28 app/plugins/progress_live.py flood: int = 0
fmt_result_line  function     20 app/utils/formatting.py def fmt_result_line(idx: int, url: str, status: str, who: str | None = None, extra: str | None = None) -> str:
fmt_summary      function     26 app/utils/formatting.py def fmt_summary(results: Iterable[str]) -> str:
footer           variable     31 app/plugins/progress_live.py footer: str = "" # optional summary
format           member       10 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
format           member       37 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
fuzzy_match      function     19 app/services/post_match.py def fuzzy_match(a: str, b: str, threshold: float = 0.70) -> bool:
fuzzy_ratio      function     12 app/services/post_match.py def fuzzy_ratio(a: str, b: str) -> float:
get_channels_by_owner function    257 app/services/channel_db.py def get_channels_by_owner(owner: str, limit: int = 50) -> List[Tuple]:
get_engine       function    229 app/services/models.py def get_engine() -> Engine:
get_logger       function    144 app/logging_json.py def get_logger(name: str, **context) -> StructuredAdapter:
get_membership   function    123 app/services/membership_db.py def get_membership(account: str, channel_id: int) -> Optional[str]:
get_session_factory function    234 app/services/models.py def get_session_factory():
gspread          variable      9 app/services/gsheets.py gspread = None
help_cmd         function     34 app/plugins/help_and_ping.py async def help_cmd(event):
init             function     32 app/services/post_watch_db.py def init(db_path: Optional[str] = None):
init             function     52 app/services/link_queue.py def init(db_path: Optional[str] = None):
init             function     65 app/services/membership_db.py def init(db_path: Optional[str] = None):
init             function     89 app/services/requested_reconciler_db.py def init(db_path: Optional[str] = None) -> None:
init             function     92 app/services/channel_db.py def init() -> None:
init_db          function    258 app/services/models.py def init_db() -> None:
invite_hash      variable     40 app/services/requested_reconciler_db.py invite_hash: Mapped[str] = mapped_column(String, nullable=False)
invite_hash      variable    113 app/services/models.py invite_hash = Column(Text, primary_key=True)
invite_hash      variable    132 app/services/models.py invite_hash = Column(Text, primary_key=True)
invite_hash      variable    174 app/services/models.py invite_hash = Column(Text, nullable=False)
invite_status_get function    223 app/services/membership_db.py def invite_status_get(invite_or_hash: str) -> Optional[str]:
invite_status_put function    207 app/services/membership_db.py def invite_status_put(invite_or_hash: str, status: str) -> None:
is_already_subscribed function    200 app/services/account_pool.py async def is_already_subscribed(url: str) -> Optional[str]:
is_already_subscribed_any function     12 app/services/subscription_check.py async def is_already_subscribed_any(url: str) -> Optional[str]:
is_bad           function     38 app/services/db/bad_invites.py def is_bad(invite_hash: str) -> Tuple[bool, Optional[int], Optional[str]]:
is_invite        function     78 app/utils/link_parser.py def is_invite(url: str) -> bool:
is_requested     function    264 app/services/requested_reconciler_db.py def is_requested(session: str, channel_id: int) -> bool:
iter_pool_clients function    167 app/services/account_pool.py def iter_pool_clients() -> List[ClientSlot]:
lease            function    182 app/services/account_pool.py async def lease() -> Optional[asyncio.AbstractAsyncContextManager]:
list_templates   function    105 app/services/post_watch_db.py def list_templates(limit: int = 50) -> List[Tuple[int, str, str, float, int]]:
list_templates_full function    117 app/services/post_watch_db.py def list_templates_full(limit: int = 50) -> List[Tuple[int, str, str, float, int, Optional[str], Optional[str]]]:
load_plugins     function     22 app/telethon_client.py async def load_plugins():
lock             variable     51 app/services/account_pool.py lock: asyncio.Lock = asyncio.Lock()
log              member       59 app/logging_json.py def log(self, level: int, msg: Any, *args, **kwargs):
log              variable      2 app/flows/batch_links/common.py log = logging.getLogger("flow.batch_links.common")
log              variable      5 app/plugins/owner_set.py log = logging.getLogger("plugin.owner_set")
log              variable      8 ...43534.py      log = logging.getLogger("plugin.post_templates")
log              variable      8 app/utils/throttle.py log = logging.getLogger("utils.throttle")
log              variable      9 app/telethon_client.py log = logging.getLogger("telethon_client")
log              variable     10 app/services/subscription_check.py log = logging.getLogger("services.subscription_check")
log              variable     11 app/plugins/channel_info.py log = logging.getLogger("plugin.channel_info")
log              variable     12 app/plugins/post_templates.py log = logging.getLogger("plugin.post_templates")
log              variable     13 app/plugins/batch_links.py log = logging.getLogger("plugin.batch_links")
log              variable     16 app/services/requested_reconciler.py log = logging.getLogger("services.requested_reconciler")
log              variable     17 app/services/account_pool.py log = logging.getLogger("services.account_pool")
log              variable     17 app/services/requested_reconciler_db.py log = logging.getLogger("services.requested_reconciler.db")
log              variable     20 app/flows/batch_links/queue_worker.py log = logging.getLogger("flow.batch_links.worker")
log              variable     21 app/services/joiner.py log = logging.getLogger("services.joiner")
log              variable     26 app/services/models.py log = logging.getLogger("services.models")
log              variable     29 app/flows/batch_links/process_links.py log = logging.getLogger("flow.batch_links.process")
lq_enqueue       unknown      21 app/flows/batch_links/process_links.py from app.services.link_queue import enqueue as lq_enqueue
lq_fetch_due     unknown      13 app/flows/batch_links/queue_worker.py fetch_due as lq_fetch_due, mark_processing as lq_mark_processing,
lq_init          unknown       9 app/plugins/batch_links.py from app.services.link_queue import init as lq_init
lq_mark_done     unknown      14 app/flows/batch_links/queue_worker.py mark_done as lq_mark_done, mark_failed as lq_mark_failed,
lq_mark_failed   unknown      14 app/flows/batch_links/queue_worker.py mark_done as lq_mark_done, mark_failed as lq_mark_failed,
lq_mark_processing unknown      13 app/flows/batch_links/queue_worker.py fetch_due as lq_fetch_due, mark_processing as lq_mark_processing,
map_invite_get   function    176 app/services/membership_db.py def map_invite_get(invite_or_hash: str) -> Tuple[Optional[int], Optional[str]]:
map_invite_set   function    147 app/services/membership_db.py def map_invite_set(invite_or_hash: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
mark_bad         function     23 app/services/db/bad_invites.py def mark_bad(invite_hash: str, ttl_seconds: int = 43200, reason: str = "") -> None:
mark_done        function    163 app/services/link_queue.py def mark_done(item_id: int):
mark_failed      function    168 app/services/link_queue.py def mark_failed(item_id: int, error: str, backoff_sec: int, max_retries: int = 5):
mark_flood       function     95 app/services/account_pool.py def mark_flood(client: TelegramClient, seconds: int) -> None:
mark_limit       function    104 app/services/account_pool.py def mark_limit(client_or_slot: Union[TelegramClient, ClientSlot], days: int = 2) -> None:
mark_processing  function    158 app/services/link_queue.py def mark_processing(item_id: int):
memb_init        unknown       8 app/plugins/batch_links.py from app.services.membership_db import init as memb_init
mon_new          function     11 app/plugins/metrics_watch.py async def mon_new(event):
mon_start        function     31 app/plugins/metrics_watch.py async def mon_start(event):
mon_status       function     21 app/plugins/metrics_watch.py async def mon_status(event):
needle_clear     function     10 app/plugins/needle_reply.py async def needle_clear(event):
needle_from_reply function     22 app/plugins/needle_reply.py async def needle_from_reply(event):
needle_show      function     15 app/plugins/needle_reply.py async def needle_show(event):
next_check_at    variable     43 app/services/requested_reconciler_db.py next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
next_check_at    variable     57 app/services/requested_reconciler_db.py next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
next_check_at    variable    176 app/services/models.py next_check_at = Column(Integer, nullable=False)
next_check_at    variable    210 app/services/models.py next_check_at = Column(Integer, nullable=False)
next_ready       variable     49 app/services/account_pool.py next_ready: float = 0.0 # unix-ts, коли клієнт знову доступний
normalize        function     54 app/utils/link_parser.py def normalize(url: str) -> str:
normalize_soft   function     23 app/utils/text_norm.py def normalize_soft(s: str) -> str:
normalize_strict function     12 app/utils/text_norm.py def normalize_strict(s: str) -> str:
normalize_text   function      3 app/services/post_match.py def normalize_text(s: str) -> str:
note_requested   function    190 app/services/requested_reconciler_db.py def note_requested(session: str, channel_id: int, start_after_sec: int = 60) -> None:
note_requested_invite function    117 app/services/requested_reconciler_db.py def note_requested_invite(session: str, invite_hash: str, start_after_sec: int = 60) -> None:
noted_at         variable     42 app/services/requested_reconciler_db.py noted_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
noted_at         variable     56 app/services/requested_reconciler_db.py noted_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
noted_at         variable    175 app/services/models.py noted_at = Column(Integer, nullable=False)
noted_at         variable    209 app/services/models.py noted_at = Column(Integer, nullable=False)
notice           function      5 app/utils/notices.py async def notice(client, control_peer: str | int = CONTROL_PEER, text: str = ""):
ok               variable     25 app/plugins/progress_live.py ok: int = 0 # joined
orm_init_db      unknown      13 main.py          from app.services.models import init_db as orm_init_db
parse_links      function     44 app/utils/tg_links.py def parse_links(text: str) -> List[str]:
ping_cmd         function     38 app/plugins/help_and_ping.py async def ping_cmd(event):
postwatch_init   unknown       8 main.py          from app.services.post_watch_db import init as postwatch_init
probe_channel_id function     64 app/services/joiner.py async def probe_channel_id(client, url: str):
process_links    function    119 app/flows/batch_links/process_links.py async def process_links(message, text: str, owner_display: Optional[str] = None, owner_username: Optional[str] = None):
prune_orphan_links function    373 app/services/channel_db.py def prune_orphan_links(max_without_channel: int = 10000) -> int:
pt_init          unknown       6 ...43534.py      from app.services.post_watch_db import init as pt_init, add_template, list_templates
pt_init          unknown      10 app/plugins/post_templates.py from app.services.post_watch_db import init as pt_init, add_template, list_templates
raw_connection   function    406 app/services/channel_db.py def raw_connection() -> sqlite3.Connection:
rdb              unknown      12 app/services/requested_reconciler.py from app.services import requested_reconciler_db as rdb
recent_channels  function    329 app/services/channel_db.py def recent_channels(limit: int = 30) -> List[Tuple]:
recent_links     function    310 app/services/channel_db.py def recent_links(limit: int = 30) -> List[Tuple]:
reqdb            unknown      11 main.py          from app.services import requested_reconciler_db as reqdb
reqdb            unknown      18 app/flows/batch_links/queue_worker.py from app.services import requested_reconciler_db as reqdb
reqdb            unknown      27 app/flows/batch_links/process_links.py from app.services import requested_reconciler_db as reqdb
run_link_queue_worker function     62 app/flows/batch_links/queue_worker.py async def run_link_queue_worker(client):
run_requested_reconciler function     53 app/services/requested_reconciler.py async def run_requested_reconciler() -> None:
sanitize_link    function     29 app/utils/tg_links.py def sanitize_link(u: str) -> str:
search_channels_by_username function    349 app/services/channel_db.py def search_channels_by_username(substring: str, limit: int = 30) -> List[Tuple]:
session          variable     41 app/services/requested_reconciler_db.py session: Mapped[str] = mapped_column(String, nullable=False)
session          variable     54 app/services/requested_reconciler_db.py session: Mapped[str] = mapped_column(String, nullable=False)
session          variable    173 app/services/models.py session = Column(Text, nullable=False)
session          variable    207 app/services/models.py session = Column(Text, nullable=False)
session_name     function     58 app/services/account_pool.py def session_name(client: TelegramClient) -> str:
session_scope    function    239 app/services/models.py def session_scope() -> Iterator[Session]:
set_current      member       46 app/plugins/progress_live.py def set_current(self, url: str | None = None, actor: str | None = None) -> None:
set_footer       member       68 app/plugins/progress_live.py def set_footer(self, text: str) -> None:
setup            function      4 app/plugins/needle_reply.py def setup(client, control_peer, monitor_buffer):
setup            function      5 app/plugins/metrics_watch.py def setup(client, control_peer, monitor_buffer):
setup            function      8 app/plugins/owner_set.py def setup(client, control_peer=None, monitor_buffer=None, **kwargs):
setup            function     20 app/plugins/batch_links.py def setup(client, control_peer=None, monitor_buffer=None, **kwargs):
setup            function     27 app/plugins/help_and_ping.py def setup(client, control_peer, monitor_buffer):
setup            function    132 ...43534.py      def setup(client, control_peer=None, **kwargs):
setup            function    154 app/plugins/channel_info.py def setup(client, control_peer=None, **kwargs):
setup            function    269 app/plugins/post_templates.py def setup(client, control_peer=None, **kwargs):
setup._add_tmpl  function    140 ...43534.py      async def _add_tmpl(evt):
setup._add_tmpl  function    277 app/plugins/post_templates.py async def _add_tmpl(evt):
setup._batch_cancel function     84 app/plugins/batch_links.py async def _batch_cancel(evt):
setup._chat_allowed function    157 app/plugins/channel_info.py def _chat_allowed(event) -> bool:
setup._guarded   function    162 app/plugins/channel_info.py async def _guarded(handler, event):
setup._list      function    209 ...43534.py      async def _list(evt):
setup._list      function    379 app/plugins/post_templates.py async def _list(evt):
setup._msg       function    124 app/plugins/batch_links.py async def _msg(evt):
setup._off       function     59 app/plugins/batch_links.py async def _off(evt):
setup._on        function     46 app/plugins/batch_links.py async def _on(evt):
setup._on_owner_clear function     78 app/plugins/owner_set.py async def _on_owner_clear(event):
setup._on_owner_set function     18 app/plugins/owner_set.py async def _on_owner_set(event):
setup._owner_skip function     97 app/plugins/batch_links.py async def _owner_skip(evt):
setup._status    function     71 app/plugins/batch_links.py async def _status(evt):
setup.help_cmd   function     34 app/plugins/help_and_ping.py async def help_cmd(event):
setup.mon_new    function     11 app/plugins/metrics_watch.py async def mon_new(event):
setup.mon_start  function     31 app/plugins/metrics_watch.py async def mon_start(event):
setup.mon_status function     21 app/plugins/metrics_watch.py async def mon_status(event):
setup.needle_clear function     10 app/plugins/needle_reply.py async def needle_clear(event):
setup.needle_from_reply function     22 app/plugins/needle_reply.py async def needle_from_reply(event):
setup.needle_show function     15 app/plugins/needle_reply.py async def needle_show(event):
setup.ping_cmd   function     38 app/plugins/help_and_ping.py async def ping_cmd(event):
setup_logging    function     16 main.py          def setup_logging():
start            member       40 app/plugins/progress_live.py async def start(self) -> None:
start_pool       function    140 app/services/account_pool.py async def start_pool() -> None:
status           variable     89 app/services/models.py status = Column(Text, nullable=False)
status           variable    133 app/services/models.py status = Column(Text, nullable=False)
status           variable    151 app/services/models.py status = Column(Text, nullable=False)
stop_pool        function    161 app/services/account_pool.py async def stop_pool() -> None:
strip_invisible  function      5 app/utils/text_norm.py def strip_invisible(s: str) -> str:
tg_types         unknown       8 app/utils/link_parser.py from telethon.tl import types as tg_types
tg_types         variable     11 app/utils/link_parser.py tg_types = None
throttle_between_links function     68 app/utils/throttle.py async def throttle_between_links(kind: str | None, url: str = "") -> None:
throttle_invite  function     51 app/utils/throttle.py async def throttle_invite() -> None:
throttle_probe   function     38 app/utils/throttle.py async def throttle_probe(url: str = "") -> None:
throttle_public  function     59 app/utils/throttle.py async def throttle_public() -> None:
title            variable    115 app/services/models.py title = Column(Text, nullable=True)
tries            variable     44 app/services/requested_reconciler_db.py tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
tries            variable     58 app/services/requested_reconciler_db.py tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
tries            variable    177 app/services/models.py tries = Column(Integer, nullable=False, default=0)
tries            variable    211 app/services/models.py tries = Column(Integer, nullable=False, default=0)
ts               variable     90 app/services/models.py ts = Column(Integer, nullable=False)
ts               variable    134 app/services/models.py ts = Column(Integer, nullable=False)
ts               variable    152 app/services/models.py ts = Column(Integer, nullable=False)
ttypes           unknown       4 ...43534.py      from telethon.tl import types as ttypes
ttypes           unknown       6 app/plugins/batch_links.py from telethon.tl import types as ttypes # для перевірки entities/markup
ttypes           unknown       7 app/plugins/post_templates.py from telethon.tl import types as ttypes
ttypes           unknown       8 app/flows/batch_links/process_links.py from telethon.tl import types as ttypes # ➕ для читання MessageEntityTextUrl
ttypes           unknown      19 ...43534.py      from telethon.tl import types as ttypes
ttypes           unknown      55 app/flows/batch_links/process_links.py from telethon.tl import types as ttypes
updated_at       variable    116 app/services/models.py updated_at = Column(Integer, nullable=True)
upsert_channel   function    158 app/services/channel_db.py def upsert_channel(
upsert_membership function    115 app/services/membership_db.py def upsert_membership(account: str, channel_id: int, status: str):
url              variable    150 app/services/models.py url = Column(Text, primary_key=True)
url_get          function    249 app/services/membership_db.py def url_get(url: str) -> Optional[str]:
url_put          function    241 app/services/membership_db.py def url_put(url: str, status: str):
Запуск у PyCharm section      22 README.md        ## Запуск у PyCharm
Команди   section      12 README.md        ## Команди
Можливості section       3 README.md        ## Можливості
```

## Notes

- This file is generated. Do not edit manually.
- Adjust MAX_DEPTH or excludes in scripts/generate-project-map.sh as needed.
