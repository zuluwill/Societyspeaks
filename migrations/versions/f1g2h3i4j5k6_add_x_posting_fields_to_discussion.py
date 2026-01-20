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
    from sqlalchemy import inspect
    from sqlalchemy.engine import Engine
    
    # Add X/Twitter posting fields to Discussion model
    # These mirror the existing Bluesky fields for staggered social posting
    op.add_column('discussion', sa.Column('x_scheduled_at', sa.DateTime(), nullable=True))
    op.add_column('discussion', sa.Column('x_posted_at', sa.DateTime(), nullable=True))
    op.add_column('discussion', sa.Column('x_post_id', sa.String(length=100), nullable=True))
    
    # Also add Bluesky columns if they don't exist (may have been added directly)
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_columns = [col['name'] for col in inspector.get_columns('discussion')]
    
    if 'bluesky_scheduled_at' not in existing_columns:
        op.add_column('discussion', sa.Column('bluesky_scheduled_at', sa.DateTime(), nullable=True))
    if 'bluesky_posted_at' not in existing_columns:
        op.add_column('discussion', sa.Column('bluesky_posted_at', sa.DateTime(), nullable=True))
    if 'bluesky_post_uri' not in existing_columns:
        op.add_column('discussion', sa.Column('bluesky_post_uri', sa.String(length=500), nullable=True))
    
    # Add indexes for efficient rate limit queries
    # These are queried frequently to count daily/monthly posts
    op.create_index('idx_discussion_x_posted_at', 'discussion', ['x_posted_at'])
    op.create_index('idx_discussion_x_scheduled_at', 'discussion', ['x_scheduled_at'])
    
    # Also add index for Bluesky posted_at if not exists (for consistency)
    op.create_index('idx_discussion_bluesky_posted_at', 'discussion', ['bluesky_posted_at'])
    op.create_index('idx_discussion_bluesky_scheduled_at', 'discussion', ['bluesky_scheduled_at'])


def downgrade():
    # Remove indexes
    op.drop_index('idx_discussion_bluesky_scheduled_at', 'discussion')
    op.drop_index('idx_discussion_bluesky_posted_at', 'discussion')
    op.drop_index('idx_discussion_x_scheduled_at', 'discussion')
    op.drop_index('idx_discussion_x_posted_at', 'discussion')
    
    # Remove columns
    op.drop_column('discussion', 'x_post_id')
    op.drop_column('discussion', 'x_posted_at')
    op.drop_column('discussion', 'x_scheduled_at')
