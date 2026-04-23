"""Add bluesky_url to individual_profile and company_profile.

Adds a nullable String(255) column on both profile tables so users can
link a Bluesky handle alongside the existing social links.

Revision ID: b1u2e3s4k5y6
Revises: perf001
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa


revision = 'b1u2e3s4k5y6'
down_revision = 'perf001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('individual_profile') as batch_op:
        batch_op.add_column(sa.Column('bluesky_url', sa.String(length=255), nullable=True))

    with op.batch_alter_table('company_profile') as batch_op:
        batch_op.add_column(sa.Column('bluesky_url', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('company_profile') as batch_op:
        batch_op.drop_column('bluesky_url')

    with op.batch_alter_table('individual_profile') as batch_op:
        batch_op.drop_column('bluesky_url')
