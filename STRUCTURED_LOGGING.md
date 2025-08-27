# Structured Logging System

This repository now includes a flexible structured logging system that supports both traditional and structured logging patterns.

## Quick Start

```python
from app.logging_json import get_logger

# Create a logger (replaces logging.getLogger)
log = get_logger("my.module")

# Traditional logging still works
log.info("Processing completed")
log.warning("Failed to process item %s", item_name)

# New structured logging with fields
log.info("User login", user_id=123, username="alice", ip="192.168.1.1")
log.error("API request failed", url="https://api.example.com", status_code=500, retry_count=3)
```

## Output Modes

### Default (Plain Verbose)
Fields are appended as `key=value` pairs:
```
[16:02:06] INFO     my.module: User login user_id=123 username=alice ip=192.168.1.1
```

### Clean Mode (`LOG_PLAIN_FIELDS=0`)
Fields are hidden from display but preserved on LogRecord:
```
[16:02:06] INFO     my.module: User login
```

### JSON Mode (`LOG_JSON=1`)
Structured JSON output:
```json
{"timestamp": "2025-08-27 16:02:06,123", "level": "INFO", "logger": "my.module", "message": "User login", "user_id": 123, "username": "alice", "ip": "192.168.1.1"}
```

## Environment Variables

- `LOG_LEVEL` - Set log level (DEBUG, INFO, WARNING, ERROR)
- `LOG_JSON` - Enable JSON output (1, true, yes, on)  
- `LOG_PLAIN_FIELDS` - Show fields in plain mode (default: 1, set to 0 to hide)

## Context Support

Create loggers with persistent context:

```python
# Logger with context
log = get_logger("worker", component="batch_processor", version="1.2.3")
log.info("Processing started", batch_id="batch:456")
# Output: [INFO] worker: Processing started batch_id=batch:456 component=batch_processor version=1.2.3
```

## Migration

Replace existing logger creation:
```python
# Old way
import logging
log = logging.getLogger("my.module")

# New way  
from app.logging_json import get_logger
log = get_logger("my.module")
```

All existing log calls continue to work unchanged. New structured fields can be added incrementally.

## Demo

Run `python demo_logging.py` to see examples in different modes:
- Default: `python demo_logging.py`
- Clean: `LOG_PLAIN_FIELDS=0 python demo_logging.py`
- JSON: `LOG_JSON=1 python demo_logging.py`