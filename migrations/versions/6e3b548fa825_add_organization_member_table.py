"""add_organization_member_table

Revision ID: 6e3b548fa825
Revises: n8o9p0q1r2s3
Create Date: 2026-01-19 19:23:42.221496

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e3b548fa825'
down_revision = 'n8o9p0q1r2s3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'organization_member',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='editor'),
        sa.Column('invited_by_id', sa.Integer(), nullable=True),
        sa.Column('invited_at', sa.DateTime(), nullable=True),
        sa.Column('joined_at', sa.DateTime(), nullable=True),
        sa.Column('invite_token', sa.String(64), nullable=True),
        sa.Column('invite_email', sa.String(255), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['org_id'], ['company_profile.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('org_id', 'user_id', name='uq_org_member'),
        sa.UniqueConstraint('invite_token', name='uq_org_member_invite_token'),
    )
    op.create_index('idx_org_member_org', 'organization_member', ['org_id'])
    op.create_index('idx_org_member_user', 'organization_member', ['user_id'])


def downgrade():
    op.drop_index('idx_org_member_user', table_name='organization_member')
    op.drop_index('idx_org_member_org', table_name='organization_member')
    op.drop_table('organization_member')
