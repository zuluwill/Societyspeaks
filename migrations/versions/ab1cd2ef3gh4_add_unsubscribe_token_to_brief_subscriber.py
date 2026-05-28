"""Add stable unsubscribe_token to daily_brief_subscriber

Revision ID: ab1cd2ef3gh4
Revises: a0b1c2d3e4f5, f9e8d7c6b5a4, jrs001, m9n8o7p6q5r4, g1a2m3e4p5l6, ee1
Create Date: 2026-05-28 16:00:00.000000

A rotating magic_token is used for authenticated access to the brief.
When it rotates (e.g. user clicks an expired magic link), old unsubscribe
links in previously-sent emails broke because they used the same token.
This migration adds a separate, stable unsubscribe_token that never
rotates, so unsubscribe links in any email the user has ever received
will always work.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ab1cd2ef3gh4'
down_revision = ('a0b1c2d3e4f5', 'f9e8d7c6b5a4', 'jrs001', 'm9n8o7p6q5r4', 'g1a2m3e4p5l6', 'ee1')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'daily_brief_subscriber',
        sa.Column('unsubscribe_token', sa.String(64), nullable=True, unique=True)
    )

    # gen_random_uuid() is built into PostgreSQL 13+ (no extension needed).
    # Replacing hyphens gives a 32-char cryptographically random hex string.
    # This must NOT be deterministic — a predictable token based on id+email
    # would let anyone who knows those values silently unsubscribe someone else.
    op.execute("""
        UPDATE daily_brief_subscriber
        SET unsubscribe_token = replace(gen_random_uuid()::text, '-', '')
        WHERE unsubscribe_token IS NULL
    """)

    op.create_index(
        'idx_dbs_unsubscribe_token',
        'daily_brief_subscriber',
        ['unsubscribe_token']
    )


def downgrade():
    op.drop_index('idx_dbs_unsubscribe_token', table_name='daily_brief_subscriber')
    op.drop_column('daily_brief_subscriber', 'unsubscribe_token')
