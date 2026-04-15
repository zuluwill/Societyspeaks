"""add discussion follow and updates

Revision ID: p2q3r4s5t6u7
Revises: n0p1q2r3s4t5
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'p2q3r4s5t6u7'
down_revision = 'n0p1q2r3s4t5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'discussion_follow',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('discussion_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'discussion_id', name='uq_discussion_follow_user_discussion'),
    )
    op.create_index('idx_discussion_follow_user_created', 'discussion_follow', ['user_id', 'created_at'])
    op.create_index('idx_discussion_follow_discussion_created', 'discussion_follow', ['discussion_id', 'created_at'])

    op.create_table(
        'discussion_update',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('discussion_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('update_type', sa.String(length=20), nullable=False, server_default='update'),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('links', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_discussion_update_discussion_created', 'discussion_update', ['discussion_id', 'created_at'])
    op.create_index('idx_discussion_update_user_created', 'discussion_update', ['user_id', 'created_at'])


def downgrade():
    op.drop_index('idx_discussion_update_user_created', table_name='discussion_update')
    op.drop_index('idx_discussion_update_discussion_created', table_name='discussion_update')
    op.drop_table('discussion_update')

    op.drop_index('idx_discussion_follow_discussion_created', table_name='discussion_follow')
    op.drop_index('idx_discussion_follow_user_created', table_name='discussion_follow')
    op.drop_table('discussion_follow')
