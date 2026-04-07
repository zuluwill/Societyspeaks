"""Add seed_stance to statement for partner pro/con/neutral labels

Revision ID: 2a3b4c5d6e7f
Revises: g1h2i3j4k5l6
Create Date: 2026-04-07

Stores optional stance from Partner API seed_statements[].position (pro|con|neutral).
Nullable for user-submitted and legacy rows.

Deploy: If the database already ran flask db upgrade beyond g1h2i3j4k5l6 without this
migration (e.g. on a branch that skipped it), run:
  ALTER TABLE statement ADD COLUMN seed_stance VARCHAR(20);
  flask db stamp 2a3b4c5d6e7f
before running flask db upgrade, so Alembic matches the revised graph.
"""
from alembic import op
import sqlalchemy as sa


revision = '2a3b4c5d6e7f'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'statement',
        sa.Column('seed_stance', sa.String(length=20), nullable=True),
    )


def downgrade():
    op.drop_column('statement', 'seed_stance')
