"""add preferred_send_minute to briefing

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2025-01-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'n8o9p0q1r2s3'
down_revision = 'm7n8o9p0q1r2'
branch_labels = None
depends_on = None


def upgrade():
    # Add preferred_send_minute column with default 0
    op.add_column('briefing', sa.Column('preferred_send_minute', sa.Integer(), nullable=True, server_default='0'))
    # Set all existing records to 0 if they're None
    op.execute("UPDATE briefing SET preferred_send_minute = 0 WHERE preferred_send_minute IS NULL")
    # Make it NOT NULL now that all records have values
    op.alter_column('briefing', 'preferred_send_minute', nullable=False, server_default='0')


def downgrade():
    op.drop_column('briefing', 'preferred_send_minute')
