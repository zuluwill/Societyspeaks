"""Add stable unsubscribe_token to journey_reminder_subscription

Revision ID: jrs004
Revises: pk002
Create Date: 2026-07-12

Journey reminder emails previously used the rotating resume_token (72h,
regenerated every send) as the unsubscribe link. That broke CAN-SPAM/GDPR
"indefinite unsubscribe" for any email older than the next send. Mirror the
Brief/Daily Question pattern: a set-once unsubscribe_token that never rotates.
"""
from alembic import op
import sqlalchemy as sa


revision = 'jrs004'
down_revision = 'pk002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'journey_reminder_subscription',
        sa.Column('unsubscribe_token', sa.String(64), nullable=True),
    )
    op.execute("""
        UPDATE journey_reminder_subscription
        SET unsubscribe_token = replace(gen_random_uuid()::text, '-', '')
        WHERE unsubscribe_token IS NULL
    """)
    op.create_index(
        'ix_jrs_unsubscribe_token',
        'journey_reminder_subscription',
        ['unsubscribe_token'],
        unique=True,
    )


def downgrade():
    op.drop_index('ix_jrs_unsubscribe_token', table_name='journey_reminder_subscription')
    op.drop_column('journey_reminder_subscription', 'unsubscribe_token')
