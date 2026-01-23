"""Add weekly digest email frequency and send preferences to daily question subscribers

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2025-01-23

This migration adds support for weekly digest emails by adding:
- email_frequency: User's preferred frequency ('daily'|'weekly'|'monthly')
- last_weekly_email_sent: Track when weekly digest was last sent
- preferred_send_day: Day of week (0=Monday, 1=Tuesday default, ..., 6=Sunday)
- preferred_send_hour: Hour of day (0-23, default 9 for 9am)
- timezone: User's timezone for localized send times
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'o9p0q1r2s3t4'
down_revision = 'n8o9p0q1r2s3'
branch_labels = None
depends_on = None


def upgrade():
    # Add email_frequency column (default: 'weekly')
    # Note: Existing subscribers will get 'weekly' as default
    op.add_column('daily_question_subscriber',
        sa.Column('email_frequency', sa.String(20), nullable=True))

    # Set default for existing records
    op.execute("UPDATE daily_question_subscriber SET email_frequency = 'weekly' WHERE email_frequency IS NULL")

    # Make it NOT NULL with server default
    op.alter_column('daily_question_subscriber', 'email_frequency',
                    nullable=False, server_default='weekly')

    # Add last_weekly_email_sent for tracking
    op.add_column('daily_question_subscriber',
        sa.Column('last_weekly_email_sent', sa.DateTime(), nullable=True))

    # Add send day preference (0=Mon, 1=Tue default, ..., 6=Sun)
    op.add_column('daily_question_subscriber',
        sa.Column('preferred_send_day', sa.Integer(), nullable=True))

    # Set default for existing records (Tuesday = 1)
    op.execute("UPDATE daily_question_subscriber SET preferred_send_day = 1 WHERE preferred_send_day IS NULL")

    # Make it NOT NULL with server default
    op.alter_column('daily_question_subscriber', 'preferred_send_day',
                    nullable=False, server_default='1')

    # Add send hour preference (0-23, default=9 for 9am)
    op.add_column('daily_question_subscriber',
        sa.Column('preferred_send_hour', sa.Integer(), nullable=True))

    # Set default for existing records
    op.execute("UPDATE daily_question_subscriber SET preferred_send_hour = 9 WHERE preferred_send_hour IS NULL")

    # Make it NOT NULL with server default
    op.alter_column('daily_question_subscriber', 'preferred_send_hour',
                    nullable=False, server_default='9')

    # Add timezone for localized send times (nullable - falls back to UTC)
    op.add_column('daily_question_subscriber',
        sa.Column('timezone', sa.String(50), nullable=True))

    # Create index for frequency filtering (used by scheduler)
    op.create_index('idx_dqs_frequency', 'daily_question_subscriber',
                   ['email_frequency', 'is_active'])

    # Create index for send day scheduling (for efficient hourly job queries)
    op.create_index('idx_dqs_send_day', 'daily_question_subscriber',
                   ['preferred_send_day', 'is_active'])


def downgrade():
    op.drop_index('idx_dqs_send_day', table_name='daily_question_subscriber')
    op.drop_index('idx_dqs_frequency', table_name='daily_question_subscriber')
    op.drop_column('daily_question_subscriber', 'timezone')
    op.drop_column('daily_question_subscriber', 'preferred_send_hour')
    op.drop_column('daily_question_subscriber', 'preferred_send_day')
    op.drop_column('daily_question_subscriber', 'last_weekly_email_sent')
    op.drop_column('daily_question_subscriber', 'email_frequency')
