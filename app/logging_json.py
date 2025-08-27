# app/logging_json.py
import json
import logging
import os
from typing import Any, Dict, Optional, Union


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON objects."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Get the basic log data
        log_data = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        
        # Add any extra fields that were passed as kwargs
        if hasattr(record, '_structured_fields'):
            log_data.update(record._structured_fields)
        
        # Add context from StructuredAdapter if present
        if hasattr(record, '_structured_context'):
            log_data.update(record._structured_context)
            
        return json.dumps(log_data, ensure_ascii=False)


class PlainFormatterVerbose(logging.Formatter):
    """Plain text formatter that appends fields as key=value pairs."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Format the base message
        formatted = super().format(record)
        
        # Collect all fields to append
        fields = {}
        if hasattr(record, '_structured_fields'):
            fields.update(record._structured_fields)
        if hasattr(record, '_structured_context'):
            fields.update(record._structured_context)
        
        # Append fields as key=value pairs
        if fields:
            field_strs = []
            for key, value in fields.items():
                field_strs.append(f"{key}={value}")
            formatted += " " + " ".join(field_strs)
            
        return formatted


class PlainFormatterClean(logging.Formatter):
    """Plain text formatter that hides fields but keeps them on LogRecord."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Just format the base message, ignoring fields
        # Fields are still available on the LogRecord for other handlers
        return super().format(record)


class StructuredAdapter(logging.LoggerAdapter):
    """LoggerAdapter that allows passing arbitrary keyword arguments."""
    
    def __init__(self, logger: logging.Logger, extra: Optional[Dict[str, Any]] = None):
        super().__init__(logger, extra or {})
    
    def process(self, msg: Any, kwargs: Dict[str, Any]) -> tuple[Any, Dict[str, Any]]:
        # Extract structured fields from kwargs
        structured_fields = {}
        log_kwargs = {}
        
        for key, value in kwargs.items():
            if key in ('exc_info', 'stack_info', 'stacklevel', 'extra'):
                # These are standard logging kwargs
                log_kwargs[key] = value
            else:
                # These are structured fields
                structured_fields[key] = value
        
        # Add context to log_kwargs extra
        extra = log_kwargs.get('extra', {})
        if structured_fields:
            extra['_structured_fields'] = structured_fields
        if self.extra:
            extra['_structured_context'] = self.extra
        
        if extra:
            log_kwargs['extra'] = extra
            
        return msg, log_kwargs


# Global flag to track if logging has been configured
_configured = False


def configure_logging() -> None:
    """Configure logging based on environment variables. Idempotent."""
    global _configured
    if _configured:
        return
        
    # Get configuration from environment
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_json = os.getenv("LOG_JSON", "").lower() in ("1", "true", "yes", "on")
    log_plain_fields = os.getenv("LOG_PLAIN_FIELDS", "1").lower() not in ("0", "false", "no", "off")
    
    # Choose formatter based on environment
    if log_json:
        formatter = JSONFormatter()
    elif log_plain_fields:
        formatter = PlainFormatterVerbose(
            fmt="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        )
    else:
        formatter = PlainFormatterClean(
            fmt="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s", 
            datefmt="%H:%M:%S"
        )
    
    # Configure root logger
    root_logger = logging.getLogger()
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add new handler with our formatter
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # Reduce telethon noise on DEBUG
    if log_level == "DEBUG":
        logging.getLogger("telethon").setLevel(logging.INFO)
    
    _configured = True


def get_logger(name: str, **context: Any) -> StructuredAdapter:
    """Get a structured logger with optional context."""
    configure_logging()  # Ensure logging is configured
    logger = logging.getLogger(name)
    return StructuredAdapter(logger, context)