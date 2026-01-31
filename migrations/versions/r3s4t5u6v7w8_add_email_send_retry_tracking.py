"""Add attempt_count and failure_reason to BriefEmailSend for retry limiting

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-01-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'r3s4t5u6v7w8'
down_revision = 'q2r3s4t5u6v7'
branch_labels = None
depends_on = None


def upgrade():
    # Add attempt_count - tracks how many times we've tried to send to this recipient
    op.add_column('brief_email_send', sa.Column('attempt_count', sa.Integer(), server_default='1', nullable=False))

    # Add failure_reason - stores why the send failed for debugging
    op.add_column('brief_email_send', sa.Column('failure_reason', sa.String(500), nullable=True))

    # Add composite index for efficient cleanup queries that filter by (brief_run_id, status)
    op.create_index('idx_brief_email_send_run_status', 'brief_email_send', ['brief_run_id', 'status'])


def downgrade():
    op.drop_index('idx_brief_email_send_run_status', table_name='brief_email_send')
    op.drop_column('brief_email_send', 'failure_reason')
    op.drop_column('brief_email_send', 'attempt_count')
