"""Add X posting fields to Discussion

Revision ID: f1g2h3i4j5k6
Revises: f740175127e3
Create Date: 2026-01-10 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1g2h3i4j5k6'
down_revision = 'f740175127e3'
branch_labels = None
depends_on = None


def upgrade():
    # Bluesky schedule columns were present in production before this revision
    # (Replit-era / direct schema drift) but were never introduced by a prior
    # Alembic revision. Create them idempotently so from-empty installs can
    # reach this revision. Production already has this revision stamped and
    # will not re-execute this function.
    op.execute("""
        ALTER TABLE discussion
            ADD COLUMN IF NOT EXISTS bluesky_scheduled_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS bluesky_posted_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS bluesky_post_uri VARCHAR(500)
    """)

    # Add X/Twitter posting fields to Discussion model
    # These mirror the existing Bluesky fields for staggered social posting
    op.add_column('discussion', sa.Column('x_scheduled_at', sa.DateTime(), nullable=True))
    op.add_column('discussion', sa.Column('x_posted_at', sa.DateTime(), nullable=True))
    op.add_column('discussion', sa.Column('x_post_id', sa.String(length=100), nullable=True))

    # Add indexes for efficient rate limit queries
    # These are queried frequently to count daily/monthly posts
    op.create_index('idx_discussion_x_posted_at', 'discussion', ['x_posted_at'])
    op.create_index('idx_discussion_x_scheduled_at', 'discussion', ['x_scheduled_at'])

    # Bluesky indexes — IF NOT EXISTS because some environments already had them
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_discussion_bluesky_posted_at "
        "ON discussion (bluesky_posted_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_discussion_bluesky_scheduled_at "
        "ON discussion (bluesky_scheduled_at)"
    )


def downgrade():
    # Remove indexes
    op.execute("DROP INDEX IF EXISTS idx_discussion_bluesky_scheduled_at")
    op.execute("DROP INDEX IF EXISTS idx_discussion_bluesky_posted_at")
    op.drop_index('idx_discussion_x_scheduled_at', 'discussion')
    op.drop_index('idx_discussion_x_posted_at', 'discussion')

    # Remove columns
    op.drop_column('discussion', 'x_post_id')
    op.drop_column('discussion', 'x_posted_at')
    op.drop_column('discussion', 'x_scheduled_at')
    # Do not drop bluesky_* columns on downgrade: they predate this revision
    # in production and other migrations (u0v1w2x3y4z5) still depend on them.
