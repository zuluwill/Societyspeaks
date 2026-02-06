"""Add tier column to partner model

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-02-06
"""
from alembic import op
import sqlalchemy as sa


revision = 'c2d3e4f5g6h7'
down_revision = 'b1c2d3e4f5g6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('partner', sa.Column('tier', sa.String(30), nullable=False, server_default='free'))


def downgrade():
    op.drop_column('partner', 'tier')
