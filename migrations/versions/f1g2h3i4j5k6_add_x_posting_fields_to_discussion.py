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
    # Add X/Twitter posting fields to Discussion model
    # These mirror the existing Bluesky fields for staggered social posting
    op.add_column('discussion', sa.Column('x_scheduled_at', sa.DateTime(), nullable=True))
    op.add_column('discussion', sa.Column('x_posted_at', sa.DateTime(), nullable=True))
    op.add_column('discussion', sa.Column('x_post_id', sa.String(length=100), nullable=True))


def downgrade():
    op.drop_column('discussion', 'x_post_id')
    op.drop_column('discussion', 'x_posted_at')
    op.drop_column('discussion', 'x_scheduled_at')
