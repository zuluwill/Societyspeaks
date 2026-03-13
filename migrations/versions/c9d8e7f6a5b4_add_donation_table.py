"""Add donation table

Revision ID: c9d8e7f6a5b4
Revises: 2646b62c01e0
Create Date: 2026-03-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9d8e7f6a5b4'
down_revision = '2646b62c01e0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'donation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stripe_checkout_session_id', sa.String(length=255), nullable=False),
        sa.Column('stripe_payment_intent_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_charge_id', sa.String(length=255), nullable=True),
        sa.Column('amount_pence', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('donor_email', sa.String(length=255), nullable=True),
        sa.Column('donor_name', sa.String(length=255), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('is_anonymous', sa.Boolean(), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_checkout_session_id'),
        sa.UniqueConstraint('stripe_payment_intent_id'),
    )
    with op.batch_alter_table('donation', schema=None) as batch_op:
        batch_op.create_index('idx_donation_status', ['status'], unique=False)
        batch_op.create_index('idx_donation_created_at', ['created_at'], unique=False)
        batch_op.create_index('idx_donation_paid_at', ['paid_at'], unique=False)
        batch_op.create_index('idx_donation_email', ['donor_email'], unique=False)


def downgrade():
    with op.batch_alter_table('donation', schema=None) as batch_op:
        batch_op.drop_index('idx_donation_email')
        batch_op.drop_index('idx_donation_paid_at')
        batch_op.drop_index('idx_donation_created_at')
        batch_op.drop_index('idx_donation_status')

    op.drop_table('donation')
