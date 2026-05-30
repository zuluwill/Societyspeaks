"""Index programme_steward.pending_email

Revision ID: fg4hi5jk6lm7
Revises: ef3gh4ij5kl6
Create Date: 2026-05-30 12:00:00.000000

On every successful user registration, auth.register queries:
    ProgrammeSteward.query.filter_by(pending_email=<new_email>, status='pending')

Without an index this is a full table scan on programme_steward.  At low
registration volume it's negligible, but under the current GPTBot crawl
pattern and real user signups the unindexed scan was the most likely cause
of the "Inefficient Database Queries" APM warning flagged on auth.register.
"""
from alembic import op


revision = 'fg4hi5jk6lm7'
down_revision = 'ef3gh4ij5kl6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_programme_steward_pending_email',
        'programme_steward',
        ['pending_email'],
    )


def downgrade():
    op.drop_index('ix_programme_steward_pending_email', table_name='programme_steward')
