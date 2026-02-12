"""add structured metadata fields to daily_question_response

Revision ID: h1i2j3k4l5m6
Revises: c1d2e3f4g5h6
Create Date: 2026-02-12 16:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h1i2j3k4l5m6'
down_revision = 'c1d2e3f4g5h6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confidence_level', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('reason_tag', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('context_expanded', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('source_link_click_count', sa.SmallInteger(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.drop_column('source_link_click_count')
        batch_op.drop_column('context_expanded')
        batch_op.drop_column('reason_tag')
        batch_op.drop_column('confidence_level')
