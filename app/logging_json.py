import os
import json
import time
import logging
from typing import Any, Dict, Optional

_RESERVED = {"exc_info", "stack_info", "stacklevel", "extra"}

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.pathname:
            base["file"] = record.pathname
        if record.lineno:
            base["line"] = record.lineno
        if hasattr(record, "context") and record.context:
            base["context"] = record.context
        if hasattr(record, "fields") and record.fields:
            combined = {}
            if hasattr(record, "context") and isinstance(record.context, dict):
                combined.update(record.context)
            combined.update(record.fields)
            base["fields"] = combined
        if record.exc_info:
            try:
                base["exception"] = self.formatException(record.exc_info)
            except Exception:
                pass
        return json.dumps(base, ensure_ascii=False)

class PlainFormatterVerbose(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        parts = []
        if hasattr(record, "context") and record.context:
            parts.extend(f"{k}={record.context[k]!r}" for k in sorted(record.context))
        if hasattr(record, "fields") and record.fields:
            parts.extend(f"{k}={record.fields[k]!r}" for k in sorted(record.fields))
        if parts:
            msg = f"{msg} | " + " ".join(parts)
        return msg

class PlainFormatterClean(logging.Formatter):
    # Стандартний формат без додавання key=value
    pass

class StructuredAdapter(logging.LoggerAdapter):
    def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
        super().__init__(logger, context or {})

    def add_context(self, **ctx):
        self.extra.update(ctx)

    def log(self, level: int, msg: Any, *args, **kwargs):
        if not self.logger.isEnabledFor(level):
            return
        exc_info = kwargs.pop("exc_info", None)
        stack_info = kwargs.pop("stack_info", None)
        stacklevel = kwargs.pop("stacklevel", 1)
        extra = kwargs.pop("extra", {}) or {}

        custom_fields = {}
        for k in list(kwargs.keys()):
            v = kwargs.pop(k)
            if k not in _RESERVED:
                custom_fields[k] = v

        context = dict(self.extra) if self.extra else {}

        if "context" in extra and isinstance(extra["context"], dict):
            merged_ctx = dict(extra["context"])
            merged_ctx.update(context)
            context = merged_ctx
        if "fields" in extra and isinstance(extra["fields"], dict):
            merged_f = dict(extra["fields"])
            merged_f.update(custom_fields)
            custom_fields = merged_f

        extra["context"] = context
        if custom_fields:
            extra["fields"] = custom_fields

        self.logger._log(  # type: ignore[attr-defined]
            level, msg, args,
            exc_info=exc_info,
            extra=extra,
            stack_info=stack_info,
            stacklevel=stacklevel
        )

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")

def configure_logging(force_json: Optional[bool] = None,
                      force_plain_verbose: Optional[bool] = None):
    if force_json is True:
        decided_json = True
    elif force_json is False:
        decided_json = False
    else:
        decided_json = _env_bool("LOG_JSON", False)

    if force_plain_verbose is True:
        show_fields_plain = True
    elif force_plain_verbose is False:
        show_fields_plain = False
    else:
        show_fields_plain = _env_bool("LOG_PLAIN_FIELDS", True)

    root = logging.getLogger()
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # Якщо хендлери вже є (наприклад, хтось налаштував logging.basicConfig),
    # усе одно виставляємо рівні та фільтри для SQLAlchemy і повертаємо.
    if root.handlers:
        root.setLevel(level)
        _configure_sqlalchemy_logging()
        return decided_json

    handler = logging.StreamHandler()
    if decided_json:
        formatter = JSONFormatter()
    else:
        fmt = "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s"
        datefmt = "%H:%M:%S"
        if show_fields_plain:
            formatter = PlainFormatterVerbose(fmt, datefmt)
        else:
            formatter = PlainFormatterClean(fmt, datefmt)
    handler.setFormatter(formatter)
    root.setLevel(level)
    root.addHandler(handler)

    if level == logging.DEBUG:
        logging.getLogger("telethon").setLevel(logging.INFO)

    # Опційний детальний лог для DAO/SQL (вмикається через змінну середовища LOG_DAO_DEBUG=1)
    _configure_sqlalchemy_logging()

    return decided_json


def _configure_sqlalchemy_logging() -> None:
    """
    Налаштовує рівні логів SQLAlchemy залежно від LOG_DAO_DEBUG.
    Викликається завжди, навіть якщо хендлери вже налаштовані раніше.
    """
    if _env_bool("LOG_DAO_DEBUG", False):
        logging.getLogger("app.DAL").setLevel(logging.DEBUG)
        # Дозволяємо службові логи SQLAlchemy, але приглушуємо детальні SQL з Engine
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
        _mute_sqlalchemy_engine_logs()
    else:
        for name in ("sqlalchemy.engine.Engine", "sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy"):
            lg = logging.getLogger(name)
            lg.handlers.clear()
            lg.setLevel(logging.CRITICAL + 10)
            lg.disabled = True
            lg.propagate = False


def _mute_sqlalchemy_engine_logs() -> None:
    """
    Вимикає детальні логи engine (sqlalchemy.engine.Engine), але залишає інші логери SQLAlchemy активними.
    """
    lg = logging.getLogger("sqlalchemy.engine.Engine")
    lg.handlers.clear()
    lg.setLevel(logging.CRITICAL + 10)
    lg.disabled = True
    lg.propagate = False

def get_logger(name: str, **context) -> StructuredAdapter:
    logger = logging.getLogger(name)
    return StructuredAdapter(logger, context or {})
