"""Add stable unsubscribe_token to daily_question_subscriber

Revision ID: cd2ef3gh4ij5
Revises: ab1cd2ef3gh4
Create Date: 2026-05-28 17:00:00.000000

The daily question batch send called generate_magic_token() before every send,
so the magic_token rotated daily.  Any unsubscribe link in yesterday's email
immediately broke once today's batch ran.

This migration adds a separate, stable unsubscribe_token that is set once and
never rotated, so unsubscribe links in any email the subscriber has ever
received will continue to work indefinitely.
"""
from alembic import op
import sqlalchemy as sa


revision = 'cd2ef3gh4ij5'
down_revision = 'ab1cd2ef3gh4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'daily_question_subscriber',
        sa.Column('unsubscribe_token', sa.String(64), nullable=True, unique=True)
    )

    # gen_random_uuid() is built into PostgreSQL 13+ — no extension needed.
    # Replacing hyphens gives a 32-char cryptographically random hex string.
    # Must NOT be deterministic; a predictable token would let anyone who knows
    # a subscriber's ID or email silently unsubscribe them.
    op.execute("""
        UPDATE daily_question_subscriber
        SET unsubscribe_token = replace(gen_random_uuid()::text, '-', '')
        WHERE unsubscribe_token IS NULL
    """)

    op.create_index(
        'idx_dqs_unsubscribe_token',
        'daily_question_subscriber',
        ['unsubscribe_token']
    )


def downgrade():
    op.drop_index('idx_dqs_unsubscribe_token', table_name='daily_question_subscriber')
    op.drop_column('daily_question_subscriber', 'unsubscribe_token')
