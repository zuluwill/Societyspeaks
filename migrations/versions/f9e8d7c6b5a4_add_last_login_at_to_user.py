"""Add last_login_at to user

Revision ID: f9e8d7c6b5a4
Revises: z3a4b5c6d7e8
Create Date: 2026-03-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f9e8d7c6b5a4'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('last_login_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('user', 'last_login_at')
