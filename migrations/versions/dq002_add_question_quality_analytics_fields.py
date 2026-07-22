"""Add question quality and vote analytics fields for stance loop scoreboard

Revision ID: dq002
Revises: pm003
Create Date: 2026-07-22

- contestability_score: press-posture score at selection time (E3 correlation)
- editorial_contest_rating: subjective 1-5 pre-send rating (editorial ritual)
- posthog_distinct_id on daily_question_response: audit server-side identity
"""
from alembic import op
import sqlalchemy as sa


revision = 'dq002'
down_revision = 'pm003'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('daily_question', schema=None) as batch_op:
        batch_op.add_column(sa.Column('contestability_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('editorial_contest_rating', sa.SmallInteger(), nullable=True))

    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('posthog_distinct_id', sa.String(length=255), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.drop_column('posthog_distinct_id')

    with op.batch_alter_table('daily_question', schema=None) as batch_op:
        batch_op.drop_column('editorial_contest_rating')
        batch_op.drop_column('contestability_score')
