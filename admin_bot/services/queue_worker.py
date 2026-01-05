from __future__ import annotations

# Shim for backward compatibility: import the worker from subscription package.
from admin_bot.services.subscription.subscription_worker import process_batch

__all__ = ["process_batch"]
