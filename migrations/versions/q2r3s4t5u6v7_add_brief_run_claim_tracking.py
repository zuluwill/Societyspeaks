"""Add claimed_at and send_attempts to BriefRun for duplicate send prevention

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-01-31 10:55:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'q2r3s4t5u6v7'
down_revision = 'p1q2r3s4t5u6'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def index_exists(table_name, index_name):
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade():
    # Add claimed_at - timestamp when a process claimed this for sending
    if not column_exists('brief_run', 'claimed_at'):
        op.add_column('brief_run', sa.Column('claimed_at', sa.DateTime(), nullable=True))
    
    # Add send_attempts - count of send attempts for monitoring/debugging
    if not column_exists('brief_run', 'send_attempts'):
        op.add_column('brief_run', sa.Column('send_attempts', sa.Integer(), server_default='0', nullable=False))
    
    # Add index on status + claimed_at for efficient stuck-send recovery queries
    if not index_exists('brief_run', 'idx_brief_run_status_claimed'):
        op.create_index('idx_brief_run_status_claimed', 'brief_run', ['status', 'claimed_at'])


def downgrade():
    op.drop_index('idx_brief_run_status_claimed', table_name='brief_run')
    op.drop_column('brief_run', 'send_attempts')
    op.drop_column('brief_run', 'claimed_at')
