"""Add Polymarket integration tables and fields

Revision ID: p1q2r3s4t5u6
Revises: 2646b62c01e0
Create Date: 2026-01-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'p1q2r3s4t5u6'
down_revision = '2646b62c01e0'
branch_labels = None
depends_on = None


def upgrade():
    # Create polymarket_market table
    op.create_table('polymarket_market',
        sa.Column('id', sa.Integer(), nullable=False),
        # Polymarket Identifiers
        sa.Column('condition_id', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=200), nullable=True),
        sa.Column('clob_token_ids', sa.JSON(), nullable=True),
        # Content
        sa.Column('question', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        # Automated Matching
        sa.Column('question_embedding', sa.JSON(), nullable=True),
        # Outcomes & Pricing
        sa.Column('outcomes', sa.JSON(), nullable=True),
        sa.Column('probability', sa.Float(), nullable=True),
        sa.Column('probability_24h_ago', sa.Float(), nullable=True),
        # Quality Signals
        sa.Column('volume_24h', sa.Float(), nullable=True),
        sa.Column('volume_total', sa.Float(), nullable=True),
        sa.Column('liquidity', sa.Float(), nullable=True),
        sa.Column('trader_count', sa.Integer(), nullable=True),
        # Lifecycle
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('end_date', sa.DateTime(), nullable=True),
        sa.Column('resolution', sa.String(length=50), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        # Sync Tracking
        sa.Column('first_seen_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('last_price_update_at', sa.DateTime(), nullable=True),
        sa.Column('sync_failures', sa.Integer(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('condition_id')
    )
    with op.batch_alter_table('polymarket_market', schema=None) as batch_op:
        batch_op.create_index('idx_pm_market_condition', ['condition_id'], unique=False)
        batch_op.create_index('idx_pm_market_category', ['category'], unique=False)
        batch_op.create_index('idx_pm_market_active', ['is_active'], unique=False)
        batch_op.create_index('idx_pm_market_quality', ['is_active', 'volume_24h', 'liquidity'], unique=False)
        batch_op.create_index('idx_pm_market_slug', ['slug'], unique=False)

    # Create topic_market_match table
    op.create_table('topic_market_match',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trending_topic_id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.Integer(), nullable=False),
        # Match Quality
        sa.Column('similarity_score', sa.Float(), nullable=False),
        sa.Column('match_method', sa.String(length=20), nullable=False),
        # Snapshot at Match Time
        sa.Column('probability_at_match', sa.Float(), nullable=True),
        sa.Column('volume_at_match', sa.Float(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['trending_topic_id'], ['trending_topic.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['market_id'], ['polymarket_market.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trending_topic_id', 'market_id', name='uq_topic_market')
    )
    with op.batch_alter_table('topic_market_match', schema=None) as batch_op:
        batch_op.create_index('idx_tmm_topic', ['trending_topic_id'], unique=False)
        batch_op.create_index('idx_tmm_market', ['market_id'], unique=False)
        batch_op.create_index('idx_tmm_similarity', ['similarity_score'], unique=False)

    # Add market_signal to brief_item
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('market_signal', sa.JSON(), nullable=True))

    # Add polymarket_market_id to daily_question
    with op.batch_alter_table('daily_question', schema=None) as batch_op:
        batch_op.add_column(sa.Column('polymarket_market_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_daily_question_polymarket_market',
            'polymarket_market',
            ['polymarket_market_id'],
            ['id']
        )


def downgrade():
    # Remove polymarket_market_id from daily_question
    with op.batch_alter_table('daily_question', schema=None) as batch_op:
        batch_op.drop_constraint('fk_daily_question_polymarket_market', type_='foreignkey')
        batch_op.drop_column('polymarket_market_id')

    # Remove market_signal from brief_item
    with op.batch_alter_table('brief_item', schema=None) as batch_op:
        batch_op.drop_column('market_signal')

    # Drop topic_market_match table
    with op.batch_alter_table('topic_market_match', schema=None) as batch_op:
        batch_op.drop_index('idx_tmm_similarity')
        batch_op.drop_index('idx_tmm_market')
        batch_op.drop_index('idx_tmm_topic')
    op.drop_table('topic_market_match')

    # Drop polymarket_market table
    with op.batch_alter_table('polymarket_market', schema=None) as batch_op:
        batch_op.drop_index('idx_pm_market_slug')
        batch_op.drop_index('idx_pm_market_quality')
        batch_op.drop_index('idx_pm_market_active')
        batch_op.drop_index('idx_pm_market_category')
        batch_op.drop_index('idx_pm_market_condition')
    op.drop_table('polymarket_market')
