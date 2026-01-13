"""
Data Access Layer package.

Тут збиратимуться DAO/репозиторії, що працюють зі спільним SessionLocal/ORM.
"""

from app.services.models import SessionLocal, session_scope  # re-export for convenience

__all__ = ["SessionLocal", "session_scope"]
