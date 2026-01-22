"""Rename link_cache.session to account"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260308_140000_rename_link_cache_session_to_account"
down_revision = "20260308_130000_add_link_cache_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("link_cache", recreate="always") as batch_op:
        batch_op.alter_column("session", new_column_name="account", existing_type=sa.String(), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("link_cache", recreate="always") as batch_op:
        batch_op.alter_column("account", new_column_name="session", existing_type=sa.String(), existing_nullable=True)
