"""Add bluesky_claimed_at, bluesky_skipped, x_claimed_at, x_skipped to discussion

Separates the posting claim marker from the success timestamp:
- bluesky_claimed_at: set when a worker picks up the post, cleared on completion
- bluesky_posted_at: now set ONLY when the post is confirmed live (has a URI)
- bluesky_skipped: explicit boolean replacing the 1970-01-01 sentinel date
- x_claimed_at / x_skipped: same pattern for X/Twitter

Revision ID: u0v1w2x3y4z5
Revises: t9u0v1w2x3y4
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa

revision = 'u0v1w2x3y4z5'
down_revision = 't9u0v1w2x3y4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE discussion
            ADD COLUMN IF NOT EXISTS bluesky_claimed_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS bluesky_skipped BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS x_claimed_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS x_skipped BOOLEAN NOT NULL DEFAULT FALSE
    """)

    op.execute("""
        UPDATE discussion
        SET bluesky_skipped = TRUE,
            bluesky_posted_at = NULL
        WHERE bluesky_posted_at = '1970-01-01 00:00:00'
          AND (bluesky_post_uri IS NULL OR bluesky_post_uri = '')
    """)

    op.execute("""
        UPDATE discussion
        SET x_skipped = TRUE,
            x_posted_at = NULL
        WHERE x_posted_at = '1970-01-01 00:00:00'
          AND (x_post_id IS NULL OR x_post_id = '')
    """)


def downgrade():
    op.execute("""
        UPDATE discussion
        SET bluesky_posted_at = '1970-01-01 00:00:00'
        WHERE bluesky_skipped = TRUE
          AND bluesky_posted_at IS NULL
    """)

    op.execute("""
        UPDATE discussion
        SET x_posted_at = '1970-01-01 00:00:00'
        WHERE x_skipped = TRUE
          AND x_posted_at IS NULL
    """)

    op.drop_column('discussion', 'x_skipped')
    op.drop_column('discussion', 'x_claimed_at')
    op.drop_column('discussion', 'bluesky_skipped')
    op.drop_column('discussion', 'bluesky_claimed_at')
