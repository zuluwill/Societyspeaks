"""add programme fields to discussion

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l2m3n4o5p6q7'
down_revision = 'k1l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('discussion', sa.Column('programme_id', sa.Integer(), nullable=True))
    op.add_column('discussion', sa.Column('programme_phase', sa.String(length=50), nullable=True))
    op.add_column('discussion', sa.Column('programme_theme', sa.String(length=100), nullable=True))
    op.create_foreign_key('fk_discussion_programme_id', 'discussion', 'programme', ['programme_id'], ['id'])
    op.create_index('idx_discussion_programme_id', 'discussion', ['programme_id'], unique=False)
    op.create_index('idx_discussion_programme_phase', 'discussion', ['programme_id', 'programme_phase'], unique=False)
    op.create_index('idx_discussion_programme_theme', 'discussion', ['programme_id', 'programme_theme'], unique=False)


def downgrade():
    op.drop_index('idx_discussion_programme_theme', table_name='discussion')
    op.drop_index('idx_discussion_programme_phase', table_name='discussion')
    op.drop_index('idx_discussion_programme_id', table_name='discussion')
    op.drop_constraint('fk_discussion_programme_id', 'discussion', type_='foreignkey')
    op.drop_column('discussion', 'programme_theme')
    op.drop_column('discussion', 'programme_phase')
    op.drop_column('discussion', 'programme_id')
