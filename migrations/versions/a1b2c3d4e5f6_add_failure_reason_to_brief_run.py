"""Add failure_reason to brief_run

Adds:
- BriefRun.failure_reason for recording why a run failed (e.g. no recipients,
  inactive briefing).  Used by send_approved_brief_runs_job Phase 2 to tag
  automatically-cleared runs so ops alerts carry actionable context.

Revision ID: a1b2c3d4e5f6
Revises: z3a4b5c6d7e8
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'brief_run',
        sa.Column('failure_reason', sa.String(500), nullable=True)
    )


def downgrade():
    op.drop_column('brief_run', 'failure_reason')
