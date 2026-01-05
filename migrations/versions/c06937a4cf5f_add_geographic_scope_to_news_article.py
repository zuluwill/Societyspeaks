"""add_geographic_scope_to_news_article

Revision ID: c06937a4cf5f
Revises: b63f9c268ab9
Create Date: 2026-01-05 11:37:11.653253

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c06937a4cf5f'
down_revision = 'b63f9c268ab9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('news_article', schema=None) as batch_op:
        batch_op.add_column(sa.Column('geographic_scope', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('geographic_countries', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('news_article', schema=None) as batch_op:
        batch_op.drop_column('geographic_countries')
        batch_op.drop_column('geographic_scope')
