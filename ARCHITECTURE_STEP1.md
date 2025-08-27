# Architecture Step 1: Centralized Scheduling & Rate Limiting

This document describes the first architectural step implemented to reduce flood risk by introducing centralized scheduling, rate limiting, jittered retry logic, and extended membership metadata.

## Overview

The monitoring system now includes a centralized task scheduler that can route JOIN actions through a rate-limited, prioritized queue when the `NEW_SCHEDULER_ENABLED` feature flag is enabled. This provides better control over Telegram API usage and reduces the risk of flood errors.

## Components Added

### 1. Scheduling Package (`app/services/scheduling/`)

#### `models.py`
- `ActionType`: Enum defining task types (JOIN, RESOLVE, FETCH_INFO, OTHER)
- `ScheduledTask`: Dataclass representing a scheduled action with priority, timing, and payload

#### `jitter.py`
- `add_jitter()`: Utility to add random variance to timing to avoid rhythmic patterns

#### `rate_limiter.py`
- `TokenBucket`: Token bucket rate limiting implementation
- `RateLimiterService`: Global and per-account rate limiting service

#### `scheduler.py`
- `TaskScheduler`: Priority-based heap scheduler with time-gated task execution

### 2. Extended Membership Database

Extended the `membership` table with retry-related columns:
- `attempt_count`: Number of retry attempts
- `last_error_code`: Last error encountered
- `next_eligible_ts`: Timestamp when next attempt is eligible

Added helper functions:
- `upsert_membership_with_retry()`: Store membership with retry metadata
- `get_membership_with_retry()`: Retrieve membership with retry metadata
- `increment_attempt_count()`: Update retry counters

### 3. Configuration

Added to `app/config.py`:
- `NEW_SCHEDULER_ENABLED`: Feature flag to enable/disable new scheduler
- `RATE_LIMIT_GLOBAL_DEFAULTS`: Global rate limits per action type
- `RATE_LIMIT_ACCOUNT_DEFAULTS`: Default per-account rate limits

### 4. Enhanced Joiner Service

Updated `app/services/joiner.py`:
- `enqueue_join()`: Add JOIN tasks to scheduler queue
- `scheduler_loop()`: Main async loop processing scheduled tasks
- `retry_refill_loop()`: Stub for future retry refill functionality
- Global scheduler and rate limiter instances

## Usage

### Enable Scheduler
Set environment variable: `NEW_SCHEDULER_ENABLED=true`

### Enqueue JOIN Tasks
```python
from app.services.joiner import enqueue_join

# Add a JOIN task with priority and delay
enqueue_join(url="https://t.me/example", account="user1", priority=50, delay_seconds=10)
```

### Run Scheduler
```python
from app.services.joiner import scheduler_loop
import asyncio

# Start scheduler loop
asyncio.create_task(scheduler_loop())
```

## Rate Limiting

### Global Limits (per action type)
- JOIN: 0.3 requests/second, capacity 2
- RESOLVE: 1.0 requests/second, capacity 5
- FETCH_INFO: 2.0 requests/second, capacity 10

### Per-Account Limits
- Default: 0.2 requests/second, capacity 1

## Implementation Notes

- The scheduler is currently a stub that logs intended actions
- Future steps will integrate with the account pool for actual execution
- Retry refill loop requires URL reconstruction mapping (future enhancement)
- Backward compatibility maintained - existing direct `ensure_join()` calls continue to work

## Integration Points

The scheduler system is designed to integrate with existing flows:
- `app/flows/batch_links/process_links.py` can use `enqueue_join()` when scheduler enabled
- `app/flows/batch_links/queue_worker.py` can route through scheduler
- Existing `ensure_join()` function remains unchanged for direct usage

## Future Steps

1. Integrate scheduler with account pool for actual task execution
2. Implement URL reconstruction for retry refill loop  
3. Add monitoring and metrics for scheduler performance
4. Extend retry logic with exponential backoff strategies