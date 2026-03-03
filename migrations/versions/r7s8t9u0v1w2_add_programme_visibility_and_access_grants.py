"""add programme visibility and access grants

Revision ID: r7s8t9u0v1w2
Revises: p6q7r8s9t0u1
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'r7s8t9u0v1w2'
down_revision = 'p6q7r8s9t0u1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('programme', sa.Column('visibility', sa.String(length=20), nullable=False, server_default='public'))
    op.create_index('ix_programme_visibility_status', 'programme', ['visibility', 'status'], unique=False)

    op.create_table(
        'programme_access_grant',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('programme_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('invited_by_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['invited_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['programme_id'], ['programme.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('programme_id', 'user_id', name='uq_programme_access_programme_user')
    )
    op.create_index('ix_programme_access_programme_id', 'programme_access_grant', ['programme_id'], unique=False)
    op.create_index('ix_programme_access_user_id', 'programme_access_grant', ['user_id'], unique=False)
    op.create_index('ix_programme_access_status', 'programme_access_grant', ['status'], unique=False)


def downgrade():
    op.drop_index('ix_programme_access_status', table_name='programme_access_grant')
    op.drop_index('ix_programme_access_user_id', table_name='programme_access_grant')
    op.drop_index('ix_programme_access_programme_id', table_name='programme_access_grant')
    op.drop_table('programme_access_grant')

    op.drop_index('ix_programme_visibility_status', table_name='programme')
    op.drop_column('programme', 'visibility')
