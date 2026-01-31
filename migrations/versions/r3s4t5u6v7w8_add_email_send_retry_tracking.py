"""Add attempt_count and failure_reason to BriefEmailSend for retry limiting

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-01-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'r3s4t5u6v7w8'
down_revision = 'q2r3s4t5u6v7'
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
    # Add attempt_count - tracks how many times we've tried to send to this recipient
    if not column_exists('brief_email_send', 'attempt_count'):
        op.add_column('brief_email_send', sa.Column('attempt_count', sa.Integer(), server_default='1', nullable=False))

    # Add failure_reason - stores why the send failed for debugging
    if not column_exists('brief_email_send', 'failure_reason'):
        op.add_column('brief_email_send', sa.Column('failure_reason', sa.String(500), nullable=True))

    # Add composite index for efficient cleanup queries that filter by (brief_run_id, status)
    if not index_exists('brief_email_send', 'idx_brief_email_send_run_status'):
        op.create_index('idx_brief_email_send_run_status', 'brief_email_send', ['brief_run_id', 'status'])


def downgrade():
    op.drop_index('idx_brief_email_send_run_status', table_name='brief_email_send')
    op.drop_column('brief_email_send', 'failure_reason')
    op.drop_column('brief_email_send', 'attempt_count')
