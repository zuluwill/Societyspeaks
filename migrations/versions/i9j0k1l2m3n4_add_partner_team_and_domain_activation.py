"""add partner team members and domain activation

Revision ID: i9j0k1l2m3n4
Revises: h1i2j3k4l5m6
Create Date: 2026-02-12 19:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'i9j0k1l2m3n4'
down_revision = 'h1i2j3k4l5m6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('partner_domain', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        'partner_member',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('partner_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=150), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=True),
        sa.Column('password_hash', sa.String(length=200), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='member'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('invite_token', sa.String(length=255), nullable=True),
        sa.Column('invited_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['partner_id'], ['partner.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='ix_partner_member_email'),
        sa.UniqueConstraint('invite_token', name='ix_partner_member_invite_token'),
    )
    op.create_index('ix_partner_member_partner_id', 'partner_member', ['partner_id'], unique=False)
    op.create_index('ix_partner_member_status', 'partner_member', ['status'], unique=False)


def downgrade():
    op.drop_index('ix_partner_member_status', table_name='partner_member')
    op.drop_index('ix_partner_member_partner_id', table_name='partner_member')
    op.drop_table('partner_member')

    with op.batch_alter_table('partner_domain', schema=None) as batch_op:
        batch_op.drop_column('is_active')
