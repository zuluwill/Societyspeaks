"""Add variant_seed to game_run (seeded opening-state variation)

Revision ID: gmr002
Revises: gmr001
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = 'gmr002'
down_revision = 'gmr001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('game_run', schema=None) as batch_op:
        batch_op.add_column(sa.Column('variant_seed', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('game_run', schema=None) as batch_op:
        batch_op.drop_column('variant_seed')
