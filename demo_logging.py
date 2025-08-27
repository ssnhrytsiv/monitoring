#!/usr/bin/env python3
"""
Demonstration of the structured logging system.

Run with different environment variables to see different output formats:
- Default: LOG_LEVEL=INFO (plain verbose)
- LOG_PLAIN_FIELDS=0 (plain clean - hides fields)
- LOG_JSON=1 (JSON output)
- LOG_LEVEL=DEBUG (includes debug messages)

Examples:
  python demo_logging.py
  LOG_PLAIN_FIELDS=0 python demo_logging.py  
  LOG_JSON=1 python demo_logging.py
  LOG_JSON=1 LOG_LEVEL=DEBUG python demo_logging.py
"""

from app.logging_json import get_logger

def demo_structured_logging():
    # Create loggers with different contexts
    main_log = get_logger("demo.main", version="1.0", component="demo")
    user_log = get_logger("demo.user") 
    api_log = get_logger("demo.api", service="telegram", env="prod")
    
    print("=== Structured Logging Demo ===\n")
    
    # Basic logging
    main_log.info("Application started")
    
    # Logging with structured fields
    user_log.info("User logged in", user_id=12345, username="alice", session_duration=3600)
    
    # Old-style formatting still works
    user_log.warning("Login failed for user %s", "bob", attempts=3, ip="192.168.1.100")
    
    # API logging with context and fields
    api_log.debug("API request", method="POST", endpoint="/api/users", response_time_ms=250)
    api_log.error("API timeout", endpoint="/api/channels", timeout_ms=5000, retry_count=2)
    
    # Exception logging
    try:
        result = 10 / 0
    except ZeroDivisionError as e:
        main_log.exception("Division error", operation="10/0", error_type=type(e).__name__)
    
    # Mixed context and fields
    worker_log = get_logger("demo.worker", worker_id="w1", queue="batch_links")
    worker_log.info("Processing batch", batch_size=100, processed=75, failed=3, remaining=22)
    
    print("\n=== Demo Complete ===")

if __name__ == "__main__":
    demo_structured_logging()