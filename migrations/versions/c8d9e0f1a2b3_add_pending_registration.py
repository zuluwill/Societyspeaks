"""Hold account signups until the email is confirmed

Revision ID: c8d9e0f1a2b3
Revises: s7n3d5f8h2k4
Create Date: 2026-09-25 14:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c8d9e0f1a2b3'
down_revision = 's7n3d5f8h2k4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pending_registration',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=150), nullable=False),
        sa.Column('username', sa.String(length=150), nullable=False),
        sa.Column('password', sa.String(length=200), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('next_url', sa.String(length=500), nullable=True),
        sa.Column('invitation_token', sa.String(length=255), nullable=True),
        sa.Column('checkout_plan', sa.String(length=50), nullable=True),
        sa.Column('checkout_interval', sa.String(length=20), nullable=True),
        sa.Column('utm_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pending_registration_email', 'pending_registration', ['email'], unique=True)
    op.create_index('ix_pending_registration_token_hash', 'pending_registration', ['token_hash'], unique=True)


def downgrade():
    op.drop_index('ix_pending_registration_token_hash', table_name='pending_registration')
    op.drop_index('ix_pending_registration_email', table_name='pending_registration')
    op.drop_table('pending_registration')
