"""Add welcome_email_sent_at to daily_brief_subscriber

Revision ID: a4b5c6d7e8f9
Revises: a2b3c4d5e6f7
Create Date: 2026-01-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4b5c6d7e8f9'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    """Add welcome_email_sent_at column to prevent duplicate welcome emails."""
    op.add_column(
        'daily_brief_subscriber',
        sa.Column('welcome_email_sent_at', sa.DateTime(), nullable=True)
    )


def downgrade():
    """Remove welcome_email_sent_at column."""
    op.drop_column('daily_brief_subscriber', 'welcome_email_sent_at')
