"""Add partner onboarding models and environment flag

Revision ID: a0b1c2d3e4f5
Revises: z3a4b5c6d7e8
Create Date: 2026-02-06
"""
from alembic import op
import sqlalchemy as sa


revision = 'a0b1c2d3e4f5'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'partner',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('contact_email', sa.String(length=150), nullable=False),
        sa.Column('password_hash', sa.String(length=200), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='pending'),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
        sa.Column('billing_status', sa.String(length=30), nullable=False, server_default='inactive'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_partner_status', 'partner', ['status'])
    op.create_index('ix_partner_slug', 'partner', ['slug'], unique=True)
    op.create_index('ix_partner_contact_email', 'partner', ['contact_email'], unique=True)
    op.create_index('ix_partner_stripe_customer_id', 'partner', ['stripe_customer_id'], unique=True)
    op.create_index('ix_partner_stripe_subscription_id', 'partner', ['stripe_subscription_id'], unique=True)

    op.create_table(
        'partner_domain',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('partner_id', sa.Integer(), sa.ForeignKey('partner.id'), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('env', sa.String(length=10), nullable=False, server_default='test'),
        sa.Column('verification_method', sa.String(length=30), nullable=False, server_default='dns_txt'),
        sa.Column('verification_token', sa.String(length=200), nullable=False),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_partner_domain', 'partner_domain', ['domain'])
    op.create_index('idx_partner_domain_env', 'partner_domain', ['env'])

    op.create_table(
        'partner_api_key',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('partner_id', sa.Integer(), sa.ForeignKey('partner.id'), nullable=False),
        sa.Column('key_prefix', sa.String(length=32), nullable=False),
        sa.Column('key_hash', sa.String(length=128), nullable=False),
        sa.Column('key_last4', sa.String(length=4), nullable=False),
        sa.Column('env', sa.String(length=10), nullable=False, server_default='test'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_partner_key_prefix', 'partner_api_key', ['key_prefix'])
    op.create_index('idx_partner_key_hash', 'partner_api_key', ['key_hash'])
    op.create_index('idx_partner_key_env', 'partner_api_key', ['env'])
    op.create_index('idx_partner_key_status', 'partner_api_key', ['status'])

    op.create_table(
        'partner_usage_event',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('partner_id', sa.Integer(), sa.ForeignKey('partner.id'), nullable=False),
        sa.Column('env', sa.String(length=10), nullable=False, server_default='test'),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_partner_usage_event', 'partner_usage_event', ['partner_id', 'env', 'event_type'])

    with op.batch_alter_table('discussion') as batch_op:
        batch_op.add_column(sa.Column('partner_env', sa.String(length=10), nullable=False, server_default='live'))
        batch_op.create_index('ix_discussion_partner_env', ['partner_env'])


def downgrade():
    with op.batch_alter_table('discussion') as batch_op:
        batch_op.drop_index('ix_discussion_partner_env')
        batch_op.drop_column('partner_env')

    op.drop_index('idx_partner_usage_event', table_name='partner_usage_event')
    op.drop_table('partner_usage_event')

    op.drop_index('idx_partner_key_status', table_name='partner_api_key')
    op.drop_index('idx_partner_key_env', table_name='partner_api_key')
    op.drop_index('idx_partner_key_hash', table_name='partner_api_key')
    op.drop_index('idx_partner_key_prefix', table_name='partner_api_key')
    op.drop_table('partner_api_key')

    op.drop_index('idx_partner_domain_env', table_name='partner_domain')
    op.drop_index('idx_partner_domain', table_name='partner_domain')
    op.drop_table('partner_domain')

    op.drop_index('ix_partner_stripe_subscription_id', table_name='partner')
    op.drop_index('ix_partner_stripe_customer_id', table_name='partner')
    op.drop_index('ix_partner_contact_email', table_name='partner')
    op.drop_index('ix_partner_slug', table_name='partner')
    op.drop_index('idx_partner_status', table_name='partner')
    op.drop_table('partner')
