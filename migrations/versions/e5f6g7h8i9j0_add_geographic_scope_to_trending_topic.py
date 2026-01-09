"""Add geographic_scope and geographic_countries to TrendingTopic

Revision ID: e5f6g7h8i9j0
Revises: 3cbe2f0a6b2c
Create Date: 2026-01-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6g7h8i9j0'
down_revision = '3cbe2f0a6b2c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trending_topic', schema=None) as batch_op:
        batch_op.add_column(sa.Column('geographic_scope', sa.String(length=20), nullable=True, server_default='global'))
        batch_op.add_column(sa.Column('geographic_countries', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('trending_topic', schema=None) as batch_op:
        batch_op.drop_column('geographic_countries')
        batch_op.drop_column('geographic_scope')
