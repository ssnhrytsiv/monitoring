# Project Map (auto-generated)

- Generated: 2025-11-30 11:27:16 UTC
- Branch: watcherchannels

## Structure (depth=4)

```text
.
├── .env
├── .gitignore
├── README.md
├── app
│   ├── __init__.py
│   ├── bot
│   │   ├── __init__.py
│   │   ├── handlers
│   │   │   ├── __init__.py
│   │   │   ├── active_watches.py
│   │   │   ├── create_watch.py
│   │   │   └── join_channels.py
│   │   ├── handlers1.py
│   │   ├── keyboards.py
│   │   ├── notifier.py
│   │   ├── processing_guard.py
│   │   ├── run.py
│   │   ├── services
│   │   │   ├── channels_repo.py
│   │   │   ├── templates_repo.py
│   │   │   └── watches_repo.py
│   │   ├── states.py
│   │   └── user_state.py
│   ├── config.py
│   ├── debug
│   │   ├── debug_post_diff_interactive.py
│   │   └── test_normalize_html_links_tony_bet.py
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
│   │   ├── monitor_links.py
│   │   ├── monitor_watch.py
│   │   ├── needle_reply.py
│   │   ├── owner_set.py
│   │   ├── post_templates.py
│   │   ├── posts_watch_listener.py
│   │   ├── progress_live.py
│   │   └── resolve_channel.py
│   ├── services
│   │   ├── __init__.py
│   │   ├── account_pool.py
│   │   ├── channel_db.py
│   │   ├── channel_facts.py
│   │   ├── channel_maps.py
│   │   ├── db
│   │   │   └── bad_invites.py
│   │   ├── feature
│   │   │   ├── __init__.py
│   │   │   ├── channel_seed.py
│   │   │   ├── seed.py
│   │   │   ├── seed_creator.py
│   │   │   ├── seed_db.py
│   │   │   ├── seed_post_db.py
│   │   │   └── seed_posts.py
│   │   ├── googlesheets
│   │   │   ├── channels_export_service.py
│   │   │   ├── channels_table.sql
│   │   │   └── export_channels_table.py
│   │   ├── gsheets.py
│   │   ├── gsheets_buffer.py
│   │   ├── gsheets_writer.py
│   │   ├── html_match.py
│   │   ├── html_render.py
│   │   ├── join_scheduler.py
│   │   ├── joiner.py
│   │   ├── link_queue.py
│   │   ├── membership_db.py
│   │   ├── models.py
│   │   ├── monitor_links_bridge.py
│   │   ├── owner_conflict_guard.py
│   │   ├── post_match.py
│   │   ├── post_matcher.py
│   │   ├── post_watch_db.py
│   │   ├── posts_watch_result_db.py
│   │   ├── requested_reconciler.py
│   │   ├── requested_reconciler_db.py
│   │   ├── subscription_check.py
│   │   └── time_utils.py
│   ├── settings.py
│   ├── telethon_client.py
│   └── utils
│       ├── __init__.py
│       ├── formatting.py
│       ├── link_parser.py
│       ├── notices.py
│       ├── text_norm.py
│       ├── tg_links.py
│       └── throttle.py
├── apply_anchored_patch.py
├── bot_create_watch.py
├── db_dump
│   └── post_watchdog.sqlite3
├── docs
│   ├── ARCHITECTURE.md
│   └── PROJECT_MAP.md
├── dump_schema.sh
├── main.py
├── patch_gsheets_buffer.diff
├── post_watchdog.sqlite3
├── posts_watch_result.sqlite3
├── requirements.txt
├── safe_apply_patch.py
├── schema_dump.txt
├── scripts
│   └── generate-project-map.sh
├── seed_channels.sqlite3
├── tg_session.session
├── tg_session_2.session
├── tg_session_3.session
├── tg_session_4.session
└── tree.txt

17 directories, 106 files
```

## Symbols index (functions/classes)

```text
API_HASH         variable      7 app/config.py    API_HASH = os.getenv("API_HASH", "")
API_HASH         variable     25 app/services/account_pool.py API_HASH = _env("API_HASH", "")
API_ID           variable      6 app/config.py    API_ID = int(os.getenv("API_ID", "0"))
API_ID           variable     24 app/services/account_pool.py API_ID = int(_env("API_ID", "0") or "0")
APPEND_CHUNK     variable     17 app/services/gsheets_buffer.py APPEND_CHUNK = 1000
Architecture overview chapter       1 docs/ARCHITECTURE.md # Architecture overview
BATCH_LIMIT      variable     25 app/services/requested_reconciler.py BATCH_LIMIT = int(os.getenv("REQUESTED_RECONCILER_BATCH", "90") or "90")
BLOCKED          variable     72 app/services/requested_reconciler.py BLOCKED = "blocked"
BULK_THRESHOLD_EVENTS variable     16 app/services/gsheets_buffer.py BULK_THRESHOLD_EVENTS = 600
Base             class        46 app/services/requested_reconciler_db.py class Base(DeclarativeBase):
Base             variable     67 app/services/models.py Base = declarative_base()
CASE_SENSITIVE   variable     20 app/config.py    CASE_SENSITIVE = os.getenv("CASE_SENSITIVE", "false").lower() in ("1", "true", "yes")
CFG_API_HASH     unknown      24 app/services/feature/seed_creator.py from app.config import API_ID as CFG_API_ID, API_HASH as CFG_API_HASH
CFG_API_HASH     variable     27 app/services/feature/seed_creator.py CFG_API_HASH = None
CFG_API_ID       unknown      24 app/services/feature/seed_creator.py from app.config import API_ID as CFG_API_ID, API_HASH as CFG_API_HASH
CFG_API_ID       variable     26 app/services/feature/seed_creator.py CFG_API_ID = None
CONTROL_PEER     variable     10 app/config.py    CONTROL_PEER = os.getenv("CONTROL_CHAT", "")
COVERAGE_POLL_TICK_SEC variable     51 app/plugins/posts_watch_listener.py COVERAGE_POLL_TICK_SEC = 30
CREATE_TABLE_SQL variable      9 app/services/link_queue.py CREATE_TABLE_SQL = """
CREATOR_SESSION_NAME variable     10 app/settings.py  CREATOR_SESSION_NAME = os.getenv('CREATOR_SESSION_NAME', 'tg_session_3')
CREATOR_SESSION_NAME variable     57 app/services/feature/seed_creator.py CREATOR_SESSION_NAME = getattr(settings, "CREATOR_SESSION_NAME", "tg_session_3")
ClientSlot       class        46 app/services/account_pool.py class ClientSlot:
ClientSlot.busy  variable     50 app/services/account_pool.py busy: bool = False
ClientSlot.lock  variable     51 app/services/account_pool.py lock: asyncio.Lock = asyncio.Lock()
ClientSlot.next_ready variable     49 app/services/account_pool.py next_ready: float = 0.0 # unix-ts, коли клієнт знову доступний
Configuration    section      18 docs/ARCHITECTURE.md ## Configuration
CreateWatch      class         8 app/bot/states.py class CreateWatch(StatesGroup):
CreateWatch.channel_input variable      9 app/bot/states.py channel_input = State()
CreateWatch.confirm variable     12 app/bot/states.py confirm = State()
CreateWatch.template_pick variable     10 app/bot/states.py template_pick = State()
CreateWatch.time_window variable     11 app/bot/states.py time_window = State()
Credentials      variable     11 app/services/gsheets.py Credentials = None
Credentials      variable     20 app/services/gsheets_writer.py Credentials = None # type: ignore
DB_PATH          variable      6 app/services/feature/seed_post_db.py DB_PATH = Path("./seed_posts.sqlite3")
DB_PATH          variable      6 app/services/link_queue.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable      6 app/services/post_watch_db.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable      7 app/services/membership_db.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable      9 app/services/feature/seed_db.py DB_PATH = Path("./seed_channels.sqlite3")
DB_PATH          variable     20 app/services/channel_facts.py DB_PATH = Path("./channels_meta.sqlite3")
DB_PATH          variable     21 app/services/requested_reconciler_db.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable     23 app/config.py    DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH          variable     32 app/services/models.py DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
DB_PATH_DEFAULT  variable     17 app/services/googlesheets/export_channels_table.py DB_PATH_DEFAULT = "post_watchdog.sqlite3"
DDL              variable      8 app/services/feature/seed_post_db.py DDL = r"""
DDL              variable      8 app/services/post_watch_db.py DDL = """
DDL              variable      9 app/services/membership_db.py DDL = """
DDL              variable     11 app/services/feature/seed_db.py DDL = r"""
DDL              variable     22 app/services/channel_facts.py DDL = r"""
DDL              variable     24 app/services/channel_maps.py DDL = r"""
DEFAULT_COVERAGE_HOURS variable     79 app/plugins/posts_watch_listener.py DEFAULT_COVERAGE_HOURS: float = _read_default_coverage_hours()
DEFAULT_DB       variable     14 app/services/channel_maps.py DEFAULT_DB = getattr(_S, "DB_FILE", "post_watchdog.sqlite3")
DEFAULT_DB       variable     16 app/services/channel_maps.py DEFAULT_DB = "post_watchdog.sqlite3"
DEFAULT_FIND_INTERVAL variable     13 app/config.py    DEFAULT_FIND_INTERVAL = os.getenv("DEFAULT_FIND_INTERVAL", "30m")
DEFAULT_FIND_WINDOW variable     15 app/config.py    DEFAULT_FIND_WINDOW = os.getenv("DEFAULT_FIND_WINDOW", "72h")
DEFAULT_FUZZ     variable     19 app/config.py    DEFAULT_FUZZ = int(os.getenv("DEFAULT_FUZZ", "85"))
DEFAULT_MODE     variable     18 app/config.py    DEFAULT_MODE = os.getenv("DEFAULT_MODE", "exact_strict")
DEFAULT_MON_INTERVAL variable     14 app/config.py    DEFAULT_MON_INTERVAL = os.getenv("DEFAULT_MON_INTERVAL", "1h")
DEFAULT_MON_WINDOW variable     16 app/config.py    DEFAULT_MON_WINDOW = os.getenv("DEFAULT_MON_WINDOW", "24h")
DELAY_BETWEEN_BATCHES variable     62 app/services/feature/seed_creator.py DELAY_BETWEEN_BATCHES = float(getattr(settings, "SEED_DELAY_BETWEEN_BATCHES", 20.0))
DELAY_BETWEEN_CREATES variable     61 app/services/feature/seed_creator.py DELAY_BETWEEN_CREATES = float(getattr(settings, "SEED_DELAY_BETWEEN_CREATES", 7.0))
Data/Control flow section      12 docs/ARCHITECTURE.md ## Data/Control flow
DebouncedProgress class        10 app/plugins/progress_live.py class DebouncedProgress:
DebouncedProgress._bar member      133 app/plugins/progress_live.py def _bar(done: int, total: int, width: int = 20) -> str:
DebouncedProgress._changed variable     35 app/plugins/progress_live.py _changed: bool = False
DebouncedProgress._closed variable     38 app/plugins/progress_live.py _closed: bool = False
DebouncedProgress._debounced_edit member       93 app/plugins/progress_live.py async def _debounced_edit(self) -> None:
DebouncedProgress._edit member      103 app/plugins/progress_live.py async def _edit(self, final: bool) -> None:
DebouncedProgress._last_render variable     37 app/plugins/progress_live.py _last_render: str = ""
DebouncedProgress._mark_changed member       85 app/plugins/progress_live.py def _mark_changed(self) -> None:
DebouncedProgress._render member      117 app/plugins/progress_live.py def _render(self, header_suffix: str, final: bool = False) -> str:
DebouncedProgress.actor variable     31 app/plugins/progress_live.py actor: str = "" # session/slot label
DebouncedProgress.add_status member       54 app/plugins/progress_live.py def add_status(self, status: str) -> None:
DebouncedProgress.already variable     27 app/plugins/progress_live.py already: int = 0
DebouncedProgress.bad variable     28 app/plugins/progress_live.py bad: int = 0 # invalid/private/error/temp/other
DebouncedProgress.current variable     30 app/plugins/progress_live.py current: str = "" # current url
DebouncedProgress.debounce variable     19 app/plugins/progress_live.py debounce: float = field(default_factory=lambda: float(_env("PROGRESS_DEBOUNCE", "3")))
DebouncedProgress.done variable     24 app/plugins/progress_live.py done: int = 0
DebouncedProgress.finish member       76 app/plugins/progress_live.py async def finish(self, footer: str = "") -> None:
DebouncedProgress.flood variable     29 app/plugins/progress_live.py flood: int = 0
DebouncedProgress.footer variable     32 app/plugins/progress_live.py footer: str = "" # optional summary
DebouncedProgress.ok variable     25 app/plugins/progress_live.py ok: int = 0 # joined
DebouncedProgress.requested variable     26 app/plugins/progress_live.py requested: int = 0 # requested (окремо від already)
DebouncedProgress.set_current member       47 app/plugins/progress_live.py def set_current(self, url: str | None = None, actor: str | None = None) -> None:
DebouncedProgress.set_footer member       72 app/plugins/progress_live.py def set_footer(self, text: str) -> None:
DebouncedProgress.start member       41 app/plugins/progress_live.py async def start(self) -> None:
DuplicateWatchError class       149 app/services/posts_watch_result_db.py class DuplicateWatchError(RuntimeError):
EVENT_TTL_SEC    variable     18 app/services/gsheets_buffer.py EVENT_TTL_SEC = 5.0
EXCLUDE_SESSIONS_FROM_JOIN variable     18 app/settings.py  EXCLUDE_SESSIONS_FROM_JOIN = os.getenv('EXCLUDE_SESSIONS_FROM_JOIN', 'tg_session_3')
FAIR_INVITES_FETCH variable     56 app/services/requested_reconciler.py FAIR_INVITES_FETCH = os.getenv("REQUESTED_RECONCILER_FAIR_INVITES_FETCH", "1") not in ("0", "false", "False")
FINAL_GLOBAL     variable     46 app/services/membership_db.py FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
FINAL_PER_ACC    variable     47 app/services/membership_db.py FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")
FLOOD_MAX_WAIT_SEC variable     54 app/services/requested_reconciler.py FLOOD_MAX_WAIT_SEC = int(os.getenv("REQUESTED_RECONCILER_FLOOD_MAX_WAIT", "3600") or "3600")
FLOOD_SLACK_SEC  variable     53 app/services/requested_reconciler.py FLOOD_SLACK_SEC = int(os.getenv("REQUESTED_RECONCILER_FLOOD_SLACK_SEC", "45") or "45")
GLOBAL_DELETED_TTL variable     54 app/plugins/posts_watch_listener.py GLOBAL_DELETED_TTL = 180.0
GSHEET_CHANNELS_SHEET variable     32 app/config.py    GSHEET_CHANNELS_SHEET= os.getenv("GSHEET_CHANNELS_SHEET", "Канали")
GSHEET_CHANNELS_SPREADSHEET_ID variable     31 app/config.py    GSHEET_CHANNELS_SPREADSHEET_ID= os.getenv("GSHEET_CHANNELS_SPREADSHEET_ID", "")
GSHEET_CREDS_FILE variable     26 app/config.py    GSHEET_CREDS_FILE = os.getenv("GSHEET_CREDS_FILE", "service_account.json")
GSHEET_JOBS_SHEET variable     27 app/config.py    GSHEET_JOBS_SHEET = os.getenv("GSHEET_JOBS_SHEET", "Jobs")
GSHEET_SPREADSHEET_ID variable     25 app/config.py    GSHEET_SPREADSHEET_ID = os.getenv("GSHEET_SPREADSHEET_ID", "")
GSHEET_SUMMARY_SHEET variable     28 app/config.py    GSHEET_SUMMARY_SHEET = os.getenv("GSHEET_SUMMARY_SHEET", "Summary")
GS_HEADER        unknown      34 app/plugins/monitor_watch.py from app.services.gsheets_writer import HEADER as GS_HEADER # type: ignore
GS_HEADER        variable     36 app/plugins/monitor_watch.py GS_HEADER = None # type: ignore
GS_HEADER        variable     40 app/plugins/monitor_watch.py GS_HEADER = None # type: ignore
HEADER           variable     25 app/services/gsheets_writer.py HEADER = [
HEADERS          variable     28 app/services/googlesheets/export_channels_table.py HEADERS = [
HELP_TEXT        variable     26 app/services/feature/channel_seed.py HELP_TEXT = (
HELP_TEXT_MD     variable      4 app/plugins/help_and_ping.py HELP_TEXT_MD = """\
HTML_CHANNEL     variable     18 app/debug/test_normalize_html_links_tony_bet.py HTML_CHANNEL = """
HTML_DB          variable      5 app/debug/test_normalize_html_links_tony_bet.py HTML_DB = """
High-level components section       8 docs/ARCHITECTURE.md ## High-level components
INDEXES          variable     27 app/services/link_queue.py INDEXES = {
INTER_DELAY_INV  variable     28 app/services/requested_reconciler.py INTER_DELAY_INV = float(os.getenv("REQUESTED_RECONCILER_INTER_DELAY_INVITE", "3.0") or "3.0")
INTER_DELAY_JITTER variable     30 app/services/requested_reconciler.py INTER_DELAY_JITTER = float(os.getenv("REQUESTED_RECONCILER_INTER_DELAY_JITTER", "0.3") or "0.3")
INTER_DELAY_REQ  variable     29 app/services/requested_reconciler.py INTER_DELAY_REQ = float(os.getenv("REQUESTED_RECONCILER_INTER_DELAY_REQUESTED", "1.0") or "1.0")
INVITE_BACKOFF_BASE variable     25 app/services/requested_reconciler_db.py INVITE_BACKOFF_BASE = int(os.getenv("REQUESTED_INVITE_BACKOFF_BASE", "15")) # сек
INVITE_BACKOFF_FACTOR variable     32 app/services/requested_reconciler_db.py INVITE_BACKOFF_FACTOR = float(os.getenv("REQUESTED_INVITE_BACKOFF_FACTOR", "2.0") or "2.0")
INVITE_BACKOFF_MAX variable     26 app/services/requested_reconciler_db.py INVITE_BACKOFF_MAX = int(os.getenv("REQUESTED_INVITE_BACKOFF_MAX", "3600")) # сек
INVITE_MIN_SPACING_FLOOR_SEC variable     44 app/services/requested_reconciler.py INVITE_MIN_SPACING_FLOOR_SEC = float(os.getenv("REQUESTED_RECONCILER_INVITE_MIN_SPACING_FLOOR_SEC", "40.0") or "40.0")
INVITE_MIN_SPACING_SEC variable     40 app/services/requested_reconciler.py INVITE_MIN_SPACING_SEC = float(os.getenv("REQUESTED_RECONCILER_INVITE_MIN_SPACING_SEC", "40.0") or "40.0")
INVITE_NOTE_DEBOUNCE_SEC variable     40 app/services/requested_reconciler_db.py INVITE_NOTE_DEBOUNCE_SEC = int(os.getenv("REQUESTED_RECONCILER_INVITE_NOTE_DEBOUNCE_SEC", "60") or "60")
INVITE_NOTE_RESET_LIMIT_PER_HOUR variable     41 app/services/requested_reconciler_db.py INVITE_NOTE_RESET_LIMIT_PER_HOUR = int(os.getenv("REQUESTED_RECONCILER_INVITE_RESET_LIMIT_PER_HOUR", "120") or "120")
INVITE_RECHECK_MIN_SEC variable     37 app/services/requested_reconciler_db.py INVITE_RECHECK_MIN_SEC = int(os.getenv("REQUESTED_RECONCILER_INVITE_RECHECK_MIN_SEC", "200") or "200")
INVITE_RL_MAX_CALLS variable     37 app/services/requested_reconciler.py INVITE_RL_MAX_CALLS = int(os.getenv("REQUESTED_RECONCILER_INVITE_RL_MAX_CALLS", "6") or "6")
INVITE_RL_WINDOW_SEC variable     38 app/services/requested_reconciler.py INVITE_RL_WINDOW_SEC = int(os.getenv("REQUESTED_RECONCILER_INVITE_RL_WINDOW_SEC", "600") or "600")
INVITE_SPACING_JITTER variable     42 app/services/requested_reconciler.py INVITE_SPACING_JITTER = float(os.getenv("REQUESTED_RECONCILER_INVITE_SPACING_JITTER", "0.0") or "0.0")
Integrations/externals section      15 docs/ARCHITECTURE.md ## Integrations/externals
InviteCheck      class        49 app/services/requested_reconciler_db.py class InviteCheck(Base):
InviteCheck      class       158 app/services/models.py class InviteCheck(Base):
InviteCheck.__repr__ member      185 app/services/models.py def __repr__(self) -> str:
InviteCheck.__table_args__ variable     58 app/services/requested_reconciler_db.py __table_args__ = (
InviteCheck.__table_args__ variable    179 app/services/models.py __table_args__ = (
InviteCheck.__tablename__ variable     50 app/services/requested_reconciler_db.py __tablename__ = "invite_check"
InviteCheck.__tablename__ variable    171 app/services/models.py __tablename__ = "invite_check"
InviteCheck.invite_hash variable     52 app/services/requested_reconciler_db.py invite_hash: Mapped[str] = mapped_column(String, nullable=False)
InviteCheck.invite_hash variable    174 app/services/models.py invite_hash = Column(Text, nullable=False)
InviteCheck.next_check_at variable     55 app/services/requested_reconciler_db.py next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
InviteCheck.next_check_at variable    176 app/services/models.py next_check_at = Column(Integer, nullable=False)
InviteCheck.noted_at variable     54 app/services/requested_reconciler_db.py noted_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
InviteCheck.noted_at variable    175 app/services/models.py noted_at = Column(Integer, nullable=False)
InviteCheck.session variable     53 app/services/requested_reconciler_db.py session: Mapped[str] = mapped_column(String, nullable=False)
InviteCheck.session variable    173 app/services/models.py session = Column(Text, nullable=False)
InviteCheck.tries variable     56 app/services/requested_reconciler_db.py tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
InviteCheck.tries variable    177 app/services/models.py tries = Column(Integer, nullable=False, default=0)
InviteCheckStatus class        61 app/services/requested_reconciler.py class InviteCheckStatus(Enum):
InviteCheckStatus.OK variable     62 app/services/requested_reconciler.py OK = "ok"
InviteCheckStatus.TERMINAL variable     64 app/services/requested_reconciler.py TERMINAL = "terminal"
InviteCheckStatus.TRANSIENT variable     63 app/services/requested_reconciler.py TRANSIENT = "transient"
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
JITTER_AFTER_COOLDOWN_PCT variable     42 app/services/join_scheduler.py JITTER_AFTER_COOLDOWN_PCT: Tuple[float, float] = (0.05, 0.15) # частка від FloodWait W
JITTER_CREATE_MAX variable     63 app/services/feature/seed_creator.py JITTER_CREATE_MIN, JITTER_CREATE_MAX = map(
JITTER_CREATE_MIN variable     63 app/services/feature/seed_creator.py JITTER_CREATE_MIN, JITTER_CREATE_MAX = map(
JITTER_IMMEDIATE_RANGE variable     41 app/services/join_scheduler.py JITTER_IMMEDIATE_RANGE: Tuple[float, float] = (0.0, 0.25) # сек коли токен є відразу
JITTER_TOKEN_WAIT_RANGE variable     40 app/services/join_scheduler.py JITTER_TOKEN_WAIT_RANGE: Tuple[float, float] = (0.2, 1.3) # сек при очікуванні токена / cooldown
JOIN_AFTER_FLOOD_HOLD_MAX variable     37 app/services/join_scheduler.py JOIN_AFTER_FLOOD_HOLD_MAX: int = int(getattr(_S, "JOIN_AFTER_FLOOD_HOLD_MAX", 300))
JOIN_AFTER_FLOOD_HOLD_MIN variable     36 app/services/join_scheduler.py JOIN_AFTER_FLOOD_HOLD_MIN: int = int(getattr(_S, "JOIN_AFTER_FLOOD_HOLD_MIN", 10))
JOIN_AFTER_FLOOD_HOLD_PCT variable     35 app/services/join_scheduler.py JOIN_AFTER_FLOOD_HOLD_PCT: float = float(getattr(_S, "JOIN_AFTER_FLOOD_HOLD_PCT", 0.10)) # 10% від W
JOIN_BURST       variable     25 app/services/join_scheduler.py JOIN_BURST: int = int(getattr(_S, "JOIN_BURST", 2)) # стартовий запас токенів
JOIN_GOOD_STREAK variable     32 app/services/join_scheduler.py JOIN_GOOD_STREAK: int = int(getattr(_S, "JOIN_GOOD_STREAK", 5))
JOIN_LIMIT_WINDOW variable     22 app/services/join_scheduler.py JOIN_LIMIT_WINDOW: int = int(getattr(_S, "JOIN_LIMIT_WINDOW", 600)) # 10 хв
JOIN_PRIVATE_CAP variable     24 app/services/join_scheduler.py JOIN_PRIVATE_CAP: int = int(getattr(_S, "JOIN_PRIVATE_CAP", 8)) # стартова місткість private
JOIN_PRIVATE_MAX variable     30 app/services/join_scheduler.py JOIN_PRIVATE_MAX: int = int(getattr(_S, "JOIN_PRIVATE_MAX", 20)) # <-- як просив: MAX=20
JOIN_PRIVATE_MIN variable     29 app/services/join_scheduler.py JOIN_PRIVATE_MIN: int = int(getattr(_S, "JOIN_PRIVATE_MIN", 3))
JOIN_PUBLIC_CAP  variable     23 app/services/join_scheduler.py JOIN_PUBLIC_CAP: int = int(getattr(_S, "JOIN_PUBLIC_CAP", 20)) # стартова місткість public
JOIN_PUBLIC_MAX  variable     28 app/services/join_scheduler.py JOIN_PUBLIC_MAX: int = int(getattr(_S, "JOIN_PUBLIC_MAX", 30))
JOIN_PUBLIC_MIN  variable     27 app/services/join_scheduler.py JOIN_PUBLIC_MIN: int = int(getattr(_S, "JOIN_PUBLIC_MIN", 6))
JSONFormatter    class         9 app/logging_json.py class JSONFormatter(logging.Formatter):
JSONFormatter.format member       10 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
JoinChannels     class         3 app/bot/states.py class JoinChannels(StatesGroup):
JoinChannels.await_action variable      5 app/bot/states.py await_action = State()
JoinChannels.channel_input variable      4 app/bot/states.py channel_input = State()
JoinChannels.owner_input variable      6 app/bot/states.py owner_input = State()
LINK_DELAY_INVITE_MAX variable     31 app/utils/throttle.py LINK_DELAY_INVITE_MAX = _f("LINK_DELAY_INVITE_MAX", "10")
LINK_DELAY_INVITE_MAX variable     35 app/utils/throttle.py LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX = _clamp_pair(LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX)
LINK_DELAY_INVITE_MIN variable     30 app/utils/throttle.py LINK_DELAY_INVITE_MIN = _f("LINK_DELAY_INVITE_MIN", "6")
LINK_DELAY_INVITE_MIN variable     35 app/utils/throttle.py LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX = _clamp_pair(LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX)
LINK_DELAY_PUBLIC_MAX variable     29 app/utils/throttle.py LINK_DELAY_PUBLIC_MAX = _f("LINK_DELAY_PUBLIC_MAX", "4")
LINK_DELAY_PUBLIC_MAX variable     34 app/utils/throttle.py LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX = _clamp_pair(LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX)
LINK_DELAY_PUBLIC_MIN variable     28 app/utils/throttle.py LINK_DELAY_PUBLIC_MIN = _f("LINK_DELAY_PUBLIC_MIN", "2")
LINK_DELAY_PUBLIC_MIN variable     34 app/utils/throttle.py LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX = _clamp_pair(LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX)
LOG_LEVEL        variable     37 app/config.py    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
MAIN_CLIENT      unknown      14 app/plugins/posts_watch_listener.py from app.telethon_client import client as MAIN_CLIENT
MAX_PER_10_MIN   variable     66 app/services/feature/seed_creator.py MAX_PER_10_MIN = int(getattr(settings, "SEED_MAX_PER_10_MIN", 15))
MEMBER           variable     68 app/services/requested_reconciler.py MEMBER = "member"
MIN_FLUSH_GAP_SEC variable     15 app/services/gsheets_buffer.py MIN_FLUSH_GAP_SEC = 5.0
MONITOR_BUFFER   variable     30 app/telethon_client.py MONITOR_BUFFER = SimpleNamespace(
MONITOR_LINKS_SHADOW variable      8 app/settings.py  MONITOR_LINKS_SHADOW = _truthy(os.getenv("MONITOR_LINKS_SHADOW", "0"))
MONITOR_LINKS_SHADOW variable     20 app/services/join_scheduler.py MONITOR_LINKS_SHADOW: bool = bool(getattr(_S, "MONITOR_LINKS_SHADOW", False))
MONITOR_LINKS_SHADOW variable     65 app/plugins/monitor_links.py MONITOR_LINKS_SHADOW: bool = bool(getattr(_S, "MONITOR_LINKS_SHADOW", False))
MONITOR_LINKS_V2 variable      7 app/settings.py  MONITOR_LINKS_V2 = _truthy(os.getenv("MONITOR_LINKS_V2", "0"))
MOSCOW_TZ        variable     12 app/services/gsheets_buffer.py MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MOSCOW_TZ        variable     43 app/services/gsheets_writer.py MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MOSCOW_TZ        variable     46 app/plugins/monitor_watch.py MOSCOW_TZ = ZoneInfo("Europe/Moscow") # єдина TZ для цього плагіна
MOSCOW_TZ        variable     47 app/services/posts_watch_result_db.py MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MOSCOW_TZ        variable     50 app/plugins/posts_watch_listener.py MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MSK_TZ           variable      4 app/services/time_utils.py MSK_TZ = pytz.timezone("Europe/Moscow")
MemberStatus     class        67 app/services/requested_reconciler.py class MemberStatus(Enum):
MemberStatus.BLOCKED variable     72 app/services/requested_reconciler.py BLOCKED = "blocked"
MemberStatus.MEMBER variable     68 app/services/requested_reconciler.py MEMBER = "member"
MemberStatus.NOT_MEMBER variable     69 app/services/requested_reconciler.py NOT_MEMBER = "not_member"
MemberStatus.PRIVATE variable     71 app/services/requested_reconciler.py PRIVATE = "private"
MemberStatus.TOO_MANY variable     73 app/services/requested_reconciler.py TOO_MANY = "too_many"
MemberStatus.TRANSIENT variable     70 app/services/requested_reconciler.py TRANSIENT = "transient"
Membership       class        73 app/services/models.py class Membership(Base):
Membership.__repr__ member       98 app/services/models.py def __repr__(self) -> str:
Membership.__table_args__ variable     92 app/services/models.py __table_args__ = (
Membership.__tablename__ variable     85 app/services/models.py __tablename__ = "membership"
Membership.account variable     88 app/services/models.py account = Column(Text, nullable=False)
Membership.channel_id variable     87 app/services/models.py channel_id = Column(Integer, nullable=False)
Membership.status variable     89 app/services/models.py status = Column(Text, nullable=False)
Membership.ts    variable     90 app/services/models.py ts = Column(Integer, nullable=False)
MsgSnapshot      class        23 app/debug/debug_post_diff_interactive.py class MsgSnapshot:
NOT_MEMBER       variable     69 app/services/requested_reconciler.py NOT_MEMBER = "not_member"
OK               variable     62 app/services/requested_reconciler.py OK = "ok"
OPS              variable     63 apply_anchored_patch.py OPS = {
Operational notes section      21 docs/ARCHITECTURE.md ## Operational notes
PER_SESSION_INVITES variable     33 app/services/requested_reconciler.py PER_SESSION_INVITES = int(os.getenv("REQUESTED_RECONCILER_PER_SESSION_INVITES", "20") or "20")
PER_SESSION_REQUESTED variable     34 app/services/requested_reconciler.py PER_SESSION_REQUESTED = int(os.getenv("REQUESTED_RECONCILER_PER_SESSION_REQUESTED", "20") or "20")
PLUGINS_PACKAGE  variable     35 app/config.py    PLUGINS_PACKAGE = "app.plugins"
POOL_SESSIONS    variable     42 app/services/account_pool.py POOL_SESSIONS = _parse_accounts_env()
POST_DB_PATH     unknown      23 app/services/feature/seed_posts.py from app.services.post_watch_db import DB_PATH as POST_DB_PATH # містить post_template
PRIMARY          variable     26 app/services/account_pool.py PRIMARY = _env("SESSION") or _env("SESSION_NAME") or "tg_session"
PRIVATE          variable     71 app/services/requested_reconciler.py PRIVATE = "private"
PROBE_DELAY_MAX  variable     25 app/utils/throttle.py PROBE_DELAY_MAX = _f("PROBE_DELAY_MAX", "1.10")
PROBE_DELAY_MAX  variable     33 app/utils/throttle.py PROBE_DELAY_MIN, PROBE_DELAY_MAX = _clamp_pair(PROBE_DELAY_MIN, PROBE_DELAY_MAX)
PROBE_DELAY_MIN  variable     24 app/utils/throttle.py PROBE_DELAY_MIN = _f("PROBE_DELAY_MIN", "0.45")
PROBE_DELAY_MIN  variable     33 app/utils/throttle.py PROBE_DELAY_MIN, PROBE_DELAY_MAX = _clamp_pair(PROBE_DELAY_MIN, PROBE_DELAY_MAX)
PlainFormatterClean class        48 app/logging_json.py class PlainFormatterClean(logging.Formatter):
PlainFormatterVerbose class        36 app/logging_json.py class PlainFormatterVerbose(logging.Formatter):
PlainFormatterVerbose.format member       37 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
Project Map (auto-generated) chapter       1 docs/PROJECT_MAP.md # Project Map (auto-generated)
Purpose          section       5 docs/ARCHITECTURE.md ## Purpose
REPORT_CHAT      variable     11 app/config.py    REPORT_CHAT = os.getenv("REPORT_CHAT", "")
REQUESTED_MIN_SPACING_FLOOR_SEC variable     51 app/services/requested_reconciler.py REQUESTED_MIN_SPACING_FLOOR_SEC = float(os.getenv("REQUESTED_RECONCILER_REQUESTED_MIN_SPACING_FLOOR_SEC", "0.8") or "0.8")
REQUESTED_MIN_SPACING_SEC variable     49 app/services/requested_reconciler.py REQUESTED_MIN_SPACING_SEC = float(os.getenv("REQUESTED_RECONCILER_REQUESTED_MIN_SPACING_SEC", "4.0") or "4.0")
REQUESTED_RL_MAX_CALLS variable     47 app/services/requested_reconciler.py REQUESTED_RL_MAX_CALLS = int(os.getenv("REQUESTED_RECONCILER_REQUESTED_RL_MAX_CALLS", "30") or "30")
REQUESTED_RL_WINDOW_SEC variable     48 app/services/requested_reconciler.py REQUESTED_RL_WINDOW_SEC = int(os.getenv("REQUESTED_RECONCILER_REQUESTED_RL_WINDOW_SEC", "600") or "600")
REQUESTED_SPACING_JITTER variable     50 app/services/requested_reconciler.py REQUESTED_SPACING_JITTER = float(os.getenv("REQUESTED_RECONCILER_REQUESTED_SPACING_JITTER", "0.7") or "0.7")
REQ_BACKOFF_BASE variable     27 app/services/requested_reconciler_db.py REQ_BACKOFF_BASE = int(os.getenv("REQUESTED_BACKOFF_BASE", "30")) # сек
REQ_BACKOFF_FACTOR variable     33 app/services/requested_reconciler_db.py REQ_BACKOFF_FACTOR = float(os.getenv("REQUESTED_BACKOFF_FACTOR", "5.0") or "5.0")
REQ_BACKOFF_MAX  variable     28 app/services/requested_reconciler_db.py REQ_BACKOFF_MAX = int(os.getenv("REQUESTED_BACKOFF_MAX", "3600")) # сек
RE_HTML_TG       variable     21 app/utils/link_parser.py RE_HTML_TG = re.compile(
RE_MD_TG         variable     15 app/utils/link_parser.py RE_MD_TG = re.compile(
RE_TG_RAW        variable     28 app/utils/link_parser.py RE_TG_RAW = re.compile(
RL_DEBUG         variable     58 app/services/requested_reconciler.py RL_DEBUG = os.getenv("REQUESTED_RECONCILER_RL_DEBUG", "0").lower() not in ("0", "false", "")
ROW_RANGE        variable     36 app/services/gsheets_writer.py ROW_RANGE = ("A", "I")
RequestedCheck   class        64 app/services/requested_reconciler_db.py class RequestedCheck(Base):
RequestedCheck   class       192 app/services/models.py class RequestedCheck(Base):
RequestedCheck.__repr__ member      219 app/services/models.py def __repr__(self) -> str:
RequestedCheck.__table_args__ variable     73 app/services/requested_reconciler_db.py __table_args__ = (
RequestedCheck.__table_args__ variable    213 app/services/models.py __table_args__ = (
RequestedCheck.__tablename__ variable     65 app/services/requested_reconciler_db.py __tablename__ = "requested_check"
RequestedCheck.__tablename__ variable    205 app/services/models.py __tablename__ = "requested_check"
RequestedCheck.channel_id variable     68 app/services/requested_reconciler_db.py channel_id: Mapped[int] = mapped_column(Integer, nullable=False)
RequestedCheck.channel_id variable    208 app/services/models.py channel_id = Column(Integer, nullable=False)
RequestedCheck.next_check_at variable     70 app/services/requested_reconciler_db.py next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
RequestedCheck.next_check_at variable    210 app/services/models.py next_check_at = Column(Integer, nullable=False)
RequestedCheck.noted_at variable     69 app/services/requested_reconciler_db.py noted_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
RequestedCheck.noted_at variable    209 app/services/models.py noted_at = Column(Integer, nullable=False)
RequestedCheck.session variable     67 app/services/requested_reconciler_db.py session: Mapped[str] = mapped_column(String, nullable=False)
RequestedCheck.session variable    207 app/services/models.py session = Column(Text, nullable=False)
RequestedCheck.tries variable     71 app/services/requested_reconciler_db.py tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
RequestedCheck.tries variable    211 app/services/models.py tries = Column(Integer, nullable=False, default=0)
SEED_DELAY_BETWEEN_BATCHES variable     13 app/settings.py  SEED_DELAY_BETWEEN_BATCHES = float(os.getenv('SEED_DELAY_BETWEEN_BATCHES', '20.0'))
SEED_DELAY_BETWEEN_CREATES variable     12 app/settings.py  SEED_DELAY_BETWEEN_CREATES = float(os.getenv('SEED_DELAY_BETWEEN_CREATES', '7.0'))
SEED_JITTER_CREATE variable     14 app/settings.py  SEED_JITTER_CREATE = os.getenv('SEED_JITTER_CREATE', '0.3,1.2')
SEED_MAX_PER_10_MIN variable     15 app/settings.py  SEED_MAX_PER_10_MIN = int(os.getenv('SEED_MAX_PER_10_MIN', '15'))
SEED_TARGET      variable     11 app/settings.py  SEED_TARGET = os.getenv('SEED_TARGET', 'tg_session')
SEED_TARGET      variable     58 app/services/feature/seed_creator.py SEED_TARGET = getattr(settings, "SEED_TARGET", "me") # дефолтно відправляємо у Saved Messages
SESSION          variable      8 app/config.py    SESSION = os.getenv("SESSION_NAME", "tg_session")
SHEETS_OK        variable     39 app/plugins/posts_watch_listener.py SHEETS_OK = False
SHEETS_OK        variable     43 app/plugins/posts_watch_listener.py SHEETS_OK = True
SHEET_NAME_DEFAULT variable     19 app/services/googlesheets/export_channels_table.py SHEET_NAME_DEFAULT = "Канали"
SQLALCHEMY_DATABASE_URI variable     40 app/services/models.py SQLALCHEMY_DATABASE_URI = _mk_sqlite_url(DB_PATH)
SQLITE_URL       variable     22 app/services/requested_reconciler_db.py SQLITE_URL = f"sqlite:///{DB_PATH}"
SQL_FILE_DEFAULT variable     18 app/services/googlesheets/export_channels_table.py SQL_FILE_DEFAULT = os.path.join(os.path.dirname(__file__), "channels_table.sql")
STATUS_ICON      variable      5 app/utils/formatting.py STATUS_ICON = {
STRICT_CONTROLLED_PLUGINS variable     19 app/telethon_client.py STRICT_CONTROLLED_PLUGINS = {
SessionLocal     variable     65 app/services/models.py SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
SessionLocal     variable     98 app/services/requested_reconciler_db.py SessionLocal = sessionmaker(bind=engine, class_=Session, autoflush=False, autocommit=False, future=True)
SessionState     class        89 app/services/join_scheduler.py class SessionState:
SessionState.__init__ member      100 app/services/join_scheduler.py def __init__(self, alias: str):
SessionState.__slots__ variable     90 app/services/join_scheduler.py __slots__ = (
SlidingWindowRateLimiter class       105 app/services/requested_reconciler.py class SlidingWindowRateLimiter:
SlidingWindowRateLimiter.__init__ member      106 app/services/requested_reconciler.py def __init__(
SlidingWindowRateLimiter._min_spacing_with_jitter member      152 app/services/requested_reconciler.py def _min_spacing_with_jitter(self) -> float:
SlidingWindowRateLimiter.acquire member      124 app/services/requested_reconciler.py async def acquire(self, key: str):
Structure (depth=4) section       6 docs/PROJECT_MAP.md ## Structure (depth=4)
StructuredAdapter class        52 app/logging_json.py class StructuredAdapter(logging.LoggerAdapter):
StructuredAdapter.__init__ member       53 app/logging_json.py def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
StructuredAdapter.add_context member       56 app/logging_json.py def add_context(self, **ctx):
StructuredAdapter.log member       59 app/logging_json.py def log(self, level: int, msg: Any, *args, **kwargs):
Symbols index (functions/classes) section     136 docs/PROJECT_MAP.md ## Symbols index (functions/classes)
TARGET_FLUSH_SEC variable     14 app/services/gsheets_buffer.py TARGET_FLUSH_SEC = 15.0
TERMINAL         variable     64 app/services/requested_reconciler.py TERMINAL = "terminal"
TICK_SEC         variable     24 app/services/requested_reconciler.py TICK_SEC = int(os.getenv("REQUESTED_RECONCILER_TICK", "60") or "60")
TOO_MANY         variable     73 app/services/requested_reconciler.py TOO_MANY = "too_many"
TRANSIENT        variable     63 app/services/requested_reconciler.py TRANSIENT = "transient"
TRANSIENT        variable     70 app/services/requested_reconciler.py TRANSIENT = "transient"
Telegram Post Watchdog — v13 (Full) chapter       1 README.md        # Telegram Post Watchdog — v13 (Full)
TgMessage        unknown       8 app/utils/link_parser.py from telethon.tl.custom.message import Message as TgMessage
TgMessage        variable     11 app/utils/link_parser.py TgMessage = None # type: ignore
TokenBucket      class        48 app/services/join_scheduler.py class TokenBucket:
TokenBucket.__init__ member       52 app/services/join_scheduler.py def __init__(self, cap: int, window_sec: int, init_tokens: float):
TokenBucket.__slots__ variable     50 app/services/join_scheduler.py __slots__ = ("cap", "tokens", "rate", "last_refill")
TokenBucket._refill member       64 app/services/join_scheduler.py def _refill(self):
TokenBucket.consume_one member       80 app/services/join_scheduler.py def consume_one(self):
TokenBucket.need_wait_seconds_for_one member       72 app/services/join_scheduler.py def need_wait_seconds_for_one(self) -> float:
TokenBucket.update_cap member       58 app/services/join_scheduler.py def update_cap(self, new_cap: int, window_sec: int):
USER_PROCESSING  variable      2 app/bot/user_state.py USER_PROCESSING = {}
UrlCache         class       140 app/services/models.py class UrlCache(Base):
UrlCache.__repr__ member      154 app/services/models.py def __repr__(self) -> str:
UrlCache.__tablename__ variable    148 app/services/models.py __tablename__ = "url_cache"
UrlCache.status  variable    151 app/services/models.py status = Column(Text, nullable=False)
UrlCache.ts      variable    152 app/services/models.py ts = Column(Integer, nullable=False)
UrlCache.url     variable    150 app/services/models.py url = Column(Text, primary_key=True)
VERBOSE_NOTICES  variable      3 app/utils/notices.py VERBOSE_NOTICES = False # set True to see debug notices
WATCH_VIEWS_ENABLED variable     39 app/config.py    WATCH_VIEWS_ENABLED = os.getenv("WATCH_VIEWS_ENABLED", "1").strip().lower() not in {"0","false","no","off"}
WHOLE_WORD       variable     21 app/config.py    WHOLE_WORD = os.getenv("WHOLE_WORD", "false").lower() in ("1", "true", "yes")
_                function     12 app/plugins/resolve_channel.py async def _(ev: events.NewMessage.Event):
_                function    175 app/plugins/monitor_watch.py async def _(ev: events.NewMessage.Event):
_ACTIVE          variable     56 app/plugins/monitor_links.py _ACTIVE = False
_ALIAS_TO_IDX    variable    114 app/services/join_scheduler.py _ALIAS_TO_IDX: Dict[str, int] = {}
_A_TAG_RE        variable    165 app/plugins/posts_watch_listener.py _A_TAG_RE = re.compile(r'<a\s+href=(?P<q1>"|\')(?P<href>.+?)(?P=q1)>(?P<body>.*?)</a>', re.DOTALL | re.IGNORECASE)
_BATCHES         variable     13 app/services/monitor_links_bridge.py _BATCHES: Dict[int, Dict[str, int]] = {}
_BOT             variable     18 app/services/monitor_links_bridge.py _BOT: Optional[Bot] = None
_CLIENT          variable     58 app/plugins/monitor_links.py _CLIENT = None
_CONN_OPTS       variable     19 app/services/channel_maps.py _CONN_OPTS = dict(check_same_thread=False, isolation_level=None) # autocommit
_CONTROL_PEER    variable     57 app/plugins/monitor_links.py _CONTROL_PEER: Optional[int] = None
_CONTROL_PEER_ID variable     14 app/plugins/post_templates.py _CONTROL_PEER_ID = None
_CONTROL_PEER_ID variable     17 app/plugins/batch_links.py _CONTROL_PEER_ID = None
_DB_PATH         variable     18 app/services/channel_maps.py _DB_PATH = Path(DEFAULT_DB)
_DB_PATH         variable     24 app/services/channel_db.py _DB_PATH = (
_DB_PATH         variable     38 app/services/posts_watch_result_db.py _DB_PATH = (
_FALLBACK_TME_RE variable     28 app/plugins/monitor_links.py _FALLBACK_TME_RE = re.compile(
_FALLBACK_TME_RE variable     70 app/bot/handlers/join_channels.py _FALLBACK_TME_RE = re.compile(
_GC              variable     38 app/services/gsheets_writer.py _GC = None
_GLOBAL_DELETED_SEEN variable     53 app/plugins/posts_watch_listener.py _GLOBAL_DELETED_SEEN: Dict[int, float] = {}
_GS_OK           variable     37 app/plugins/monitor_watch.py _GS_OK = True
_GS_OK           variable     41 app/plugins/monitor_watch.py _GS_OK = False
_HTML_RENDER     variable     90 app/plugins/posts_watch_listener.py _HTML_RENDER: Optional[Callable[[Message], str]] = None
_HTML_RENDER_SRC variable     91 app/plugins/posts_watch_listener.py _HTML_RENDER_SRC = None
_INVIS           variable     34 app/utils/link_parser.py _INVIS = ("\u200b", "\u200e", "\u200f")
_INVITE_RE       variable     46 app/services/feature/seed_posts.py _INVITE_RE = re.compile(r"https?://t\.me/\+([A-Za-z0-9_\-]+)")
_INV_RE          variable      9 app/bot/services/channels_repo.py _INV_RE = re.compile(r"(?:t\.me/(?:\+|joinchat/)|tg://join\?invite=)([A-Za-z0-9_-]{6,})")
_LINK_RE         variable     22 app/bot/handlers1.py _LINK_RE = re.compile(r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)')
_LINK_RE         variable     22 bot_create_watch.py _LINK_RE = re.compile(r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)')
_LINK_RE         variable     23 app/bot/handlers/create_watch.py _LINK_RE = re.compile(r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)')
_LINK_RE         variable     53 app/plugins/post_templates.py _LINK_RE = re.compile(
_LINK_RE         variable     67 app/bot/handlers/join_channels.py _LINK_RE = re.compile(r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)')
_META_PATH       variable     17 app/plugins/post_templates.py _META_PATH = "data/post_templates_meta.json"
_MONITOR_CHAT_ID variable     16 app/plugins/batch_links.py _MONITOR_CHAT_ID = None
_MONITOR_ENABLED variable     15 app/plugins/batch_links.py _MONITOR_ENABLED = False
_OWNER_DISPLAY   variable     62 app/plugins/monitor_links.py _OWNER_DISPLAY: Optional[str] = None
_OWNER_USERNAME  variable     61 app/plugins/monitor_links.py _OWNER_USERNAME: Optional[str] = None
_POOL            variable     53 app/services/account_pool.py _POOL: List[ClientSlot] = []
_POOL_LOCK       variable     54 app/services/account_pool.py _POOL_LOCK = asyncio.Lock()
_QUEUES          variable    112 app/services/join_scheduler.py _QUEUES: List[asyncio.Queue] = []
_RESERVED        variable      7 app/logging_json.py _RESERVED = {"exc_info", "stack_info", "stacklevel", "extra"}
_RE_WS           variable      8 app/services/html_match.py _RE_WS = re.compile(r"[ \t\r\f\v]+") # багаторазові пробіли (без \n)
_RR              variable    103 app/flows/batch_links/process_links.py _RR = _RoundRobinOrder()
_RoundRobinOrder class        49 app/flows/batch_links/process_links.py class _RoundRobinOrder:
_RoundRobinOrder.__init__ member       58 app/flows/batch_links/process_links.py def __init__(self) -> None:
_RoundRobinOrder._sid member       62 app/flows/batch_links/process_links.py def _sid(self, slot: Any) -> str:
_RoundRobinOrder.pick_order member       67 app/flows/batch_links/process_links.py def pick_order(self, slots: List[Any]) -> List[Any]:
_S               class        32 app/services/feature/seed_creator.py class _S: ...
_S               unknown      13 app/services/channel_maps.py from app import settings as _S
_S               unknown      13 app/services/join_scheduler.py from app import settings as _S # беремо з settings, але нижче маємо безпечні дефолти
_S               unknown      51 app/plugins/monitor_links.py from app import settings as _S
_SESSIONS        variable    111 app/services/join_scheduler.py _SESSIONS: List[Any] = []
_SH              variable     39 app/services/gsheets_writer.py _SH = None
_SHEETS_WITH_HEADER variable     41 app/services/gsheets_writer.py _SHEETS_WITH_HEADER: set[str] = set()
_STARTED         variable    115 app/services/join_scheduler.py _STARTED = False
_STATE           variable     12 app/services/googlesheets/channels_export_service.py _STATE = {
_STATE           variable    113 app/services/join_scheduler.py _STATE: List[SessionState] = []
_TAG_RE          variable     91 app/plugins/post_templates.py _TAG_RE = re.compile(r"<[^>]+>")
_TRAIL_PUNCT     variable     35 app/utils/link_parser.py _TRAIL_PUNCT = ".,;:)]}>"
_USER_LOCKS      variable     16 app/services/monitor_links_bridge.py _USER_LOCKS: Dict[int, bool] = {}
_USER_RE         variable     10 app/bot/services/channels_repo.py _USER_RE = re.compile(r"(?:https?://)?t\.me/([A-Za-z0-9_]{3,})/?$", re.IGNORECASE)
_WS_CACHE        variable     40 app/services/gsheets_writer.py _WS_CACHE: Dict[str, Any] = {}
_ZERO_WIDTH      variable     11 app/services/post_matcher.py _ZERO_WIDTH = ("\u200b", "\u200e", "\u200f")
_ZW              variable      7 app/services/html_match.py _ZW = "[\u200b\u200c\u200d\u200e\u200f]" # zero-width chars
__all__          variable      4 app/flows/batch_links/__init__.py __all__ = ["process_links", "run_link_queue_worker"]
__all__          variable      4 app/services/__init__.py __all__ = ["list_templates_full"]
__all__          variable      9 app/services/channel_db.py __all__ = [
__all__          variable     14 app/services/posts_watch_result_db.py __all__ = [
__init__         member       52 app/services/join_scheduler.py def __init__(self, cap: int, window_sec: int, init_tokens: float):
__init__         member       53 app/logging_json.py def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
__init__         member       58 app/flows/batch_links/process_links.py def __init__(self) -> None:
__init__         member      100 app/services/join_scheduler.py def __init__(self, alias: str):
__init__         member      106 app/services/requested_reconciler.py def __init__(
__repr__         member       98 app/services/models.py def __repr__(self) -> str:
__repr__         member      118 app/services/models.py def __repr__(self) -> str:
__repr__         member      136 app/services/models.py def __repr__(self) -> str:
__repr__         member      154 app/services/models.py def __repr__(self) -> str:
__repr__         member      185 app/services/models.py def __repr__(self) -> str:
__repr__         member      219 app/services/models.py def __repr__(self) -> str:
__slots__        variable     50 app/services/join_scheduler.py __slots__ = ("cap", "tokens", "rate", "last_refill")
__slots__        variable     90 app/services/join_scheduler.py __slots__ = (
__table_args__   variable     58 app/services/requested_reconciler_db.py __table_args__ = (
__table_args__   variable     73 app/services/requested_reconciler_db.py __table_args__ = (
__table_args__   variable     92 app/services/models.py __table_args__ = (
__table_args__   variable    179 app/services/models.py __table_args__ = (
__table_args__   variable    213 app/services/models.py __table_args__ = (
__tablename__    variable     50 app/services/requested_reconciler_db.py __tablename__ = "invite_check"
__tablename__    variable     65 app/services/requested_reconciler_db.py __tablename__ = "requested_check"
__tablename__    variable     85 app/services/models.py __tablename__ = "membership"
__tablename__    variable    111 app/services/models.py __tablename__ = "invite_map"
__tablename__    variable    130 app/services/models.py __tablename__ = "invite_status"
__tablename__    variable    148 app/services/models.py __tablename__ = "url_cache"
__tablename__    variable    171 app/services/models.py __tablename__ = "invite_check"
__tablename__    variable    205 app/services/models.py __tablename__ = "requested_check"
_adapt_limits_and_cooldown function    329 app/services/join_scheduler.py def _adapt_limits_and_cooldown(st: SessionState, kind: str, ok: bool, flood_wait_s: Optional[int]):
_add_tmpl        function    277 app/plugins/post_templates.py async def _add_tmpl(evt):
_allow_note_reset function    142 app/services/requested_reconciler_db.py def _allow_note_reset(session: str, invite_hash: str, now_ts: int) -> bool:
_already_joined  function    266 app/plugins/monitor_links.py async def _already_joined(cid: int) -> bool:
_apply_default_sheet_formatting function    129 app/services/gsheets_writer.py def _apply_default_sheet_formatting(ws) -> None:
_apply_session_cooldown_db function    200 app/services/requested_reconciler.py def _apply_session_cooldown_db(sess: str, cooldown_until_epoch: float):
_attach_listener_for_client function    367 app/plugins/posts_watch_listener.py def _attach_listener_for_client(tag: str, cli) -> None:
_attach_listener_for_client._on_deleted function    547 app/plugins/posts_watch_listener.py async def _on_deleted(ev: events.MessageDeleted.Event):
_attach_listener_for_client._on_edited function    470 app/plugins/posts_watch_listener.py async def _on_edited(ev: events.MessageEdited.Event):
_attach_listener_for_client._on_new_message function    369 app/plugins/posts_watch_listener.py async def _on_new_message(ev: events.NewMessage.Event):
_auto_resize_columns function    102 app/services/gsheets_writer.py def _auto_resize_columns(ws) -> None:
_bar             member      133 app/plugins/progress_live.py def _bar(done: int, total: int, width: int = 20) -> str:
_batch_cancel    function     84 app/plugins/batch_links.py async def _batch_cancel(evt):
_buf_lock        variable     20 app/services/gsheets_buffer.py _buf_lock = threading.Lock()
_build_full_footer function    106 app/flows/batch_links/process_links.py def _build_full_footer(items: List[dict]) -> str:
_build_full_footer._conflict_name function    128 app/flows/batch_links/process_links.py def _conflict_name(status: str) -> Optional[str]:
_build_full_footer._esc function    122 app/flows/batch_links/process_links.py def _esc(s: str) -> str:
_build_full_footer._escape unknown     119 app/flows/batch_links/process_links.py from html import escape as _escape
_build_full_footer._is_invalid_or_error function    148 app/flows/batch_links/process_links.py def _is_invalid_or_error(status: str) -> bool:
_build_full_footer._is_private function    144 app/flows/batch_links/process_links.py def _is_private(status: str) -> bool:
_build_full_footer._link_line function    155 app/flows/batch_links/process_links.py def _link_line(idx: int, url: str, title: Optional[str], status: str, tag: str = "") -> str:
_build_full_footer._strip_conflict function    135 app/flows/batch_links/process_links.py def _strip_conflict(status: str) -> str:
_build_parser    function     25 app/services/feature/seed.py def _build_parser() -> argparse.ArgumentParser:
_build_row_for_edited_other function    208 app/services/gsheets_buffer.py def _build_row_for_edited_other(wid: int, when_str: str | None) -> Tuple[str, List[str]]:
_build_row_for_expired function    184 app/services/gsheets_buffer.py def _build_row_for_expired(wid: int) -> Tuple[str, List[str]]:
_build_row_for_matched function    158 app/services/gsheets_buffer.py def _build_row_for_matched(wid: int) -> Tuple[str, List[str]]:
_busy_reply      function     56 app/bot/handlers/join_channels.py async def _busy_reply(message: Message):
_calc_coverage_at function     82 app/plugins/posts_watch_listener.py def _calc_coverage_at(hours_after: float | None = None) -> Optional[str]:
_calc_next       function    123 app/services/requested_reconciler_db.py def _calc_next(base: int, tries: int, max_cap: int, factor: float = 2.0) -> int:
_canon_url       function     30 app/services/post_matcher.py def _canon_url(u: str) -> str:
_changed         variable     35 app/plugins/progress_live.py _changed: bool = False
_chat_allowed    function    157 app/plugins/channel_info.py def _chat_allowed(event) -> bool:
_check_invite_with_session function    220 app/services/requested_reconciler.py async def _check_invite_with_session(client, invite_hash: str) -> Tuple["InviteCheckStatus", Optional[Any]]:
_clamp           function    147 app/services/join_scheduler.py def _clamp(v: float, vmin: float, vmax: float) -> float:
_clamp_pair      function     16 app/utils/throttle.py def _clamp_pair(lo: float, hi: float) -> Tuple[float, float]:
_classify        function     76 app/plugins/monitor_links.py def _classify(url: str) -> str:
_classify_kind   function    132 app/services/join_scheduler.py def _classify_kind(invite_or_username: Optional[str]) -> str:
_clean           function     38 app/utils/link_parser.py def _clean(s: str) -> str:
_cleanup_recent  function    421 app/services/gsheets_buffer.py def _cleanup_recent():
_client          function     14 app/services/gsheets.py def _client():
_client          function     55 app/services/gsheets_writer.py def _client():
_client_by_session function     88 app/services/requested_reconciler.py def _client_by_session(sess: str):
_closed          variable     38 app/plugins/progress_live.py _closed: bool = False
_cmd_channel_info function    104 app/plugins/channel_info.py async def _cmd_channel_info(event: events.NewMessage.Event):
_cmd_channels_help function    140 app/plugins/channel_info.py async def _cmd_channels_help(event: events.NewMessage.Event):
_cmd_channels_owner function     53 app/plugins/channel_info.py async def _cmd_channels_owner(event: events.NewMessage.Event):
_cmd_recent_channels function     72 app/plugins/channel_info.py async def _cmd_recent_channels(event: events.NewMessage.Event):
_cmd_recent_links function     89 app/plugins/channel_info.py async def _cmd_recent_links(event: events.NewMessage.Event):
_collect_links   function     57 app/plugins/post_templates.py def _collect_links(msg, html_text: str) -> list:
_collect_links_from_aiogram function     89 app/bot/handlers/join_channels.py def _collect_links_from_aiogram(src: Message, plain_text: str) -> List[str]:
_collect_links_from_aiogram function    108 app/bot/handlers1.py def _collect_links_from_aiogram(src: Message, plain_text: str) -> List[str]:
_collect_links_from_aiogram function    108 bot_create_watch.py def _collect_links_from_aiogram(src: Message, plain_text: str) -> List[str]:
_collect_links_from_aiogram function    118 app/bot/handlers/create_watch.py def _collect_links_from_aiogram(src: Message, plain_text: str) -> List[str]:
_column_exists   function     25 app/services/post_watch_db.py def _column_exists(c: sqlite3.Connection, table: str, column: str) -> bool:
_compare_two     function    126 app/debug/debug_post_diff_interactive.py async def _compare_two(first: MsgSnapshot, second: MsgSnapshot):
_conflict_name   function    128 app/flows/batch_links/process_links.py def _conflict_name(status: str) -> Optional[str]:
_conn            function     20 app/services/post_watch_db.py def _conn():
_conn            function     30 app/services/feature/seed_post_db.py def _conn():
_conn            function     36 app/services/link_queue.py def _conn():
_conn            function     46 app/services/owner_conflict_guard.py def _conn() -> sqlite3.Connection:
_conn            function     50 app/services/membership_db.py def _conn():
_conn            function     56 app/services/channel_facts.py def _conn():
_conn            variable     30 app/services/channel_db.py _conn: Optional[sqlite3.Connection] = None
_conn            variable     44 app/services/posts_watch_result_db.py _conn: Optional[sqlite3.Connection] = None
_control_chat_id function     21 app/bot/handlers/join_channels.py def _control_chat_id():
_control_chat_id function     30 app/bot/handlers1.py def _control_chat_id() -> Optional[int]:
_control_chat_id function     30 bot_create_watch.py def _control_chat_id() -> Optional[int]:
_control_chat_id function     33 app/bot/handlers/create_watch.py def _control_chat_id() -> Optional[int]:
_create_template_from_source function    166 bot_create_watch.py async def _create_template_from_source(src: Message) -> Optional[int]:
_create_template_from_source function    188 app/bot/handlers1.py async def _create_template_from_source(src: Message) -> Optional[int]:
_create_template_from_source function    233 app/bot/handlers/create_watch.py async def _create_template_from_source(src: Message) -> Optional[int]:
_create_template_from_source.pdb unknown     203 bot_create_watch.py from app.services import post_watch_db as pdb
_create_template_from_source.pdb unknown     211 app/bot/handlers1.py from app.services import post_watch_db as pdb
_create_template_from_source.pdb unknown     255 app/bot/handlers/create_watch.py from app.services import post_watch_db as pdb
_db_channel_meta function    134 app/plugins/monitor_watch.py def _db_channel_meta(channel_id: int) -> Tuple[Optional[str], Optional[str]]:
_db_get_channel_title_and_owner function    108 app/services/gsheets_buffer.py def _db_get_channel_title_and_owner(channel_id: int):
_db_get_template_title function    125 app/services/gsheets_buffer.py def _db_get_template_title(tid: int | None):
_db_get_watch_core function     78 app/services/gsheets_buffer.py def _db_get_watch_core(wid: int):
_db_get_watch_core function    134 app/plugins/posts_watch_listener.py def _db_get_watch_core(wid: int) -> Optional[Dict[str, Any]]:
_debounced_edit  member       93 app/plugins/progress_live.py async def _debounced_edit(self) -> None:
_dedup_ttl_key   function     68 app/services/gsheets_buffer.py def _dedup_ttl_key(sheet: str, wid: int, etype: str) -> bool:
_delayed_monitor_off function    389 app/bot/handlers/join_channels.py async def _delayed_monitor_off():
_delete_later    function     89 app/services/feature/seed_posts.py async def _delete_later(channel: Any, message_id: int, delay: int):
_delta_minutes_msq_str function     53 app/plugins/monitor_watch.py def _delta_minutes_msq_str(minutes: int) -> str:
_edit            member      103 app/plugins/progress_live.py async def _edit(self, final: bool) -> None:
_edited_other_value function    153 app/services/gsheets_buffer.py def _edited_other_value(when_str: str | None) -> str:
_engine          variable     44 app/services/models.py _engine: Engine = create_engine(
_ensure_bad_invites_table function      8 app/services/db/bad_invites.py def _ensure_bad_invites_table() -> None:
_ensure_bot      function     21 app/services/monitor_links_bridge.py async def _ensure_bot() -> Optional[Bot]:
_ensure_conn     function     38 app/services/channel_db.py def _ensure_conn() -> sqlite3.Connection:
_ensure_conn     function     54 app/services/posts_watch_result_db.py def _ensure_conn() -> sqlite3.Connection:
_ensure_connected function    137 app/services/account_pool.py async def _ensure_connected(slot: ClientSlot) -> None:
_ensure_schema   function     17 app/services/owner_conflict_guard.py def _ensure_schema(conn: sqlite3.Connection) -> None:
_entity_repr     function     34 app/debug/debug_post_diff_interactive.py def _entity_repr(text: str, e: Any) -> dict:
_env             function      5 app/plugins/progress_live.py def _env(name: str, default: str = "") -> str:
_env             function     20 app/services/account_pool.py def _env(name: str, default: str = "") -> str:
_env_bool        function     96 app/logging_json.py def _env_bool(name: str, default: bool) -> bool:
_esc             function     16 app/plugins/channel_info.py def _esc(s: Optional[str]) -> str:
_esc             function    122 app/flows/batch_links/process_links.py def _esc(s: str) -> str:
_escape          function     22 app/services/html_render.py def _escape(s: str) -> str:
_escape          unknown       5 app/flows/batch_links/process_links.py from html import escape as _escape
_escape          unknown       5 app/plugins/post_templates.py from html import escape as _escape
_escape          unknown     119 app/flows/batch_links/process_links.py from html import escape as _escape
_estimate_col_widths_px function     98 app/services/googlesheets/export_channels_table.py def _estimate_col_widths_px(headers: List[str], rows: List[List[Any]]) -> List[int]:
_event_text      function     20 app/bot/notifier.py def _event_text(event_type: str, payload_json: str, created_at: str, watch_id: int) -> str:
_execute         function     73 app/services/channel_maps.py async def _execute(sql: str, params: tuple = ()) -> None:
_execute._inner  function     74 app/services/channel_maps.py def _inner():
_executemany     function     80 app/services/channel_maps.py async def _executemany(sql: str, seq_params: list[tuple]) -> None:
_executemany._inner function     81 app/services/channel_maps.py def _inner():
_export_invite   function    107 app/services/feature/seed_creator.py async def _export_invite(c: TelegramClient, chat: Any, kind: str):
_extract_args    function     44 app/plugins/channel_info.py def _extract_args(raw: str, command: str) -> str:
_extract_from_entities function    129 app/utils/link_parser.py def _extract_from_entities(text: str, entities: Iterable) -> List[str]:
_extract_hidden_links_from_message function    281 app/flows/batch_links/process_links.py def _extract_hidden_links_from_message(msg) -> List[str]:
_extract_invite_hash function     24 app/services/joiner.py def _extract_invite_hash(url: str) -> str | None:
_extract_invite_hash function     87 app/services/membership_db.py def _extract_invite_hash(inv_or_url: str) -> Optional[str]:
_extract_message_html function    107 app/plugins/post_templates.py def _extract_message_html(msg) -> str:
_extract_message_html._is_high function    177 app/plugins/post_templates.py def _is_high(c: str) -> bool:
_extract_message_html._is_low function    180 app/plugins/post_templates.py def _is_low(c: str) -> bool:
_extract_message_html.add_span function    118 app/plugins/post_templates.py def add_span(off: int, ln: int, start_tag: str, end_tag: str):
_extract_targets function     47 app/bot/handlers1.py def _extract_targets(text: str) -> List[str]:
_extract_targets function     47 bot_create_watch.py def _extract_targets(text: str) -> List[str]:
_extract_targets function     52 app/bot/handlers/create_watch.py def _extract_targets(text: str) -> List[str]:
_extract_targets_from_message function    217 app/bot/handlers/create_watch.py def _extract_targets_from_message(msg: Message) -> List[str]:
_extract_title   function     93 app/plugins/post_templates.py def _extract_title(html_text: str) -> str:
_extract_urls    function     39 app/bot/handlers1.py def _extract_urls(text: str) -> List[str]:
_extract_urls    function     39 bot_create_watch.py def _extract_urls(text: str) -> List[str]:
_extract_urls    function     43 app/bot/handlers/create_watch.py def _extract_urls(text: str) -> List[str]:
_f               function     10 app/utils/throttle.py def _f(name: str, default: str) -> float:
_fallback_render function    123 app/plugins/posts_watch_listener.py def _fallback_render(m: Message) -> str:
_fetchall        function     95 app/services/channel_maps.py async def _fetchall(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
_fetchall._inner function     96 app/services/channel_maps.py def _inner():
_fetchone        function     87 app/services/channel_maps.py async def _fetchone(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
_fetchone._inner function     88 app/services/channel_maps.py def _inner():
_find_slot       function     72 app/services/account_pool.py def _find_slot(obj: Union[TelegramClient, ClientSlot]) -> Optional[ClientSlot]:
_first_line_title function     59 app/bot/handlers1.py def _first_line_title(text: str) -> str:
_first_line_title function     59 bot_create_watch.py def _first_line_title(text: str) -> str:
_first_line_title function     65 app/bot/handlers/create_watch.py def _first_line_title(text: str) -> str:
_flood_cooldown_until variable    176 app/services/requested_reconciler.py _flood_cooldown_until: dict[str, float] = defaultdict(float)
_flood_defer_applied_until variable    177 app/services/requested_reconciler.py _flood_defer_applied_until: dict[str, float] = defaultdict(float)
_flush_sheet     function    366 app/services/gsheets_buffer.py def _flush_sheet(sheet: str) -> None:
_flusher_stop    variable     22 app/services/gsheets_buffer.py _flusher_stop: Optional[threading.Event] = None
_flusher_thread  variable     21 app/services/gsheets_buffer.py _flusher_thread: Optional[threading.Thread] = None
_fmt_tw_end      function     21 app/bot/handlers/active_watches.py def _fmt_tw_end(s: Optional[str]) -> str:
_fmt_tw_end      function    151 app/bot/handlers1.py def _fmt_tw_end(s: Optional[str]) -> str:
_fmt_tw_end      function    151 bot_create_watch.py def _fmt_tw_end(s: Optional[str]) -> str:
_fmt_views       function     55 app/services/gsheets_buffer.py def _fmt_views(val: int | None) -> str:
_get_api_credentials function     35 app/services/feature/seed_creator.py def _get_api_credentials():
_get_conn        function     25 app/services/feature/seed_db.py def _get_conn():
_get_conn        function     67 app/services/channel_maps.py def _get_conn() -> sqlite3.Connection:
_get_or_create_worksheet function    248 app/services/gsheets_writer.py def _get_or_create_worksheet(sh, title: str):
_get_pool_sessions function     91 app/plugins/monitor_links.py async def _get_pool_sessions() -> List[Any]:
_get_pool_sessions._normalize_list function    100 app/plugins/monitor_links.py def _normalize_list(obj) -> List[Any]:
_guard_begin     unknown      20 app/flows/batch_links/queue_worker.py from app.services.owner_conflict_guard import begin as _guard_begin, end as _guard_end
_guard_begin     unknown      41 app/flows/batch_links/process_links.py from app.services.owner_conflict_guard import begin as _guard_begin, end as _guard_end
_guard_end       unknown      20 app/flows/batch_links/queue_worker.py from app.services.owner_conflict_guard import begin as _guard_begin, end as _guard_end
_guard_end       unknown      41 app/flows/batch_links/process_links.py from app.services.owner_conflict_guard import begin as _guard_begin, end as _guard_end
_guarded         function    162 app/plugins/channel_info.py async def _guarded(handler, event):
_handle_flood    function     88 app/services/feature/seed_creator.py async def _handle_flood(e: Exception):
_has_active_duplicate function     97 app/plugins/monitor_watch.py def _has_active_duplicate(channel_id: int, template_id: Optional[int], expected_text_hash: Optional[str]) -> Optional[dict]:
_has_column      function     56 app/services/membership_db.py def _has_column(c: sqlite3.Connection, table: str, col: str) -> bool:
_has_column      function     61 app/services/posts_watch_result_db.py def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
_html_mod        namespace    32 app/plugins/posts_watch_listener.py import html as _html_mod
_human           function     37 app/services/gsheets_buffer.py def _human(dt: datetime) -> str:
_human           function     61 app/plugins/posts_watch_listener.py def _human(dt: datetime) -> str:
_idem            function     13 app/services/owner_conflict_guard.py def _idem(owner: str, source_ref: str, action: str) -> str:
_in_flood_cooldown function    180 app/services/requested_reconciler.py def _in_flood_cooldown(sess: str) -> bool:
_index_exists    function     42 app/services/link_queue.py def _index_exists(c: sqlite3.Connection, name: str) -> bool:
_init_html_renderer function     94 app/plugins/posts_watch_listener.py def _init_html_renderer():
_init_html_renderer._fallback_render function    123 app/plugins/posts_watch_listener.py def _fallback_render(m: Message) -> str:
_init_html_renderer._rh unknown      97 app/plugins/posts_watch_listener.py from app.plugins.post_templates import _extract_message_html as _rh # type: ignore
_init_html_renderer._rh unknown     104 app/plugins/posts_watch_listener.py from app.services.html_render import render_html as _rh # type: ignore
_initialized     variable      8 app/services/owner_conflict_guard.py _initialized = False
_inner           function     74 app/services/channel_maps.py def _inner():
_inner           function     81 app/services/channel_maps.py def _inner():
_inner           function     88 app/services/channel_maps.py def _inner():
_inner           function     96 app/services/channel_maps.py def _inner():
_inner           function    114 app/services/channel_maps.py def _inner():
_interval_seconds function     20 app/services/googlesheets/channels_export_service.py def _interval_seconds() -> int:
_invite_owner_conflict function    378 app/flows/batch_links/process_links.py def _invite_owner_conflict(invite_hash: Optional[str],
_invite_rl       variable    159 app/services/requested_reconciler.py _invite_rl = SlidingWindowRateLimiter(
_is_enabled      function     17 app/services/googlesheets/channels_export_service.py def _is_enabled() -> bool:
_is_forward_message function     77 app/bot/handlers1.py def _is_forward_message(m: Message) -> bool:
_is_forward_message function     77 bot_create_watch.py def _is_forward_message(m: Message) -> bool:
_is_forward_message function     85 app/bot/handlers/create_watch.py def _is_forward_message(m: Message) -> bool:
_is_high         function    177 app/plugins/post_templates.py def _is_high(c: str) -> bool:
_is_invalid_or_error function    148 app/flows/batch_links/process_links.py def _is_invalid_or_error(status: str) -> bool:
_is_low          function    180 app/plugins/post_templates.py def _is_low(c: str) -> bool:
_is_member       function    250 app/services/requested_reconciler.py async def _is_member(client, channel_id: int) -> "MemberStatus":
_is_private      function    144 app/flows/batch_links/process_links.py def _is_private(status: str) -> bool:
_jittered        function    196 app/services/requested_reconciler.py def _jittered(ts: float, spread: float = 0.2) -> float:
_join_actions_kb function     31 app/bot/handlers/join_channels.py def _join_actions_kb() -> InlineKeyboardMarkup:
_json            namespace   359 app/plugins/monitor_watch.py import json as _json
_known_row_index variable     27 app/services/gsheets_buffer.py _known_row_index: Dict[str, Dict[int, int]] = {}
_last_flush_ts   variable     23 app/services/gsheets_buffer.py _last_flush_ts: float = 0.0
_last_render     variable     37 app/plugins/progress_live.py _last_render: str = ""
_late_setup      function    357 app/plugins/monitor_links.py async def _late_setup():
_lease_ctx       function    207 app/services/account_pool.py async def _lease_ctx(slot: ClientSlot):
_link_line       function    155 app/flows/batch_links/process_links.py def _link_line(idx: int, url: str, title: Optional[str], status: str, tag: str = "") -> str:
_links_from_metas function     50 app/services/feature/seed.py def _links_from_metas(metas: List[Dict]) -> List[str]:
_links_from_rows function     60 app/services/feature/seed.py def _links_from_rows(rows: List[Dict]) -> List[str]:
_links_text_from_json function    140 app/services/gsheets_buffer.py def _links_text_from_json(links_json: str | None) -> str:
_list            function    386 app/plugins/post_templates.py async def _list(evt):
_load_meta       function     20 app/plugins/post_templates.py def _load_meta():
_load_template_text function     31 app/services/feature/seed_posts.py def _load_template_text(tpl_id: int) -> Optional[str]:
_load_templates_map function    168 app/bot/handlers1.py def _load_templates_map() -> Dict[int, Dict[str, Any]]:
_load_templates_map.pdb unknown     170 app/bot/handlers1.py from app.services import post_watch_db as pdb
_lock            variable     31 app/services/channel_db.py _lock = threading.Lock()
_lock            variable     45 app/services/posts_watch_result_db.py _lock = threading.Lock()
_log_task_result function     46 main.py          def _log_task_result(t: asyncio.Task):
_loop            function     26 app/services/googlesheets/channels_export_service.py async def _loop(stop_event: asyncio.Event, interval_sec: int) -> None:
_loop            function    324 app/services/gsheets_buffer.py def _loop():
_main            function     38 main.py          async def _main():
_main._log_task_result function     46 main.py          def _log_task_result(t: asyncio.Task):
_mark_changed    member       85 app/plugins/progress_live.py def _mark_changed(self) -> None:
_mark_done_edited_other function    345 app/plugins/posts_watch_listener.py def _mark_done_edited_other(wid: int) -> str:
_max_line_len    function     92 app/services/googlesheets/export_channels_table.py def _max_line_len(s: str) -> int:
_maybe           function     69 app/plugins/monitor_links.py async def _maybe(awaitable_or_value):
_meta_cache      variable     18 app/plugins/post_templates.py _meta_cache = None
_min_spacing_with_jitter member      152 app/services/requested_reconciler.py def _min_spacing_with_jitter(self) -> float:
_mk_sqlite_url   function     34 app/services/models.py def _mk_sqlite_url(path: str) -> str:
_msg             function    124 app/plugins/batch_links.py async def _msg(evt):
_norm_html       function     10 app/services/html_match.py def _norm_html(s: str | None) -> str:
_norm_user       function     25 app/flows/batch_links/queue_worker.py def _norm_user(u: Optional[str]) -> Optional[str]:
_norm_user       function    307 app/flows/batch_links/process_links.py def _norm_user(u: Optional[str]) -> Optional[str]:
_normalize_html_full function    177 app/plugins/posts_watch_listener.py def _normalize_html_full(html_text: str) -> str:
_normalize_html_links function    207 app/plugins/posts_watch_listener.py def _normalize_html_links(html: str) -> str:
_normalize_html_links._replace_a function    225 app/plugins/posts_watch_listener.py def _replace_a(m: re.Match) -> str:
_normalize_list  function    100 app/plugins/monitor_links.py def _normalize_list(obj) -> List[Any]:
_note_reset_window variable    140 app/services/requested_reconciler_db.py _note_reset_window = {} # key: (session, invite_hash) -> dict(start:int, count:int)
_notify          function     81 app/plugins/monitor_links.py async def _notify(text: str):
_now             function     10 app/services/owner_conflict_guard.py def _now() -> int:
_now             function     34 app/services/channel_db.py def _now() -> str:
_now             function     50 app/services/posts_watch_result_db.py def _now() -> str:
_now             function    120 app/services/requested_reconciler_db.py def _now() -> int:
_now             function    143 app/services/join_scheduler.py def _now() -> float:
_now_monotonic   function     57 app/plugins/posts_watch_listener.py def _now_monotonic() -> float:
_now_msq_str     function     49 app/plugins/monitor_watch.py def _now_msq_str() -> str:
_off             function     59 app/plugins/batch_links.py async def _off(evt):
_oldest_event_ts variable     29 app/services/gsheets_buffer.py _oldest_event_ts: Optional[float] = None
_on              function     46 app/plugins/batch_links.py async def _on(evt):
_on_deleted      function    547 app/plugins/posts_watch_listener.py async def _on_deleted(ev: events.MessageDeleted.Event):
_on_edited       function    470 app/plugins/posts_watch_listener.py async def _on_edited(ev: events.MessageEdited.Event):
_on_new_message  function    369 app/plugins/posts_watch_listener.py async def _on_new_message(ev: events.NewMessage.Event):
_on_owner_clear  function    107 app/plugins/owner_set.py async def _on_owner_clear(event):
_on_owner_freeform function    119 app/plugins/owner_set.py async def _on_owner_freeform(event):
_on_owner_set    function     48 app/plugins/owner_set.py async def _on_owner_set(event):
_only_time       function     41 app/services/gsheets_buffer.py def _only_time(ts: str | None) -> str:
_open_spreadsheet function     83 app/services/gsheets_writer.py def _open_spreadsheet():
_owner_conflict  function     31 app/flows/batch_links/queue_worker.py def _owner_conflict(channel_id: Optional[int],
_owner_conflict  function    351 app/flows/batch_links/process_links.py def _owner_conflict(channel_id: Optional[int],
_owner_of        function    277 app/plugins/monitor_links.py async def _owner_of(cid: int) -> Optional[str]:
_owner_skip      function     97 app/plugins/batch_links.py async def _owner_skip(evt):
_owner_to_str    function     69 app/services/channel_facts.py def _owner_to_str(owner_id: Optional[Any], owner_username: Optional[str], owner_display: Optional[str]) -> str:
_parse_accounts_env function     28 app/services/account_pool.py def _parse_accounts_env() -> List[str]:
_parse_add_args  function    206 app/plugins/post_templates.py def _parse_add_args(arg_str: str):
_parse_flood_wait_seconds function    151 app/services/join_scheduler.py def _parse_flood_wait_seconds(err) -> Optional[int]:
_parse_int       function     22 app/plugins/channel_info.py def _parse_int(maybe: Optional[str], default: int, min_v=1, max_v=200) -> int:
_parse_kv        function     39 app/services/feature/channel_seed.py def _parse_kv(s: str) -> Dict[str, str]:
_parse_links_unique function    132 app/bot/handlers1.py def _parse_links_unique(links_json: Optional[str]) -> List[str]:
_parse_links_unique function    132 bot_create_watch.py def _parse_links_unique(links_json: Optional[str]) -> List[str]:
_parse_owner_freeform function     23 app/plugins/owner_set.py def _parse_owner_freeform(raw: str):
_parse_payload   function     13 app/bot/notifier.py def _parse_payload(payload_json: str) -> Dict[str, Any]:
_parse_template_id function     66 app/bot/handlers1.py def _parse_template_id(res: Any) -> Optional[int]:
_parse_template_id function     66 bot_create_watch.py def _parse_template_id(res: Any) -> Optional[int]:
_parse_template_id function     73 app/bot/handlers/create_watch.py def _parse_template_id(res: Any) -> Optional[int]:
_parse_window_spec function     57 app/plugins/monitor_watch.py def _parse_window_spec(spec: str) -> Optional[int]:
_pending_appends variable     25 app/services/gsheets_buffer.py _pending_appends: Dict[str, List[Tuple[int, List[str]]]] = {}
_pending_expire_worker function    317 app/plugins/posts_watch_listener.py async def _pending_expire_worker():
_pending_updates variable     26 app/services/gsheets_buffer.py _pending_updates: Dict[str, Dict[int, Dict[str, str]]] = {}
_persist_owner_conflict function    314 app/flows/batch_links/process_links.py def _persist_owner_conflict(channel_id: Optional[int],
_pick_idx_by_alias function    121 app/services/join_scheduler.py def _pick_idx_by_alias(alias: Optional[str]) -> Optional[int]:
_pick_idx_hash   function    127 app/services/join_scheduler.py def _pick_idx_hash(channel_id: int) -> int:
_plausible_invite_hash function     48 app/services/joiner.py def _plausible_invite_hash(h: str | None) -> bool:
_pool_sessions   function     76 app/services/requested_reconciler.py def _pool_sessions() -> List[str]:
_post_one        function    126 app/services/feature/seed_posts.py async def _post_one(ent, link_repr: str):
_print_diff      function    108 app/debug/debug_post_diff_interactive.py def _print_diff(label: str, a: Any, b: Any):
_print_entities_diff function    117 app/debug/debug_post_diff_interactive.py def _print_entities_diff(a: List[dict], b: List[dict]):
_print_err       function     46 app/services/gsheets_writer.py def _print_err(msg: str, exc: Exception | None = None):
_probe_any       function    155 app/plugins/monitor_links.py async def _probe_any(url: str) -> Optional[Dict[str, Any]]:
_process_links   function    295 app/plugins/monitor_links.py async def _process_links(urls: Iterable[str]):
_processing_state variable      7 app/bot/processing_guard.py _processing_state: Dict[int, Dict[str, Any]] = {}
_pylog           variable     44 app/plugins/monitor_watch.py _pylog = logging.getLogger("plugin.monitor_watch")
_pylog           variable     48 app/plugins/posts_watch_listener.py _pylog = logging.getLogger("plugin.posts_watch_listener")
_rand_uniform    function    139 app/services/join_scheduler.py def _rand_uniform(a: float, b: float) -> float:
_rate_wait_session function    180 app/services/join_scheduler.py async def _rate_wait_session(idx: int, kind: str):
_read_default_coverage_hours function     65 app/plugins/posts_watch_listener.py def _read_default_coverage_hours() -> float:
_recent_events   variable     28 app/services/gsheets_buffer.py _recent_events: Dict[Tuple[str, int, str], float] = {}
_record_meta     function     43 app/plugins/post_templates.py def _record_meta(tid: int, chat_id: int, message_id: int, has_media: bool):
_refill          member       64 app/services/join_scheduler.py def _refill(self):
_render          member      117 app/plugins/progress_live.py def _render(self, header_suffix: str, final: bool = False) -> str:
_render_html     function     56 app/debug/debug_post_diff_interactive.py def _render_html(msg: Message) -> str:
_render_html._rh unknown      62 app/debug/debug_post_diff_interactive.py from app.plugins.post_templates import _extract_message_html as _rh # type: ignore
_render_html._rh2 unknown      69 app/debug/debug_post_diff_interactive.py from app.services.html_render import render_html as _rh2 # type: ignore
_replace_a       function    225 app/plugins/posts_watch_listener.py def _replace_a(m: re.Match) -> str:
_reply           function     34 app/plugins/channel_info.py async def _reply(msg: Message, text: str):
_requested_rl    variable    167 app/services/requested_reconciler.py _requested_rl = SlidingWindowRateLimiter(
_resend_last     function     70 app/services/feature/seed.py async def _resend_last(n: int, target: str, send_batch: int):
_resend_last_bg  function     78 app/services/feature/channel_seed.py async def _resend_last_bg(n: int):
_resolve_channel_id_from_link function     79 app/plugins/monitor_watch.py async def _resolve_channel_id_from_link(url: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
_resolve_control_peer function     40 app/telethon_client.py async def _resolve_control_peer() -> tuple[int | None, str]:
_resolve_url     function    201 app/plugins/monitor_links.py async def _resolve_url(url: str) -> Dict[str, Any]:
_rh              unknown      62 app/debug/debug_post_diff_interactive.py from app.plugins.post_templates import _extract_message_html as _rh # type: ignore
_rh              unknown      97 app/plugins/posts_watch_listener.py from app.plugins.post_templates import _extract_message_html as _rh # type: ignore
_rh              unknown     104 app/plugins/posts_watch_listener.py from app.services.html_render import render_html as _rh # type: ignore
_rh2             unknown      69 app/debug/debug_post_diff_interactive.py from app.services.html_render import render_html as _rh2 # type: ignore
_rr              variable     55 app/services/account_pool.py _rr = 0 # round-robin індекс
_run             function     88 app/services/feature/seed.py async def _run(args):
_safe_sleep      function     83 app/services/feature/seed_creator.py async def _safe_sleep(base: float):
_save_meta       function     34 app/plugins/post_templates.py def _save_meta():
_seed_channels_bg function    105 app/services/feature/channel_seed.py async def _seed_channels_bg(args: Dict[str, str]):
_send_watch_from_links_batch_bot function    255 app/bot/handlers1.py async def _send_watch_from_links_batch_bot(bot, targets: List[str], mins: int, template_id: int) -> bool:
_send_watch_from_links_batch_bot function    259 bot_create_watch.py async def _send_watch_from_links_batch_bot(bot, targets: List[str], mins: int, template_id: int, created_by: int) -> bool:
_send_watch_from_links_batch_bot function    295 app/bot/handlers/create_watch.py async def _send_watch_from_links_batch_bot(bot, targets: List[str], mins: int, template_id: int) -> bool:
_session_name    unknown       7 app/flows/batch_links/queue_worker.py iter_pool_clients, mark_flood, mark_limit, session_name as _session_name,
_session_name    unknown      22 app/flows/batch_links/process_links.py iter_ready_pool_clients, bump_cooldown, mark_flood, mark_limit, session_name as _session_name
_set_flood_cooldown function    184 app/services/requested_reconciler.py def _set_flood_cooldown(sess: str, seconds: int) -> float:
_set_owner       function    486 app/plugins/monitor_links.py def _set_owner(username: Optional[str], display: Optional[str]):
_set_ready_after function    103 app/services/account_pool.py def _set_ready_after(slot: ClientSlot, seconds: int) -> None:
_set_sqlite_pragma function     89 app/services/requested_reconciler_db.py def _set_sqlite_pragma(dbapi_conn, connection_record):
_short_pause     function    274 app/flows/batch_links/process_links.py async def _short_pause():
_short_title     function     30 app/bot/handlers/active_watches.py def _short_title(title: Optional[Any], tid: Optional[int]) -> str:
_short_title     function    160 app/bot/handlers1.py def _short_title(title: Optional[Any], tid: Optional[int]) -> str:
_short_title     function    160 bot_create_watch.py def _short_title(title: Optional[str], tid: Optional[int]) -> str:
_sid             member       62 app/flows/batch_links/process_links.py def _sid(self, slot: Any) -> str:
_sleep           function    360 app/flows/batch_links/queue_worker.py async def _sleep(sec: int):
_sleep_delay     function     96 app/services/requested_reconciler.py def _sleep_delay(base: float) -> float:
_snapshot_from_msg function     79 app/debug/debug_post_diff_interactive.py def _snapshot_from_msg(msg: Message) -> MsgSnapshot:
_sqlite_pragmas  function     53 app/services/models.py def _sqlite_pragmas(dbapi_conn, _):
_status          function     71 app/plugins/batch_links.py async def _status(evt):
_strip_conflict  function    135 app/flows/batch_links/process_links.py def _strip_conflict(status: str) -> str:
_strip_simple_tags function    168 app/plugins/posts_watch_listener.py def _strip_simple_tags(html_fragment: str) -> str:
_strip_zw        function     13 app/services/post_matcher.py def _strip_zw(s: str) -> str:
_table_exists    function     47 app/services/link_queue.py def _table_exists(c: sqlite3.Connection, name: str) -> bool:
_tag_for_entity  function     25 app/services/html_render.py def _tag_for_entity(e) -> Tuple[str, str]:
_touch_oldest_event_ts function     61 app/services/gsheets_buffer.py def _touch_oldest_event_ts():
_truthy          function      2 app/settings.py  def _truthy(v: str | None) -> bool:
_try_int         function     24 app/bot/handlers1.py def _try_int(s: str) -> Optional[int]:
_try_int         function     24 bot_create_watch.py def _try_int(s: str) -> Optional[int]:
_try_int         function     26 app/bot/handlers/create_watch.py def _try_int(s: str) -> Optional[int]:
_unique_preserve function     76 app/bot/handlers/join_channels.py def _unique_preserve(items: List[str]) -> List[str]:
_unique_preserve function     96 app/bot/handlers1.py def _unique_preserve(items: List[str]) -> List[str]:
_unique_preserve function     96 bot_create_watch.py def _unique_preserve(items: List[str]) -> List[str]:
_unique_preserve function    105 app/bot/handlers/create_watch.py def _unique_preserve(items: List[str]) -> List[str]:
_update_maps     function    250 app/plugins/monitor_links.py async def _update_maps(res: Dict[str, Any]):
_views_worker    function    259 app/plugins/posts_watch_listener.py async def _views_worker():
_worker          function    259 app/services/join_scheduler.py async def _worker(idx: int):
account          variable     88 app/services/models.py account = Column(Text, nullable=False)
acquire          member      124 app/services/requested_reconciler.py async def acquire(self, key: str):
active_watches_router unknown       4 app/bot/handlers/__init__.py from app.bot.handlers.active_watches import router as active_watches_router
actor            variable     31 app/plugins/progress_live.py actor: str = "" # session/slot label
adapters         function      3 app/__init__.py  def adapters():
add_context      member       56 app/logging_json.py def add_context(self, **ctx):
add_link         function    135 app/services/channel_facts.py def add_link(channel_id: int, link: str) -> None:
add_link         function    167 app/services/channel_db.py def add_link(
add_span         function    118 app/plugins/post_templates.py def add_span(off: int, ln: int, start_tag: str, end_tag: str):
add_status       member       54 app/plugins/progress_live.py def add_status(self, status: str) -> None:
add_template     function     52 app/services/post_watch_db.py def add_template(
already          variable     27 app/plugins/progress_live.py already: int = 0
any_final_for_channel function    133 app/services/membership_db.py def any_final_for_channel(channel_id: int) -> Optional[str]:
app/services/gsheets_buffer.py modifiedFile    1 patch_gsheets_buffer.diff --- app/services/gsheets_buffer.py
append_rows      function    314 app/services/gsheets_writer.py def append_rows(sheet_title: str, rows: List[List[str]]) -> None:
append_summary_row function     31 app/services/gsheets.py def append_summary_row(row: list) -> bool:
apply_formatting function    138 app/services/googlesheets/export_channels_table.py def apply_formatting(ws: gspread.Worksheet, nrows: int, ncols: int, col_widths_px: Optional[List[int]] = None) -> None:
apply_insert_after function     22 apply_anchored_patch.py def apply_insert_after(content, anchor, payload):
apply_insert_before function     29 apply_anchored_patch.py def apply_insert_before(content, anchor, payload):
apply_regex_replace function     35 apply_anchored_patch.py def apply_regex_replace(content, pattern, repl, count=1, flags=""):
apply_replace    function     12 apply_anchored_patch.py def apply_replace(content, before, after, allow_multiple=False):
apply_replace_between function     52 apply_anchored_patch.py def apply_replace_between(content, begin_marker, end_marker, payload, include_markers=False):
await_action     variable      5 app/bot/states.py await_action = State()
back_to_menu_kb  function     13 app/bot/keyboards.py def back_to_menu_kb():
backoff_invite_miss function    266 app/services/requested_reconciler_db.py def backoff_invite_miss(session: str, invite_hash: str) -> None:
backoff_miss     function    386 app/services/requested_reconciler_db.py def backoff_miss(session: str, channel_id: int) -> None:
backup_file      function      9 apply_anchored_patch.py def backup_file(p):
bad              variable     28 app/plugins/progress_live.py bad: int = 0 # invalid/private/error/temp/other
batch_update_values function    353 app/services/gsheets_writer.py def batch_update_values(sheet_title: str, data: List[Dict[str, Any]]) -> None:
begin            function     55 app/services/owner_conflict_guard.py def begin(owner: str, source_ref: str, action: str) -> Tuple[bool, str]:
build_media_fingerprint function     65 app/services/post_matcher.py def build_media_fingerprint(msg) -> Optional[str]:
build_text_fingerprint function     54 app/services/post_matcher.py def build_text_fingerprint(s: Optional[str]) -> Tuple[str, int, str]:
bulk_defer_session_invites function    308 app/services/requested_reconciler_db.py def bulk_defer_session_invites(session: str, next_ts_epoch: int) -> None:
bulk_defer_session_requested function    405 app/services/requested_reconciler_db.py def bulk_defer_session_requested(session: str, next_ts_epoch: int) -> None:
bump_cooldown    function    109 app/services/account_pool.py def bump_cooldown(client: TelegramClient, seconds: int) -> None:
busy             variable     50 app/services/account_pool.py busy: bool = False
cancel_post      function    103 app/services/feature/seed_post_db.py def cancel_post(row_id: int) -> bool:
cancel_watch     function    418 app/services/posts_watch_result_db.py def cancel_watch(watch_id: int) -> None:
channel_id       variable     68 app/services/requested_reconciler_db.py channel_id: Mapped[int] = mapped_column(Integer, nullable=False)
channel_id       variable     87 app/services/models.py channel_id = Column(Integer, nullable=False)
channel_id       variable    114 app/services/models.py channel_id = Column(Integer, nullable=True)
channel_id       variable    208 app/services/models.py channel_id = Column(Integer, nullable=False)
channel_input    variable      4 app/bot/states.py channel_input = State()
channel_input    variable      9 app/bot/states.py channel_input = State()
cleanup_expired  function     59 app/services/db/bad_invites.py def cleanup_expired() -> int:
clear            function    422 app/services/requested_reconciler_db.py def clear(session: str, channel_id: int) -> None:
clear_invite     function    325 app/services/requested_reconciler_db.py def clear_invite(session: str, invite_hash: str) -> None:
client           variable     15 app/telethon_client.py client = TelegramClient(SESSION, API_ID, API_HASH, connection=ConnectionTcpAbridged)
client           variable     68 app/services/feature/seed_creator.py client: Optional[TelegramClient] = None
cmd_help         function     61 app/services/feature/channel_seed.py async def cmd_help(event):
cmd_off          function    413 app/plugins/monitor_links.py async def cmd_off(ev):
cmd_on           function    391 app/plugins/monitor_links.py async def cmd_on(ev):
cmd_seed_channels function     98 app/services/feature/channel_seed.py async def cmd_seed_channels(event):
cmd_seed_links   function     67 app/services/feature/channel_seed.py async def cmd_seed_links(event):
cmd_status       function    380 app/plugins/monitor_links.py async def cmd_status(ev):
collapse_ws      function     26 app/utils/text_norm.py def collapse_ws(s: str) -> str:
collect_links    function    188 app/utils/link_parser.py async def collect_links(evt) -> List[str]:
configure_logging function    102 app/logging_json.py def configure_logging(force_json: Optional[bool] = None,
confirm          variable     12 app/bot/states.py confirm = State()
confirm_no       function    361 app/bot/handlers1.py async def confirm_no(cb: CallbackQuery, state: FSMContext):
confirm_no       function    380 bot_create_watch.py async def confirm_no(cb: CallbackQuery, state: FSMContext):
confirm_no       function    440 app/bot/handlers/create_watch.py async def confirm_no(cb: CallbackQuery, state: FSMContext):
confirm_yes      function    366 app/bot/handlers1.py async def confirm_yes(cb: CallbackQuery, state: FSMContext):
confirm_yes      function    386 bot_create_watch.py async def confirm_yes(cb: CallbackQuery, state: FSMContext):
confirm_yes      function    446 app/bot/handlers/create_watch.py async def confirm_yes(cb: CallbackQuery, state: FSMContext):
consume_one      member       80 app/services/join_scheduler.py def consume_one(self):
create_batch     function    203 app/services/feature/seed_creator.py async def create_batch(count: int, mix: Optional[Dict[str, int]] = None, title_prefix: str = "SEED") -> List[Dict[str, Any]]:
create_channel   function    126 app/services/feature/seed_creator.py async def create_channel(title: str, kind: str = "private_open") -> Dict[str, Any]:
create_or_get_daily_sheet variable     39 app/plugins/monitor_watch.py create_or_get_daily_sheet = append_daily_row = None # type: ignore
create_watch     function    153 app/services/posts_watch_result_db.py def create_watch(
create_watch_router unknown       3 app/bot/handlers/__init__.py from app.bot.handlers.create_watch import router as create_watch_router
current          variable     30 app/plugins/progress_live.py current: str = "" # current url
debounce         variable     19 app/plugins/progress_live.py debounce: float = field(default_factory=lambda: float(_env("PROGRESS_DEBOUNCE", "3")))
defer_invite_until function    291 app/services/requested_reconciler_db.py def defer_invite_until(session: str, invite_hash: str, next_ts_epoch: int) -> None:
display_name     function      4 app/flows/batch_links/common.py def display_name(slot) -> str:
done             variable     24 app/plugins/progress_live.py done: int = 0
due_invites      function    246 app/services/requested_reconciler_db.py def due_invites(sessions: Sequence[str], limit: int) -> List[InviteCheck]:
due_requested    function    364 app/services/requested_reconciler_db.py def due_requested(sessions: Sequence[str], per_account: int, limit: int) -> List[RequestedCheck]:
due_to_delete    function     73 app/services/feature/seed_post_db.py def due_to_delete(limit: int = 50) -> List[Dict[str, Any]]:
due_to_post      function     53 app/services/feature/seed_post_db.py def due_to_post(limit: int = 50) -> List[Dict[str, Any]]:
end              function     77 app/services/owner_conflict_guard.py def end(owner: str, source_ref: str, action: str, result: str) -> None:
engine           variable     80 app/services/requested_reconciler_db.py engine = create_engine(
enqueue          function     97 app/services/link_queue.py def enqueue(
enqueue_join     function    443 app/services/join_scheduler.py async def enqueue_join(channel_id: int, invite_or_username: Optional[str], source_url: Optional[str]):
ensure_client    function     71 app/services/feature/seed_creator.py async def ensure_client():
ensure_daily_sheet function     45 app/services/gsheets.py def ensure_daily_sheet(title: str, headers: Optional[List[str]] = None):
ensure_daily_sheet function    306 app/services/gsheets_writer.py def ensure_daily_sheet(sheet_title: str) -> bool:
ensure_join      function    121 app/services/joiner.py async def ensure_join(client, url: str):
ensure_ws        function     83 app/services/googlesheets/export_channels_table.py def ensure_ws(gc: gspread.Client, spreadsheet_id: str, sheet_name: str, headers: List[str]) -> gspread.Worksheet:
exact_html_equal function     21 app/services/html_match.py def exact_html_equal(a: str | None, b: str | None) -> bool:
exact_match      function      9 app/services/post_match.py def exact_match(a: str, b: str) -> bool:
export_channels_table function    229 app/services/googlesheets/export_channels_table.py def export_channels_table(logger: Optional[logging.Logger] = None) -> bool:
extract_links    function     85 app/utils/link_parser.py def extract_links(text: str) -> List[str]:
extract_links_any function    164 app/utils/link_parser.py def extract_links_any(msg_or_text: Union[str, "TgMessage"]) -> List[str]:
extract_links_norm function     38 app/services/post_matcher.py def extract_links_norm(s: str) -> List[str]:
fetch_due        function    137 app/services/link_queue.py def fetch_due(limit: int = 20) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
fetch_rows       function     41 app/services/googlesheets/export_channels_table.py def fetch_rows(db_path: str, sql_path: str) -> List[List[Any]]:
fetch_unsent_events function    279 app/services/posts_watch_result_db.py def fetch_unsent_events(limit: int = 100) -> List[Tuple[int, int, str, str, str]]:
find_active_duplicate function    520 app/services/posts_watch_result_db.py def find_active_duplicate(
find_by_username function     57 app/services/feature/seed_db.py def find_by_username(username: str) -> Optional[Dict[str, Any]]:
find_channel     function    211 app/services/channel_db.py def find_channel(channel_id: int) -> Optional[Dict[str, Any]]:
find_matched_by_message function    372 app/services/posts_watch_result_db.py def find_matched_by_message(channel_id: int, message_id: int) -> list[int]:
find_slot_by_session_name function     80 app/services/account_pool.py def find_slot_by_session_name(name: str) -> Optional[ClientSlot]:
finish           member       76 app/plugins/progress_live.py async def finish(self, footer: str = "") -> None:
finish_batch     function    170 app/services/monitor_links_bridge.py def finish_batch(control_msg_id: int) -> None:
finish_processing function     10 app/bot/user_state.py def finish_processing(uid: int):
flood            variable     29 app/plugins/progress_live.py flood: int = 0
flush_now        function    359 app/services/gsheets_buffer.py def flush_now() -> None:
fmt_result_line  function     20 app/utils/formatting.py def fmt_result_line(idx: int, url: str, status: str, who: str | None = None, extra: str | None = None) -> str:
fmt_summary      function     35 app/utils/formatting.py def fmt_summary(results: Iterable[str]) -> str:
footer           variable     32 app/plugins/progress_live.py footer: str = "" # optional summary
format           member       10 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
format           member       37 app/logging_json.py def format(self, record: logging.LogRecord) -> str:
fuzzy_match      function     19 app/services/post_match.py def fuzzy_match(a: str, b: str, threshold: float = 0.70) -> bool:
fuzzy_ratio      function     12 app/services/post_match.py def fuzzy_ratio(a: str, b: str) -> float:
get_channel      function    140 app/services/channel_maps.py async def get_channel(channel_id: int) -> Optional[Dict[str, Any]]:
get_channel_owner function    147 app/services/channel_facts.py def get_channel_owner(channel_id: int) -> Optional[Dict[str, Any]]:
get_channels_by_owner function    192 app/services/channel_db.py def get_channels_by_owner(owner: str, limit: int = 50) -> List[Tuple]:
get_client       function     69 app/services/googlesheets/export_channels_table.py def get_client() -> gspread.Client:
get_client_by_session_name function     89 app/services/account_pool.py def get_client_by_session_name(name: str) -> Optional[TelegramClient]:
get_engine       function    229 app/services/models.py def get_engine() -> Engine:
get_invite_owner function    341 app/services/channel_db.py def get_invite_owner(invite_hash: str) -> Optional[Dict[str, Any]]:
get_invite_sessions function    234 app/services/requested_reconciler_db.py def get_invite_sessions(invite_hash: str) -> List[str]:
get_link         function    177 app/services/channel_maps.py async def get_link(url: str) -> Optional[Dict[str, Any]]:
get_links_by_channel_ids function     87 app/bot/services/channels_repo.py def get_links_by_channel_ids(cids: List[int]) -> Dict[int, str]:
get_logger       function    144 app/logging_json.py def get_logger(name: str, **context) -> StructuredAdapter:
get_membership   function    123 app/services/membership_db.py def get_membership(account: str, channel_id: int) -> Optional[str]:
get_owners_by_channel_ids function    142 app/bot/services/channels_repo.py def get_owners_by_channel_ids(cids: List[int]) -> Dict[int, str]:
get_pending_by_channel function    430 app/services/posts_watch_result_db.py def get_pending_by_channel(channel_id: int) -> List[Dict[str, Any]]:
get_processing   function     28 app/bot/processing_guard.py def get_processing(user_id: int) -> dict | None:
get_session_factory function    234 app/services/models.py def get_session_factory():
get_subscription function    225 app/services/channel_maps.py async def get_subscription(channel_id: int) -> Optional[Tuple[int, int, str, Optional[int], Optional[str], Optional[int]]]:
get_subscription_by_alias function    246 app/services/channel_maps.py async def get_subscription_by_alias(channel_id: int, alias: str) -> Optional[Dict[str, Any]]:
get_watch_created_by function    224 app/services/posts_watch_result_db.py def get_watch_created_by(watch_id: int) -> Optional[int]:
get_watch_created_via function    241 app/services/posts_watch_result_db.py def get_watch_created_via(watch_id: int) -> Optional[str]:
get_watch_source_url function    210 app/services/posts_watch_result_db.py def get_watch_source_url(watch_id: int) -> Optional[str]:
group_active     function     24 app/bot/services/watches_repo.py def group_active(
gsheets_buffer   variable     45 app/plugins/posts_watch_listener.py gsheets_buffer = None # type: ignore
gspread          variable     10 app/services/gsheets.py gspread = None
gspread          variable     19 app/services/gsheets_writer.py gspread = None # type: ignore
gw               unknown      10 app/services/gsheets_buffer.py from app.services import gsheets_writer as gw
handler          function    186 app/debug/debug_post_diff_interactive.py async def handler(evt: events.NewMessage.Event):
help_cmd         function     34 app/plugins/help_and_ping.py async def help_cmd(event):
init             function     31 app/services/feature/seed_db.py def init():
init             function     32 app/services/post_watch_db.py def init(db_path: Optional[str] = None):
init             function     35 app/services/feature/seed_post_db.py def init():
init             function     45 app/services/channel_db.py def init() -> None:
init             function     49 app/services/owner_conflict_guard.py def init() -> None:
init             function     52 app/services/link_queue.py def init(db_path: Optional[str] = None):
init             function     62 app/services/channel_facts.py def init():
init             function     65 app/services/membership_db.py def init(db_path: Optional[str] = None):
init             function     66 app/services/posts_watch_result_db.py def init() -> None:
init             function    103 app/services/requested_reconciler_db.py def init(db_path: Optional[str] = None) -> None:
init             function    106 app/services/channel_maps.py async def init(db_path: Optional[str] = None) -> None:
init._inner      function    114 app/services/channel_maps.py def _inner():
init_db          function    258 app/services/models.py def init_db() -> None:
insert_watch_event function    255 app/services/posts_watch_result_db.py def insert_watch_event(watch_id: int, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
intake           function    423 app/plugins/monitor_links.py async def intake(ev):
invite_hash      variable     52 app/services/requested_reconciler_db.py invite_hash: Mapped[str] = mapped_column(String, nullable=False)
invite_hash      variable    113 app/services/models.py invite_hash = Column(Text, primary_key=True)
invite_hash      variable    132 app/services/models.py invite_hash = Column(Text, primary_key=True)
invite_hash      variable    174 app/services/models.py invite_hash = Column(Text, nullable=False)
invite_status_get function    223 app/services/membership_db.py def invite_status_get(invite_or_hash: str) -> Optional[str]:
invite_status_put function    207 app/services/membership_db.py def invite_status_put(invite_or_hash: str, status: str) -> None:
is_already_subscribed function    233 app/services/account_pool.py async def is_already_subscribed(url: str) -> Optional[str]:
is_already_subscribed_any function     12 app/services/subscription_check.py async def is_already_subscribed_any(url: str) -> Optional[str]:
is_bad           function     38 app/services/db/bad_invites.py def is_bad(invite_hash: str) -> Tuple[bool, Optional[int], Optional[str]]:
is_invite        function     77 app/utils/link_parser.py def is_invite(url: str) -> bool:
is_match_message function     98 app/services/post_matcher.py def is_match_message(
is_processing    function      4 app/bot/user_state.py def is_processing(uid: int) -> bool:
is_processing    function     10 app/bot/processing_guard.py def is_processing(user_id: int) -> bool:
is_requested     function    431 app/services/requested_reconciler_db.py def is_requested(session: str, channel_id: int) -> bool:
is_user_locked   function     87 app/services/monitor_links_bridge.py def is_user_locked(user_chat_id: int) -> bool:
iter_links_by_channel function    182 app/services/channel_maps.py async def iter_links_by_channel(channel_id: int) -> list[Dict[str, Any]]:
iter_pool_clients function    190 app/services/account_pool.py def iter_pool_clients() -> List[ClientSlot]:
iter_ready_pool_clients function    197 app/services/account_pool.py def iter_ready_pool_clients() -> List[ClientSlot]:
join_cancel_batch function    310 app/bot/handlers/join_channels.py async def join_cancel_batch(cb: CallbackQuery, state: FSMContext):
join_channels_input function    219 app/bot/handlers/join_channels.py async def join_channels_input(m: Message, state: FSMContext):
join_channels_result_kb function     38 app/bot/keyboards.py def join_channels_result_kb():
join_channels_router unknown       5 app/bot/handlers/__init__.py from app.bot.handlers.join_channels import router as join_channels_router
join_owner_input function    360 app/bot/handlers/join_channels.py async def join_owner_input(m: Message, state: FSMContext):
join_owner_input._delayed_monitor_off function    389 app/bot/handlers/join_channels.py async def _delayed_monitor_off():
join_set_owner   function    334 app/bot/handlers/join_channels.py async def join_set_owner(cb: CallbackQuery, state: FSMContext):
join_status      function    500 app/services/join_scheduler.py def join_status() -> Dict[str, int]:
last_created     function     49 app/services/feature/seed_db.py def last_created(n: int = 10) -> List[Dict[str, Any]]:
lease            function    215 app/services/account_pool.py async def lease() -> Optional[asyncio.AbstractAsyncContextManager]:
list_active_channels function    461 app/services/posts_watch_result_db.py def list_active_channels() -> List[int]:
list_active_watches function      7 app/bot/services/watches_repo.py def list_active_watches(user_id: int) -> List[Tuple[Any, Any, Any, Any, Any, Any]]:
list_due_coverage function    476 app/services/posts_watch_result_db.py def list_due_coverage(now_ts: Optional[str] = None) -> List[Tuple[int, int, int, Optional[str]]]:
list_due_pending_expire function    499 app/services/posts_watch_result_db.py def list_due_pending_expire(now_ts: Optional[str] = None) -> List[int]:
list_recent      function     96 app/services/feature/seed_post_db.py def list_recent(n: int = 20) -> List[Dict[str, Any]]:
list_session_names function     97 app/services/account_pool.py def list_session_names() -> List[str]:
list_templates   function    105 app/services/post_watch_db.py def list_templates(limit: int = 50) -> List[Tuple[int, str, str, float, int]]:
list_templates_full function    117 app/services/post_watch_db.py def list_templates_full(limit: int = 50) -> List[Tuple[int, str, str, float, int, Optional[str], Optional[str]]]:
list_templates_full variable     37 app/plugins/posts_watch_listener.py list_templates_full = None # type: ignore
load_plugins     function     65 app/telethon_client.py async def load_plugins():
load_sql         function     37 app/services/googlesheets/export_channels_table.py def load_sql(path: str) -> str:
load_templates_map function      7 app/bot/services/templates_repo.py def load_templates_map() -> Dict[int, Dict[str, Any]]:
load_templates_map.pdb unknown       9 app/bot/services/templates_repo.py from app.services import post_watch_db as pdb
lock             variable     51 app/services/account_pool.py lock: asyncio.Lock = asyncio.Lock()
log              member       59 app/logging_json.py def log(self, level: int, msg: Any, *args, **kwargs):
log              variable      2 app/flows/batch_links/common.py log = logging.getLogger("flow.batch_links.common")
log              variable      4 app/bot/processing_guard.py log = logging.getLogger("bot_processing_guard")
log              variable      5 app/bot/services/templates_repo.py log = logging.getLogger("templates_repo")
log              variable      5 app/plugins/owner_set.py log = logging.getLogger("plugin.owner_set")
log              variable      7 app/bot/services/channels_repo.py log = logging.getLogger("channels_repo")
log              variable      8 app/plugins/resolve_channel.py log = get_logger("plugin.resolve_channel")
log              variable      8 app/utils/throttle.py log = logging.getLogger("utils.throttle")
log              variable      9 app/services/post_matcher.py log = logging.getLogger("services.post_matcher")
log              variable     10 app/services/googlesheets/channels_export_service.py log = logging.getLogger("channels_exporter")
log              variable     10 app/services/monitor_links_bridge.py log = logging.getLogger("monitor_links_bridge")
log              variable     10 app/services/subscription_check.py log = logging.getLogger("services.subscription_check")
log              variable     11 app/plugins/channel_info.py log = logging.getLogger("plugin.channel_info")
log              variable     12 app/plugins/post_templates.py log = logging.getLogger("plugin.post_templates")
log              variable     12 app/services/posts_watch_result_db.py log = logging.getLogger("services.posts_watch_result_db")
log              variable     13 app/plugins/batch_links.py log = logging.getLogger("plugin.batch_links")
log              variable     13 app/services/gsheets_writer.py log = logging.getLogger("services.gsheets_writer_transport")
log              variable     13 app/telethon_client.py log = logging.getLogger("telethon_client")
log              variable     14 app/services/googlesheets/export_channels_table.py log = logging.getLogger("channels_table")
log              variable     15 app/services/join_scheduler.py log = get_logger("join_scheduler")
log              variable     16 app/services/requested_reconciler_db.py log = logging.getLogger("services.requested_reconciler.db")
log              variable     17 app/services/account_pool.py log = logging.getLogger("services.account_pool")
log              variable     18 app/bot/handlers/active_watches.py log = logging.getLogger("bot_active_watches")
log              variable     18 app/bot/handlers/join_channels.py log = logging.getLogger("bot_join_channels")
log              variable     18 app/debug/debug_post_diff_interactive.py log = logging.getLogger("two_forwards_html_diff_local")
log              variable     20 app/bot/handlers1.py log = logging.getLogger("bot_create_watch")
log              variable     20 bot_create_watch.py log = logging.getLogger("bot_create_watch")
log              variable     21 app/bot/handlers/create_watch.py log = logging.getLogger("bot_create_watch")
log              variable     21 app/services/joiner.py log = logging.getLogger("services.joiner")
log              variable     22 app/flows/batch_links/queue_worker.py log = logging.getLogger("flow.batch_links.worker")
log              variable     22 app/services/feature/seed.py log = logging.getLogger("seed_cli")
log              variable     22 app/services/requested_reconciler.py log = logging.getLogger("services.requested_reconciler")
log              variable     23 app/services/feature/channel_seed.py log = get_logger("plugin.channel_seed")
log              variable     26 app/services/feature/seed_posts.py log = logging.getLogger("seed_posts")
log              variable     26 app/services/models.py log = logging.getLogger("services.models")
log              variable     43 app/plugins/monitor_watch.py log = get_logger("plugin.monitor_watch")
log              variable     45 app/flows/batch_links/process_links.py log = logging.getLogger("flow.batch_links.process")
log              variable     47 app/plugins/posts_watch_listener.py log = get_logger("plugin.posts_watch_listener")
log              variable     53 app/plugins/monitor_links.py log = logging.getLogger("monitor_links")
log              variable     55 app/services/feature/seed_creator.py log = logging.getLogger("seed_creator")
lq_enqueue       unknown      34 app/flows/batch_links/process_links.py from app.services.link_queue import enqueue as lq_enqueue
lq_fetch_due     unknown      13 app/flows/batch_links/queue_worker.py fetch_due as lq_fetch_due, mark_processing as lq_mark_processing,
lq_init          unknown       9 app/plugins/batch_links.py from app.services.link_queue import init as lq_init
lq_mark_done     unknown      14 app/flows/batch_links/queue_worker.py mark_done as lq_mark_done, mark_failed as lq_mark_failed,
lq_mark_failed   unknown      14 app/flows/batch_links/queue_worker.py mark_done as lq_mark_done, mark_failed as lq_mark_failed,
lq_mark_processing unknown      13 app/flows/batch_links/queue_worker.py fetch_due as lq_fetch_due, mark_processing as lq_mark_processing,
main             function      8 safe_apply_patch.py def main():
main             function     31 app/debug/test_normalize_html_links_tony_bet.py def main():
main             function     71 apply_anchored_patch.py def main():
main             function    129 app/services/feature/seed.py def main():
main             function    169 app/debug/debug_post_diff_interactive.py async def main():
main.handler     function    186 app/debug/debug_post_diff_interactive.py async def handler(evt: events.NewMessage.Event):
main_client      unknown      12 app/plugins/monitor_watch.py from app.telethon_client import client as main_client # базовий клієнт
main_menu_kb     function      4 app/bot/keyboards.py def main_menu_kb():
map_invite_get   function    176 app/services/membership_db.py def map_invite_get(invite_or_hash: str) -> Tuple[Optional[int], Optional[str]]:
map_invite_set   function    147 app/services/membership_db.py def map_invite_set(invite_or_hash: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
mark_bad         function     23 app/services/db/bad_invites.py def mark_bad(invite_hash: str, ttl_seconds: int = 43200, reason: str = "") -> None:
mark_deleted     function     84 app/services/feature/seed_post_db.py def mark_deleted(row_id: int):
mark_done        function    163 app/services/link_queue.py def mark_done(item_id: int):
mark_done_deleted function    356 app/services/posts_watch_result_db.py def mark_done_deleted(watch_id: int) -> None:
mark_done_views  function    340 app/services/posts_watch_result_db.py def mark_done_views(watch_id: int, final_views: Optional[int]) -> None:
mark_event_sent  function    300 app/services/posts_watch_result_db.py def mark_event_sent(event_id: int, sent_to: int) -> None:
mark_expired     function    388 app/services/posts_watch_result_db.py def mark_expired(watch_id: int) -> None:
mark_failed      function     90 app/services/feature/seed_post_db.py def mark_failed(row_id: int):
mark_failed      function    168 app/services/link_queue.py def mark_failed(item_id: int, error: str, backoff_sec: int, max_retries: int = 5):
mark_flood       function    118 app/services/account_pool.py def mark_flood(client: TelegramClient, seconds: int) -> None:
mark_limit       function    127 app/services/account_pool.py def mark_limit(client_or_slot: Union[TelegramClient, ClientSlot], days: int = 2) -> None:
mark_matched     function    315 app/services/posts_watch_result_db.py def mark_matched(
mark_posted      function     64 app/services/feature/seed_post_db.py def mark_posted(row_id: int, message_id: int):
mark_processing  function    158 app/services/link_queue.py def mark_processing(item_id: int):
mark_unmatched_after_edit function    400 app/services/posts_watch_result_db.py def mark_unmatched_after_edit(watch_id: int) -> None:
memb_init        unknown       8 app/plugins/batch_links.py from app.services.membership_db import init as memb_init
menu_add_join_channels function    197 app/bot/handlers/join_channels.py async def menu_add_join_channels(cb: CallbackQuery, state: FSMContext):
menu_add_watch   function    284 app/bot/handlers1.py async def menu_add_watch(cb: CallbackQuery, state: FSMContext):
menu_add_watch   function    290 bot_create_watch.py async def menu_add_watch(cb: CallbackQuery, state: FSMContext):
menu_add_watch   function    326 app/bot/handlers/create_watch.py async def menu_add_watch(cb: CallbackQuery, state: FSMContext):
menu_home        function    276 app/bot/handlers1.py async def menu_home(cb: CallbackQuery, state: FSMContext):
menu_home        function    284 bot_create_watch.py async def menu_home(cb: CallbackQuery, state: FSMContext):
menu_home        function    317 app/bot/handlers/create_watch.py async def menu_home(cb: CallbackQuery, state: FSMContext):
menu_list_active function    185 app/bot/handlers/active_watches.py async def menu_list_active(cb: CallbackQuery):
menu_list_active function    529 app/bot/handlers1.py async def menu_list_active(cb: CallbackQuery):
menu_list_active function    540 bot_create_watch.py async def menu_list_active(cb: CallbackQuery):
mon_new          function     11 app/plugins/metrics_watch.py async def mon_new(event):
mon_start        function     31 app/plugins/metrics_watch.py async def mon_start(event):
mon_status       function     21 app/plugins/metrics_watch.py async def mon_status(event):
msk_now          function      6 app/services/time_utils.py def msk_now() -> datetime:
msk_timestamp    function     10 app/services/time_utils.py def msk_timestamp() -> int:
need_wait_seconds_for_one member       72 app/services/join_scheduler.py def need_wait_seconds_for_one(self) -> float:
needle_clear     function     10 app/plugins/needle_reply.py async def needle_clear(event):
needle_from_reply function     22 app/plugins/needle_reply.py async def needle_from_reply(event):
needle_show      function     15 app/plugins/needle_reply.py async def needle_show(event):
next_check_at    variable     55 app/services/requested_reconciler_db.py next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
next_check_at    variable     70 app/services/requested_reconciler_db.py next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
next_check_at    variable    176 app/services/models.py next_check_at = Column(Integer, nullable=False)
next_check_at    variable    210 app/services/models.py next_check_at = Column(Integer, nullable=False)
next_ready       variable     49 app/services/account_pool.py next_ready: float = 0.0 # unix-ts, коли клієнт знову доступний
normalize        function     53 app/utils/link_parser.py def normalize(url: str) -> str:
normalize_soft   function     23 app/utils/text_norm.py def normalize_soft(s: str) -> str:
normalize_strict function     12 app/utils/text_norm.py def normalize_strict(s: str) -> str:
normalize_target_link function     12 app/bot/services/channels_repo.py def normalize_target_link(target: str) -> str:
normalize_text   function      3 app/services/post_match.py def normalize_text(s: str) -> str:
normalize_text   function     18 app/services/post_matcher.py def normalize_text(s: Optional[str]) -> str:
note_conflict    function     91 app/services/owner_conflict_guard.py def note_conflict(owner: str, channel_id: Optional[int], source_ref: Optional[str], reason: str) -> None:
note_owner_conflict function    157 app/services/channel_facts.py def note_owner_conflict(channel_id: int, incoming_owner: str, source_link: Optional[str]) -> None:
note_requested   function    336 app/services/requested_reconciler_db.py def note_requested(session: str, channel_id: int, start_after_sec: int = 60) -> None:
note_requested_invite function    173 app/services/requested_reconciler_db.py def note_requested_invite(session: str, invite_hash: str, start_after_sec: int = 60) -> None:
noted_at         variable     54 app/services/requested_reconciler_db.py noted_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
noted_at         variable     69 app/services/requested_reconciler_db.py noted_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
noted_at         variable    175 app/services/models.py noted_at = Column(Integer, nullable=False)
noted_at         variable    209 app/services/models.py noted_at = Column(Integer, nullable=False)
notice           function      5 app/utils/notices.py async def notice(client, control_peer: str | int = CONTROL_PEER, text: str = ""):
notifier_loop    function     71 app/bot/notifier.py async def notifier_loop(bot: Bot, tick_sec: float = 5.0):
ok               variable     25 app/plugins/progress_live.py ok: int = 0 # joined
orm_init_db      unknown      15 main.py          from app.services.models import init_db as orm_init_db
owner_guard_init unknown      16 main.py          from app.services.owner_conflict_guard import init as owner_guard_init
owner_input      variable      6 app/bot/states.py owner_input = State()
pdb              unknown       9 app/bot/services/templates_repo.py from app.services import post_watch_db as pdb
pdb              unknown     170 app/bot/handlers1.py from app.services import post_watch_db as pdb
pdb              unknown     203 bot_create_watch.py from app.services import post_watch_db as pdb
pdb              unknown     211 app/bot/handlers1.py from app.services import post_watch_db as pdb
pdb              unknown     255 app/bot/handlers/create_watch.py from app.services import post_watch_db as pdb
pick_order       member       67 app/flows/batch_links/process_links.py def pick_order(self, slots: List[Any]) -> List[Any]:
ping_cmd         function     38 app/plugins/help_and_ping.py async def ping_cmd(event):
post_to_channels function    100 app/services/feature/seed_posts.py async def post_to_channels(
post_to_channels._post_one function    126 app/services/feature/seed_posts.py async def _post_one(ent, link_repr: str):
posts_result_init unknown      17 main.py          from app.services.posts_watch_result_db import init as posts_result_init
postwatch_init   unknown      10 main.py          from app.services.post_watch_db import init as postwatch_init
probe_channel_id function     64 app/services/joiner.py async def probe_channel_id(client, url: str):
process_links    function    409 app/flows/batch_links/process_links.py async def process_links(message, text: str, owner_display: Optional[str] = None, owner_username: Optional[str] = None):
prune_orphan_links function    292 app/services/channel_db.py def prune_orphan_links(max_without_channel: int = 10000) -> int:
pt_init          unknown      10 app/plugins/post_templates.py from app.services.post_watch_db import init as pt_init, add_template, list_templates
raw_connection   function    318 app/services/channel_db.py def raw_connection() -> sqlite3.Connection:
raw_connection   function    552 app/services/posts_watch_result_db.py def raw_connection() -> sqlite3.Connection:
rdb              unknown      17 app/services/requested_reconciler.py from app.services import requested_reconciler_db as rdb
read_col_I       function    339 app/services/gsheets_writer.py def read_col_I(sheet_title: str) -> List[str]:
read_text        function      3 apply_anchored_patch.py def read_text(p):
recent_channels  function    254 app/services/channel_db.py def recent_channels(limit: int = 30) -> List[Tuple]:
recent_links     function    238 app/services/channel_db.py def recent_links(limit: int = 30) -> List[Tuple]:
record_channel   function     38 app/services/feature/seed_db.py def record_channel(peer_id: str, title: str, kind: str, username: Optional[str], invite_link: Optional[str], notes: Optional[str] = None):
record_deleted   function    258 app/services/gsheets_buffer.py def record_deleted(watch_id: int, when_str: str | None = None) -> bool:
record_edited_other_post function    302 app/services/gsheets_buffer.py def record_edited_other_post(watch_id: int, when_str: str | None = None) -> bool:
record_expired   function    274 app/services/gsheets_buffer.py def record_expired(watch_id: int) -> bool:
record_matched   function    232 app/services/gsheets_buffer.py def record_matched(watch_id: int) -> bool:
record_seen_invite function    154 app/services/channel_maps.py async def record_seen_invite(channel_id: int, url: str, kind: str, owner_id: Optional[int]) -> None:
record_views     function    243 app/services/gsheets_buffer.py def record_views(watch_id: int, views: int | None) -> bool:
register_batch   function     47 app/services/monitor_links_bridge.py def register_batch(control_msg_id: int, user_chat_id: int, bot_msg_id: int) -> None:
render_html      function     60 app/services/html_render.py def render_html(msg: Message) -> str:
reqdb            unknown      14 main.py          from app.services import requested_reconciler_db as reqdb
reqdb            unknown      17 app/flows/batch_links/queue_worker.py from app.services import requested_reconciler_db as reqdb
reqdb            unknown      38 app/flows/batch_links/process_links.py from app.services import requested_reconciler_db as reqdb
requested        variable     26 app/plugins/progress_live.py requested: int = 0 # requested (окремо від already)
resolve_channels function     48 app/services/feature/seed_posts.py async def resolve_channels(links: List[str]) -> List[Any]:
resolve_cid_by_target function     27 app/bot/services/channels_repo.py def resolve_cid_by_target(target: str) -> Optional[int]:
router           variable      7 app/bot/handlers/__init__.py router = Router()
router           variable     17 app/bot/handlers/active_watches.py router = Router()
router           variable     17 app/bot/handlers/join_channels.py router = Router()
router           variable     19 app/bot/handlers1.py router = Router()
router           variable     19 bot_create_watch.py router = Router()
router           variable     20 app/bot/handlers/create_watch.py router = Router()
run              function      4 safe_apply_patch.py def run(cmd):
run_bot          function     12 app/bot/run.py   async def run_bot():
run_link_queue_worker function     57 app/flows/batch_links/queue_worker.py async def run_link_queue_worker(client):
run_requested_reconciler function    288 app/services/requested_reconciler.py async def run_requested_reconciler() -> None:
sanitize_link    function      5 app/utils/tg_links.py def sanitize_link(u: str) -> str:
schedule_post    function     41 app/services/feature/seed_post_db.py def schedule_post(peer_id: str, text: str, post_at: int, delete_at: Optional[int]) -> int:
search_channels_by_username function    271 app/services/channel_db.py def search_channels_by_username(substring: str, limit: int = 30) -> List[Tuple]:
send_links       function    171 app/services/feature/seed_creator.py async def send_links(target: str, links: List[str]):
session          variable     53 app/services/requested_reconciler_db.py session: Mapped[str] = mapped_column(String, nullable=False)
session          variable     67 app/services/requested_reconciler_db.py session: Mapped[str] = mapped_column(String, nullable=False)
session          variable    173 app/services/models.py session = Column(Text, nullable=False)
session          variable    207 app/services/models.py session = Column(Text, nullable=False)
session_name     function     58 app/services/account_pool.py def session_name(client: TelegramClient) -> str:
session_scope    function    239 app/services/models.py def session_scope() -> Iterator[Session]:
set_channel_owner function    145 app/services/channel_maps.py async def set_channel_owner(channel_id: int, owner_id: Optional[int]) -> None:
set_current      member       47 app/plugins/progress_live.py def set_current(self, url: str | None = None, actor: str | None = None) -> None:
set_flush_interval function     32 app/services/gsheets_buffer.py def set_flush_interval(seconds: float) -> None:
set_footer       member       72 app/plugins/progress_live.py def set_footer(self, text: str) -> None:
set_invite_owner function    322 app/services/channel_db.py def set_invite_owner(invite_hash: str, owner_display: Optional[str], owner_username: Optional[str]) -> None:
set_processing   function     15 app/bot/processing_guard.py def set_processing(user_id: int, flag: bool, msg_id: int | None = None) -> None:
settings         variable     33 app/services/feature/seed_creator.py settings = _S()
setup            function      4 app/plugins/needle_reply.py def setup(client, control_peer, monitor_buffer):
setup            function      5 app/plugins/metrics_watch.py def setup(client, control_peer, monitor_buffer):
setup            function      8 app/plugins/owner_set.py def setup(client, control_peer=None, monitor_buffer=None, **kwargs):
setup            function     10 app/plugins/resolve_channel.py def setup(control_peer=None, monitor_buffer=None, **kwargs):
setup            function     20 app/plugins/batch_links.py def setup(client, control_peer=None, monitor_buffer=None, **kwargs):
setup            function     27 app/plugins/help_and_ping.py def setup(client, control_peer, monitor_buffer):
setup            function     54 app/services/feature/channel_seed.py def setup(client=None, control_peer=None, monitor_buffer=None):
setup            function    154 app/plugins/channel_info.py def setup(client, control_peer=None, **kwargs):
setup            function    156 app/plugins/monitor_watch.py def setup(*, client=None, control_peer=None, monitor_buffer=None):
setup            function    269 app/plugins/post_templates.py def setup(client, control_peer=None, **kwargs):
setup            function    346 app/plugins/monitor_links.py def setup(client, control_peer: Optional[int] = None, monitor_buffer=None, **kwargs):
setup            function    613 app/plugins/posts_watch_listener.py def setup(client=None, control_peer=None, monitor_buffer=None, **_):
setup._          function     12 app/plugins/resolve_channel.py async def _(ev: events.NewMessage.Event):
setup._          function    175 app/plugins/monitor_watch.py async def _(ev: events.NewMessage.Event):
setup._._json    namespace   359 app/plugins/monitor_watch.py import json as _json
setup._add_tmpl  function    277 app/plugins/post_templates.py async def _add_tmpl(evt):
setup._batch_cancel function     84 app/plugins/batch_links.py async def _batch_cancel(evt):
setup._chat_allowed function    157 app/plugins/channel_info.py def _chat_allowed(event) -> bool:
setup._guarded   function    162 app/plugins/channel_info.py async def _guarded(handler, event):
setup._late_setup function    357 app/plugins/monitor_links.py async def _late_setup():
setup._list      function    386 app/plugins/post_templates.py async def _list(evt):
setup._msg       function    124 app/plugins/batch_links.py async def _msg(evt):
setup._off       function     59 app/plugins/batch_links.py async def _off(evt):
setup._on        function     46 app/plugins/batch_links.py async def _on(evt):
setup._on_owner_clear function    107 app/plugins/owner_set.py async def _on_owner_clear(event):
setup._on_owner_freeform function    119 app/plugins/owner_set.py async def _on_owner_freeform(event):
setup._on_owner_set function     48 app/plugins/owner_set.py async def _on_owner_set(event):
setup._owner_skip function     97 app/plugins/batch_links.py async def _owner_skip(evt):
setup._parse_owner_freeform function     23 app/plugins/owner_set.py def _parse_owner_freeform(raw: str):
setup._resend_last_bg function     78 app/services/feature/channel_seed.py async def _resend_last_bg(n: int):
setup._seed_channels_bg function    105 app/services/feature/channel_seed.py async def _seed_channels_bg(args: Dict[str, str]):
setup._status    function     71 app/plugins/batch_links.py async def _status(evt):
setup.cmd_help   function     61 app/services/feature/channel_seed.py async def cmd_help(event):
setup.cmd_off    function    413 app/plugins/monitor_links.py async def cmd_off(ev):
setup.cmd_on     function    391 app/plugins/monitor_links.py async def cmd_on(ev):
setup.cmd_seed_channels function     98 app/services/feature/channel_seed.py async def cmd_seed_channels(event):
setup.cmd_seed_links function     67 app/services/feature/channel_seed.py async def cmd_seed_links(event):
setup.cmd_status function    380 app/plugins/monitor_links.py async def cmd_status(ev):
setup.help_cmd   function     34 app/plugins/help_and_ping.py async def help_cmd(event):
setup.intake     function    423 app/plugins/monitor_links.py async def intake(ev):
setup.mon_new    function     11 app/plugins/metrics_watch.py async def mon_new(event):
setup.mon_start  function     31 app/plugins/metrics_watch.py async def mon_start(event):
setup.mon_status function     21 app/plugins/metrics_watch.py async def mon_status(event):
setup.needle_clear function     10 app/plugins/needle_reply.py async def needle_clear(event):
setup.needle_from_reply function     22 app/plugins/needle_reply.py async def needle_from_reply(event):
setup.needle_show function     15 app/plugins/needle_reply.py async def needle_show(event):
setup.ping_cmd   function     38 app/plugins/help_and_ping.py async def ping_cmd(event):
setup_join_scheduler function    412 app/services/join_scheduler.py async def setup_join_scheduler(sessions: List[Any]):
setup_logging    function     34 main.py          def setup_logging():
sheet_title_from_time_window_start function    366 app/services/gsheets_writer.py def sheet_title_from_time_window_start(tws: str | None) -> str:
snapshot         function    506 app/services/join_scheduler.py def snapshot() -> Dict[str, Any]:
start            member       41 app/plugins/progress_live.py async def start(self) -> None:
start_channels_exporter function     40 app/services/googlesheets/channels_export_service.py def start_channels_exporter() -> Optional[asyncio.Task]:
start_cmd        function    271 app/bot/handlers1.py async def start_cmd(m: Message, state: FSMContext):
start_cmd        function    278 bot_create_watch.py async def start_cmd(m: Message, state: FSMContext):
start_cmd        function    311 app/bot/handlers/create_watch.py async def start_cmd(m: Message, state: FSMContext):
start_flusher    function    318 app/services/gsheets_buffer.py def start_flusher() -> None:
start_flusher._loop function    324 app/services/gsheets_buffer.py def _loop():
start_pool       function    163 app/services/account_pool.py async def start_pool() -> None:
start_processing function      7 app/bot/user_state.py def start_processing(uid: int):
status           variable     89 app/services/models.py status = Column(Text, nullable=False)
status           variable    133 app/services/models.py status = Column(Text, nullable=False)
status           variable    151 app/services/models.py status = Column(Text, nullable=False)
step_channel_input function    292 app/bot/handlers1.py async def step_channel_input(m: Message, state: FSMContext):
step_channel_input function    299 bot_create_watch.py async def step_channel_input(m: Message, state: FSMContext):
step_channel_input function    335 app/bot/handlers/create_watch.py async def step_channel_input(m: Message, state: FSMContext):
step_template_pick_manual function    306 app/bot/handlers1.py async def step_template_pick_manual(m: Message, state: FSMContext):
step_template_pick_manual function    314 bot_create_watch.py async def step_template_pick_manual(m: Message, state: FSMContext):
step_template_pick_manual function    349 app/bot/handlers/create_watch.py async def step_template_pick_manual(m: Message, state: FSMContext):
step_time_window function    337 app/bot/handlers1.py async def step_time_window(m: Message, state: FSMContext):
step_time_window function    354 bot_create_watch.py async def step_time_window(m: Message, state: FSMContext):
step_time_window function    381 app/bot/handlers/create_watch.py async def step_time_window(m: Message, state: FSMContext):
stop_channels_exporter function     64 app/services/googlesheets/channels_export_service.py async def stop_channels_exporter() -> None:
stop_flusher     function    349 app/services/gsheets_buffer.py def stop_flusher() -> None:
stop_pool        function    184 app/services/account_pool.py async def stop_pool() -> None:
strip_invisible  function      5 app/utils/text_norm.py def strip_invisible(s: str) -> str:
template_pick    variable     10 app/bot/states.py template_pick = State()
templates_kb     function     28 app/bot/keyboards.py def templates_kb(templates):
tg_types         unknown       7 app/utils/link_parser.py from telethon.tl import types as tg_types
tg_types         variable     10 app/utils/link_parser.py tg_types = None
throttle_between_links function     68 app/utils/throttle.py async def throttle_between_links(kind: str | None, url: str = "") -> None:
throttle_invite  function     51 app/utils/throttle.py async def throttle_invite() -> None:
throttle_probe   function     38 app/utils/throttle.py async def throttle_probe(url: str = "") -> None:
throttle_public  function     59 app/utils/throttle.py async def throttle_public() -> None:
time_window      variable     11 app/bot/states.py time_window = State()
title            variable    115 app/services/models.py title = Column(Text, nullable=True)
tries            variable     56 app/services/requested_reconciler_db.py tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
tries            variable     71 app/services/requested_reconciler_db.py tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
tries            variable    177 app/services/models.py tries = Column(Integer, nullable=False, default=0)
tries            variable    211 app/services/models.py tries = Column(Integer, nullable=False, default=0)
ts               variable     90 app/services/models.py ts = Column(Integer, nullable=False)
ts               variable    134 app/services/models.py ts = Column(Integer, nullable=False)
ts               variable    152 app/services/models.py ts = Column(Integer, nullable=False)
ttypes           unknown       6 app/plugins/batch_links.py from telethon.tl import types as ttypes # для перевірки entities/markup
ttypes           unknown       7 app/flows/batch_links/process_links.py from telethon.tl import types as ttypes # для читання MessageEntityTextUrl
ttypes           unknown       7 app/plugins/post_templates.py from telethon.tl import types as ttypes
update_cap       member       58 app/services/join_scheduler.py def update_cap(self, new_cap: int, window_sec: int):
update_progress  function    106 app/services/monitor_links_bridge.py async def update_progress(control_msg_id: int, text: str) -> None:
updated_at       variable    116 app/services/models.py updated_at = Column(Integer, nullable=True)
upsert_channel   function    113 app/services/channel_db.py def upsert_channel(
upsert_channel_core function    121 app/services/channel_maps.py async def upsert_channel_core(channel_id: int, title: Optional[str], owner_id: Optional[int]) -> None:
upsert_channel_facts function     79 app/services/channel_facts.py def upsert_channel_facts(
upsert_membership function    115 app/services/membership_db.py def upsert_membership(account: str, channel_id: int, status: str):
upsert_subscription_joined function    191 app/services/channel_maps.py async def upsert_subscription_joined(channel_id: int, ok: bool, alias: str, err: Optional[str]) -> None:
url              variable    150 app/services/models.py url = Column(Text, primary_key=True)
url_get          function    249 app/services/membership_db.py def url_get(url: str) -> Optional[str]:
url_put          function    241 app/services/membership_db.py def url_put(url: str, status: str):
watch_cancel     function    128 app/bot/handlers/active_watches.py async def watch_cancel(cb: CallbackQuery):
watch_cancel     function    469 app/bot/handlers1.py async def watch_cancel(cb: CallbackQuery):
watch_cancel     function    491 bot_create_watch.py async def watch_cancel(cb: CallbackQuery):
watch_channels   function     45 app/bot/handlers/active_watches.py async def watch_channels(cb: CallbackQuery):
watch_links      function    428 app/bot/handlers1.py async def watch_links(cb: CallbackQuery):
watch_links      function    456 bot_create_watch.py async def watch_links(cb: CallbackQuery):
watch_noop       function     40 app/bot/handlers/active_watches.py async def watch_noop(cb: CallbackQuery):
write_text       function      6 apply_anchored_patch.py def write_text(p, s):
yes_no_kb        function     19 app/bot/keyboards.py def yes_no_kb(yes_cb: str, no_cb: str):
Запуск у PyCharm section      22 README.md        ## Запуск у PyCharm
Команди   section      12 README.md        ## Команди
Можливості section       3 README.md        ## Можливості
```

## Notes

- This file is generated. Do not edit manually.
- Adjust MAX_DEPTH or excludes in scripts/generate-project-map.sh as needed.
