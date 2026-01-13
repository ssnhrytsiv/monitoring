"""baseline shared models

Revision ID: 1d271c13555e
Revises: 20240229_010101
Create Date: 2026-01-10 21:35:15.305098
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision = "1d271c13555e"
down_revision = "20240229_010101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline migration: no schema changes; we align alembic_version only.
    pass


def downgrade() -> None:
    # Baseline migration: nothing to revert.
    pass
