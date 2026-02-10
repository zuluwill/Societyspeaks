"""Add composite indexes for partner models

Revision ID: 2938ecbcf765
Revises: e4f5g6h7i8j9
Create Date: 2026-02-10 15:12:15.432490

"""
from alembic import op

revision = '2938ecbcf765'
down_revision = 'e4f5g6h7i8j9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('partner_api_key', schema=None) as batch_op:
        batch_op.create_index('idx_partner_key_hash_status', ['key_hash', 'status'], unique=False)

    with op.batch_alter_table('partner_domain', schema=None) as batch_op:
        batch_op.create_index('idx_partner_domain_domain_env', ['domain', 'env'], unique=False)


def downgrade():
    with op.batch_alter_table('partner_domain', schema=None) as batch_op:
        batch_op.drop_index('idx_partner_domain_domain_env')

    with op.batch_alter_table('partner_api_key', schema=None) as batch_op:
        batch_op.drop_index('idx_partner_key_hash_status')
