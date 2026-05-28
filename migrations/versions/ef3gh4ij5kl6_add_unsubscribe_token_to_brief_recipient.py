"""Add stable unsubscribe_token to brief_recipient

Revision ID: ef3gh4ij5kl6
Revises: cd2ef3gh4ij5
Create Date: 2026-05-28 18:00:00.000000

BriefingEmailClient called generate_magic_token() before every email send,
rotating the token for every recipient on every send.  Any unsubscribe link
in a previously-delivered briefing email immediately broke when the next
send ran.

This migration adds a separate, stable unsubscribe_token that is set once
and never rotated, so unsubscribe links from any previously sent briefing
email continue to work indefinitely.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ef3gh4ij5kl6'
down_revision = 'cd2ef3gh4ij5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'brief_recipient',
        sa.Column('unsubscribe_token', sa.String(64), nullable=True, unique=True)
    )

    # gen_random_uuid() is built into PostgreSQL 13+ — no extension needed.
    # Replacing hyphens gives a 32-char cryptographically random hex string.
    # Must NOT be deterministic — a predictable token would let anyone who knows
    # a recipient's briefing_id and email silently unsubscribe them.
    op.execute("""
        UPDATE brief_recipient
        SET unsubscribe_token = replace(gen_random_uuid()::text, '-', '')
        WHERE unsubscribe_token IS NULL
    """)

    op.create_index(
        'idx_brief_recipient_unsubscribe_token',
        'brief_recipient',
        ['unsubscribe_token']
    )


def downgrade():
    op.drop_index('idx_brief_recipient_unsubscribe_token', table_name='brief_recipient')
    op.drop_column('brief_recipient', 'unsubscribe_token')
