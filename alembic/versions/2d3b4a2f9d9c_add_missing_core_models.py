"""add missing core models

Revision ID: 2d3b4a2f9d9c
Revises: 1d271c13555e
Create Date: 2026-01-10 22:05:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2d3b4a2f9d9c"
down_revision = "1d271c13555e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # таблиці вже існують у поточній БД; ця ревізія лише вирівнює модель і схему
    pass


def downgrade() -> None:
    pass
