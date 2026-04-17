"""Add preferred_minute to JourneyReminderSubscription

Revision ID: jrs003
Revises: jrs002
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'jrs003'
down_revision = 'jrs002'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('journey_reminder_subscription', schema=None) as batch_op:
        batch_op.add_column(sa.Column('preferred_minute', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('journey_reminder_subscription', schema=None) as batch_op:
        batch_op.drop_column('preferred_minute')
