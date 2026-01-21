"""Add analytics columns to brief_run_item

Revision ID: add_brief_analytics_cols
Revises: n8o9p0q1r2s3
Create Date: 2026-01-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers
revision = 'add_brief_analytics_cols'
down_revision = 'n8o9p0q1r2s3'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    # Add new columns to brief_run_item table for analytics (idempotent)
    if not column_exists('brief_run_item', 'topic_category'):
        op.add_column('brief_run_item', sa.Column('topic_category', sa.String(100), nullable=True))
    if not column_exists('brief_run_item', 'sentiment_score'):
        op.add_column('brief_run_item', sa.Column('sentiment_score', sa.Float(), nullable=True))
    if not column_exists('brief_run_item', 'click_count'):
        op.add_column('brief_run_item', sa.Column('click_count', sa.Integer(), server_default='0', nullable=True))
    if not column_exists('brief_run_item', 'selection_score'):
        op.add_column('brief_run_item', sa.Column('selection_score', sa.Float(), nullable=True))


def downgrade():
    if column_exists('brief_run_item', 'selection_score'):
        op.drop_column('brief_run_item', 'selection_score')
    if column_exists('brief_run_item', 'click_count'):
        op.drop_column('brief_run_item', 'click_count')
    if column_exists('brief_run_item', 'sentiment_score'):
        op.drop_column('brief_run_item', 'sentiment_score')
    if column_exists('brief_run_item', 'topic_category'):
        op.drop_column('brief_run_item', 'topic_category')
