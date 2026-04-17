"""Add timezone and preferred_hour to journey_reminder_subscription

Revision ID: jrs002
Revises: jrs001
Create Date: 2026-04-17

Adds two columns that enable timezone-aware scheduling:
  - timezone:       IANA timezone string (e.g. 'America/New_York'), default 'UTC'
  - preferred_hour: 0–23 integer representing the user's local send-time, default 8

Also migrates any legacy 'commute' cadence rows to 'twice_weekly'.
"""

from alembic import op
import sqlalchemy as sa

revision = 'jrs002'
down_revision = 'jrs001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('journey_reminder_subscription') as batch_op:
        batch_op.add_column(
            sa.Column('timezone', sa.String(50), nullable=False, server_default='UTC')
        )
        batch_op.add_column(
            sa.Column('preferred_hour', sa.Integer(), nullable=False, server_default='8')
        )

    op.execute(
        "UPDATE journey_reminder_subscription SET cadence = 'twice_weekly' WHERE cadence = 'commute'"
    )


def downgrade():
    op.execute(
        "UPDATE journey_reminder_subscription SET cadence = 'commute' WHERE cadence = 'twice_weekly'"
    )
    with op.batch_alter_table('journey_reminder_subscription') as batch_op:
        batch_op.drop_column('preferred_hour')
        batch_op.drop_column('timezone')
