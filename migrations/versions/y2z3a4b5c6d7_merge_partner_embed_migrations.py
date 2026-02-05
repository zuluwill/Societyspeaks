"""Merge partner embed migrations

Merges:
- x1y2z3a4b5c6_add_discussion_closed_flag
- w8x9y0z1a2b3_add_anonymous_flagging_support

Both descended from v7w8x9y0z1a2 (add_integrity_and_source_fields)

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6, w8x9y0z1a2b3
Create Date: 2026-02-05

"""
from alembic import op
import sqlalchemy as sa


revision = 'y2z3a4b5c6d7'
down_revision = ('x1y2z3a4b5c6', 'w8x9y0z1a2b3')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
