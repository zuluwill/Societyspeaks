"""merge_migration_heads

Revision ID: ba07c61956b4
Revises: 6e3b548fa825, add_brief_analytics_cols
Create Date: 2026-01-21 09:13:30.920928

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ba07c61956b4'
down_revision = ('6e3b548fa825', 'add_brief_analytics_cols')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
