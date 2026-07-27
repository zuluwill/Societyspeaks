"""Add weekly_development to brief_item

Weekly brief items are built by copying the highest-ranked daily item for each
topic. ``weekly_development`` is the one field that is *not* inherited — it holds
a short, week-specific line describing how the story moved across the week, and
is what distinguishes a weekly edition from a rerun of a daily one.

Null for every daily item and for weekly items whose story appeared on only one
day (a single appearance has no development to describe).

Revision ID: wk001
Revises: dq004
Create Date: 2026-07-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'wk001'
down_revision = 'dq004'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('weekly_development', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.drop_column('weekly_development')
