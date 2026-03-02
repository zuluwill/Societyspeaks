"""add programme_steward table

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'p6q7r8s9t0u1'
down_revision = 'o5p6q7r8s9t0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'programme_steward',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('programme_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='steward'),
        sa.Column('invited_by_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('invite_token', sa.String(length=255), nullable=True),
        sa.Column('invited_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['programme_id'], ['programme.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['invited_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('programme_id', 'user_id', name='uq_programme_steward_programme_user')
    )
    op.create_index('ix_programme_steward_programme_id', 'programme_steward', ['programme_id'], unique=False)
    op.create_index('ix_programme_steward_user_id', 'programme_steward', ['user_id'], unique=False)
    op.create_index('ix_programme_steward_invite_token', 'programme_steward', ['invite_token'], unique=True)


def downgrade():
    op.drop_index('ix_programme_steward_invite_token', table_name='programme_steward')
    op.drop_index('ix_programme_steward_user_id', table_name='programme_steward')
    op.drop_index('ix_programme_steward_programme_id', table_name='programme_steward')
    op.drop_table('programme_steward')
