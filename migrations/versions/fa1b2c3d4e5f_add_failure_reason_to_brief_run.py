"""Add failure_reason to brief_run

Adds:
- BriefRun.failure_reason VARCHAR(500) nullable -- records why a run was
  automatically marked failed (e.g. no active recipients, inactive briefing).
  Used by send_approved_brief_runs_job Phase 2 cleanup so ops alerts carry
  actionable context without needing to grep scheduler logs.

Uses column_exists() guard so the migration is safe to run against a database
that already has the column (e.g. dev environments where the column was added
via a direct ALTER TABLE before this migration was written).

Revision ID: fa1b2c3d4e5f
Revises: b2c3d4e5f6a7
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'fa1b2c3d4e5f'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Return True if column_name already exists in table_name."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    if not column_exists('brief_run', 'failure_reason'):
        op.add_column(
            'brief_run',
            sa.Column('failure_reason', sa.String(500), nullable=True)
        )


def downgrade():
    if column_exists('brief_run', 'failure_reason'):
        op.drop_column('brief_run', 'failure_reason')
