"""Add posthog_confirmed_mirrored_at audit column for E1 mirror health

Revision ID: dq003
Revises: dq002
Create Date: 2026-07-22

Tracks whether email_vote_confirmed was durably mirrored to PostHog for each
daily_question_response row. Enables scoreboard §11 health checks and idempotent
backfill via scripts/mirror_stance_events_to_posthog.py.
"""
from alembic import op
import sqlalchemy as sa


revision = 'dq003'
down_revision = 'dq002'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('posthog_confirmed_mirrored_at', sa.DateTime(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.drop_column('posthog_confirmed_mirrored_at')
