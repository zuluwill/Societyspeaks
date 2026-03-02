"""add cohort and viewed fields to discussion_participant

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'n4o5p6q7r8s9'
down_revision = 'm3n4o5p6q7r8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('discussion_participant', sa.Column('cohort_slug', sa.String(length=80), nullable=True))
    op.add_column('discussion_participant', sa.Column('viewed_information_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('discussion_participant', 'viewed_information_at')
    op.drop_column('discussion_participant', 'cohort_slug')
