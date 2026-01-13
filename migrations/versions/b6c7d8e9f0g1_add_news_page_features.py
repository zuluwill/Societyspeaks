"""Add news page features: NewsPerspectiveCache and AdminSettings

Revision ID: b6c7d8e9f0g1
Revises: a4b5c6d7e8f9
Create Date: 2026-01-13 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b6c7d8e9f0g1'
down_revision = 'i3j4k5l6m7n8'
branch_labels = None
depends_on = None


def upgrade():
    """Add NewsPerspectiveCache and AdminSettings tables for news transparency page."""

    # Create news_perspective_cache table
    op.create_table(
        'news_perspective_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trending_topic_id', sa.Integer(), nullable=False),
        sa.Column('perspectives', sa.JSON(), nullable=True),
        sa.Column('so_what', sa.Text(), nullable=True),
        sa.Column('personal_impact', sa.Text(), nullable=True),
        sa.Column('generated_date', sa.Date(), nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['trending_topic_id'], ['trending_topic.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trending_topic_id', 'generated_date', name='uq_npc_topic_date')
    )

    # Create indexes
    op.create_index(
        'idx_npc_topic_date',
        'news_perspective_cache',
        ['trending_topic_id', 'generated_date']
    )

    # Create admin_settings table
    op.create_table(
        'admin_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key')
    )


def downgrade():
    """Remove NewsPerspectiveCache and AdminSettings tables."""
    op.drop_table('admin_settings')
    op.drop_index('idx_npc_topic_date', table_name='news_perspective_cache')
    op.drop_table('news_perspective_cache')
