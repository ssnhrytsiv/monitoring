from __future__ import annotations

import logging
from logging.config import fileConfig
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure project root is on sys.path when running Alembic directly (before imports)
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

"""
Alembic env configured to use the shared ORM Base.
We point target_metadata to app.db.models.Base, which now includes
all common tables (channels, links, networks, sheet_projects, etc.) and
additional service-specific models (InviteCheck, RequestedCheck) via
app.services.models.
"""

from app.db import models as shared_models  # noqa: E402
from app.db.session import engine as shared_engine  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name:
    fileConfig(config.config_file_name)
log = logging.getLogger(__name__)

target_metadata = shared_models.Base.metadata


def get_url() -> str:
    # Shared engine/database URL comes from admin_bot config
    try:
        from app.admin_bot.config import SQLALCHEMY_DATABASE_URL
        return SQLALCHEMY_DATABASE_URL
    except Exception:
        # Fallback to shared engine URL if available
        return str(shared_engine.url)


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config.set_main_option("sqlalchemy.url", get_url())
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
