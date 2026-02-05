"""Merge all migration heads into single head

Merges:
- cff133064e02 (existing email send retry merge)
- y2z3a4b5c6d7 (partner embed merge)

This creates a single migration head for deployment.

Revision ID: z3a4b5c6d7e8
Revises: cff133064e02, y2z3a4b5c6d7
Create Date: 2026-02-05

"""
from alembic import op
import sqlalchemy as sa


revision = 'z3a4b5c6d7e8'
down_revision = ('cff133064e02', 'y2z3a4b5c6d7')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
