"""Add last_monthly_email_sent to daily_question_subscriber

Separates monthly-digest tracking from last_weekly_email_sent so that
subscribers who switch from weekly to monthly are not silently blocked
from their first monthly send for the rest of the calendar month.

Revision ID: m9n8o7p6q5r4
Revises: z3a4b5c6d7e8
Create Date: 2026-04-18

Note: Originally used a1b2c3d4e5f6, which collides with
a1b2c3d4e5f6_add_personal_impact_to_brief_item.py — Alembic requires
globally unique revision IDs.
"""
from alembic import op
import sqlalchemy as sa

revision = 'm9n8o7p6q5r4'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('daily_question_subscriber') as batch_op:
        batch_op.add_column(
            sa.Column('last_monthly_email_sent', sa.DateTime(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('daily_question_subscriber') as batch_op:
        batch_op.drop_column('last_monthly_email_sent')
