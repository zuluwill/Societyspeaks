"""Merge vote integrity constraints and consensus job queue migrations

Merges:
- v1w2x3y4z5a6 (Phase 0: vote integrity constraints + participant dedup)
- q9r8s7t6u5v4 (Phase 3: consensus job queue table)

Revision ID: a3b4c5d6e7f8
Revises: v1w2x3y4z5a6, q9r8s7t6u5v4
Create Date: 2026-03-09

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a3b4c5d6e7f8'
down_revision = ('v1w2x3y4z5a6', 'q9r8s7t6u5v4')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
