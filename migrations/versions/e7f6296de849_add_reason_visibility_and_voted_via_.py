"""Add reason_visibility and voted_via_email to DailyQuestionResponse

Revision ID: e7f6296de849
Revises: 90af5b74a035
Create Date: 2026-01-11 14:42:11.904439

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7f6296de849'
down_revision = '90af5b74a035'
branch_labels = None
depends_on = None


def upgrade():
    # Add reason_visibility and voted_via_email columns to daily_question_response
    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reason_visibility', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('voted_via_email', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.drop_column('voted_via_email')
        batch_op.drop_column('reason_visibility')
