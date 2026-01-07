"""Add daily brief system

Revision ID: d8e9f0a1b2c3
Revises: c3a2f6d73e0a
Create Date: 2026-01-07 10:07:25.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'd8e9f0a1b2c3'
down_revision = 'c3a2f6d73e0a'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(table_name):
    """Check if a table exists."""
    conn = op.get_bind()
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def upgrade():
    # Add political leaning columns to news_source (conditionally)
    columns_to_add = [
        ('political_leaning', sa.Column('political_leaning', sa.Float(), nullable=True)),
        ('leaning_source', sa.Column('leaning_source', sa.String(length=50), nullable=True)),
        ('leaning_updated_at', sa.Column('leaning_updated_at', sa.DateTime(), nullable=True)),
        ('country', sa.Column('country', sa.String(length=100), nullable=True)),
    ]
    for col_name, col_def in columns_to_add:
        if not column_exists('news_source', col_name):
            with op.batch_alter_table('news_source', schema=None) as batch_op:
                batch_op.add_column(col_def)

    # Create brief_team table (if not exists)
    if not table_exists('brief_team'):
        op.create_table('brief_team',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=True),
            sa.Column('seat_limit', sa.Integer(), nullable=True),
            sa.Column('price_per_seat', sa.Integer(), nullable=True),
            sa.Column('base_price', sa.Integer(), nullable=True),
            sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
            sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
            sa.Column('admin_email', sa.String(length=255), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('brief_team', schema=None) as batch_op:
            batch_op.create_index('idx_brief_team_admin', ['admin_email'], unique=False)

    # Create daily_brief table (if not exists)
    if not table_exists('daily_brief'):
        op.create_table('daily_brief',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('title', sa.String(length=200), nullable=True),
            sa.Column('intro_text', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('auto_selected', sa.Boolean(), nullable=True),
            sa.Column('admin_edited_by', sa.Integer(), nullable=True),
            sa.Column('admin_notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('published_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['admin_edited_by'], ['user.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('date', name='uq_daily_brief_date')
        )
        with op.batch_alter_table('daily_brief', schema=None) as batch_op:
            batch_op.create_index('idx_brief_date', ['date'], unique=False)
            batch_op.create_index('idx_brief_status', ['status'], unique=False)

    # Create daily_brief_subscriber table (if not exists)
    if not table_exists('daily_brief_subscriber'):
        op.create_table('daily_brief_subscriber',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('tier', sa.String(length=20), nullable=True),
            sa.Column('trial_started_at', sa.DateTime(), nullable=True),
            sa.Column('trial_ends_at', sa.DateTime(), nullable=True),
            sa.Column('team_id', sa.Integer(), nullable=True),
            sa.Column('timezone', sa.String(length=50), nullable=True),
            sa.Column('preferred_send_hour', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('unsubscribed_at', sa.DateTime(), nullable=True),
            sa.Column('magic_token', sa.String(length=64), nullable=True),
            sa.Column('magic_token_expires', sa.DateTime(), nullable=True),
            sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
            sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
            sa.Column('subscription_expires_at', sa.DateTime(), nullable=True),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('last_sent_at', sa.DateTime(), nullable=True),
            sa.Column('total_briefs_received', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['team_id'], ['brief_team.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('email')
        )
        with op.batch_alter_table('daily_brief_subscriber', schema=None) as batch_op:
            batch_op.create_index('idx_dbs_email', ['email'], unique=False)
            batch_op.create_index('idx_dbs_status', ['status'], unique=False)
            batch_op.create_index('idx_dbs_team', ['team_id'], unique=False)
            batch_op.create_index('idx_dbs_token', ['magic_token'], unique=False)

    # Create brief_item table (if not exists)
    if not table_exists('brief_item'):
        op.create_table('brief_item',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('brief_id', sa.Integer(), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('trending_topic_id', sa.Integer(), nullable=False),
            sa.Column('headline', sa.String(length=200), nullable=True),
            sa.Column('summary_bullets', sa.JSON(), nullable=True),
            sa.Column('coverage_distribution', sa.JSON(), nullable=True),
            sa.Column('coverage_imbalance', sa.Float(), nullable=True),
            sa.Column('source_count', sa.Integer(), nullable=True),
            sa.Column('sources_by_leaning', sa.JSON(), nullable=True),
            sa.Column('sensationalism_score', sa.Float(), nullable=True),
            sa.Column('sensationalism_label', sa.String(length=20), nullable=True),
            sa.Column('verification_links', sa.JSON(), nullable=True),
            sa.Column('discussion_id', sa.Integer(), nullable=True),
            sa.Column('cta_text', sa.String(length=200), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['brief_id'], ['daily_brief.id'], ),
            sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id'], ),
            sa.ForeignKeyConstraint(['trending_topic_id'], ['trending_topic.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('brief_id', 'position', name='uq_brief_position')
        )
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.create_index('idx_brief_item_brief', ['brief_id'], unique=False)
            batch_op.create_index('idx_brief_item_topic', ['trending_topic_id'], unique=False)


def downgrade():
    # Drop tables in reverse order
    op.drop_table('brief_item')
    op.drop_table('daily_brief_subscriber')
    op.drop_table('daily_brief')
    op.drop_table('brief_team')

    # Remove columns from news_source
    with op.batch_alter_table('news_source', schema=None) as batch_op:
        batch_op.drop_column('country')
        batch_op.drop_column('leaning_updated_at')
        batch_op.drop_column('leaning_source')
        batch_op.drop_column('political_leaning')
