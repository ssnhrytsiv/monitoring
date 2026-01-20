"""
Data Access Layer package.

Тут збиратимуться DAO/репозиторії, що працюють зі спільним SessionLocal/ORM.
"""

from app.db.session import SessionLocal, session_scope

__all__ = ["SessionLocal", "session_scope"]
