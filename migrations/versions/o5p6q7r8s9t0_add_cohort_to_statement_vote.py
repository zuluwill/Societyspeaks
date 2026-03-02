"""add cohort_slug to statement_vote

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'o5p6q7r8s9t0'
down_revision = 'n4o5p6q7r8s9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('statement_vote', sa.Column('cohort_slug', sa.String(length=80), nullable=True))
    op.create_index('idx_vote_discussion_cohort', 'statement_vote', ['discussion_id', 'cohort_slug'], unique=False)


def downgrade():
    op.drop_index('idx_vote_discussion_cohort', table_name='statement_vote')
    op.drop_column('statement_vote', 'cohort_slug')
