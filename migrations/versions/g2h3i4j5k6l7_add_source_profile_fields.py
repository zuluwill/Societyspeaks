"""Add source profile fields to NewsSource

Revision ID: g2h3i4j5k6l7
Revises: fd7bceb76f95
Create Date: 2026-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g2h3i4j5k6l7'
down_revision = 'fd7bceb76f95'
branch_labels = None
depends_on = None


def upgrade():
    # Add source profile fields to news_source table
    with op.batch_alter_table('news_source', schema=None) as batch_op:
        # Source profile fields
        batch_op.add_column(sa.Column('slug', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('source_category', sa.String(length=50), nullable=True, server_default='newspaper'))

        # Basic branding (for unclaimed sources)
        batch_op.add_column(sa.Column('logo_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('website_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))

        # Claiming fields
        batch_op.add_column(sa.Column('claim_status', sa.String(length=20), nullable=True, server_default='unclaimed'))
        batch_op.add_column(sa.Column('claimed_by_profile_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('claimed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('claim_requested_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('claim_requested_by_id', sa.Integer(), nullable=True))

        # Create unique index on slug
        batch_op.create_index('idx_news_source_slug', ['slug'], unique=True)

        # Create foreign key constraints
        batch_op.create_foreign_key(
            'fk_news_source_claimed_by_profile',
            'company_profile',
            ['claimed_by_profile_id'],
            ['id'],
            ondelete='SET NULL'
        )
        batch_op.create_foreign_key(
            'fk_news_source_claim_requested_by',
            'user',
            ['claim_requested_by_id'],
            ['id'],
            ondelete='SET NULL'
        )


def downgrade():
    with op.batch_alter_table('news_source', schema=None) as batch_op:
        # Drop foreign keys first
        batch_op.drop_constraint('fk_news_source_claimed_by_profile', type_='foreignkey')
        batch_op.drop_constraint('fk_news_source_claim_requested_by', type_='foreignkey')

        # Drop index
        batch_op.drop_index('idx_news_source_slug')

        # Drop columns
        batch_op.drop_column('claim_requested_by_id')
        batch_op.drop_column('claim_requested_at')
        batch_op.drop_column('claimed_at')
        batch_op.drop_column('claimed_by_profile_id')
        batch_op.drop_column('claim_status')
        batch_op.drop_column('description')
        batch_op.drop_column('website_url')
        batch_op.drop_column('logo_url')
        batch_op.drop_column('source_category')
        batch_op.drop_column('slug')
