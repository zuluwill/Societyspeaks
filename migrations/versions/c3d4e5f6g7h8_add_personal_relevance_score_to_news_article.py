"""Add personal_relevance_score to news_article

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-01-07 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6g7h8'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade():
    # Add personal_relevance_score column to news_article table
    with op.batch_alter_table('news_article', schema=None) as batch_op:
        batch_op.add_column(sa.Column('personal_relevance_score', sa.Float(), nullable=True))


def downgrade():
    # Remove personal_relevance_score column from news_article table
    with op.batch_alter_table('news_article', schema=None) as batch_op:
        batch_op.drop_column('personal_relevance_score')
