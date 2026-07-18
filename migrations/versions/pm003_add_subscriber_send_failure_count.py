"""Add send_failure_count to daily_brief_subscriber for permanent-failure suppression.

Tracks consecutive permanent (per-recipient) send failures — e.g. a repeated
HTTP 400 from Resend's edge — so a dead-but-not-422 address is auto-suppressed
after a threshold instead of being retried on every brief.

Revision ID: pm003
Revises: pm002
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = 'pm003'
down_revision = 'pm002'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {c['name'] for c in inspector.get_columns('daily_brief_subscriber')}
    if 'send_failure_count' not in columns:
        op.add_column(
            'daily_brief_subscriber',
            sa.Column(
                'send_failure_count',
                sa.Integer(),
                nullable=False,
                server_default='0',
            ),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {c['name'] for c in inspector.get_columns('daily_brief_subscriber')}
    if 'send_failure_count' in columns:
        op.drop_column('daily_brief_subscriber', 'send_failure_count')
