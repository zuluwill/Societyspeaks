"""Add briefing system v2 models

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'j4k5l6m7n8o9'
down_revision = 'i3j4k5l6m7n8'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if a table exists."""
    conn = op.get_bind()
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def upgrade():
    # Create brief_template table
    if not table_exists('brief_template'):
        op.create_table('brief_template',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('slug', sa.String(length=100), nullable=True),
            sa.Column('default_sources', sa.JSON(), nullable=True),
            sa.Column('default_filters', sa.JSON(), nullable=True),
            sa.Column('default_cadence', sa.String(length=20), nullable=True),
            sa.Column('default_tone', sa.String(length=50), nullable=True),
            sa.Column('allow_customization', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name'),
            sa.UniqueConstraint('slug')
        )
        with op.batch_alter_table('brief_template', schema=None) as batch_op:
            batch_op.create_index('idx_brief_template_name', ['name'], unique=False)

    # Create input_source table
    if not table_exists('input_source'):
        op.create_table('input_source',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('owner_type', sa.String(length=20), nullable=False),
            sa.Column('owner_id', sa.Integer(), nullable=True),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('type', sa.String(length=50), nullable=False),
            sa.Column('config_json', sa.JSON(), nullable=True),
            sa.Column('storage_key', sa.String(length=500), nullable=True),
            sa.Column('storage_url', sa.String(length=500), nullable=True),
            sa.Column('extracted_text', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=30), nullable=True),
            sa.Column('extraction_error', sa.Text(), nullable=True),
            sa.Column('enabled', sa.Boolean(), nullable=True),
            sa.Column('last_fetched_at', sa.DateTime(), nullable=True),
            sa.Column('fetch_error_count', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('input_source', schema=None) as batch_op:
            batch_op.create_index('idx_input_source_owner', ['owner_type', 'owner_id'], unique=False)
            batch_op.create_index('idx_input_source_type', ['type'], unique=False)
            batch_op.create_index('idx_input_source_status', ['status'], unique=False)

    # Create ingested_item table
    if not table_exists('ingested_item'):
        op.create_table('ingested_item',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('source_id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=500), nullable=False),
            sa.Column('url', sa.String(length=1000), nullable=True),
            sa.Column('source_name', sa.String(length=200), nullable=True),
            sa.Column('published_at', sa.DateTime(), nullable=True),
            sa.Column('fetched_at', sa.DateTime(), nullable=True),
            sa.Column('content_text', sa.Text(), nullable=True),
            sa.Column('content_hash', sa.String(length=64), nullable=False),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('storage_key', sa.String(length=500), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['source_id'], ['input_source.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('source_id', 'content_hash', name='uq_source_content_hash')
        )
        with op.batch_alter_table('ingested_item', schema=None) as batch_op:
            batch_op.create_index('idx_ingested_source_fetched', ['source_id', 'fetched_at'], unique=False)
            batch_op.create_index('idx_ingested_published', ['published_at'], unique=False)

    # Create sending_domain table (needed before briefing for FK)
    if not table_exists('sending_domain'):
        op.create_table('sending_domain',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('org_id', sa.Integer(), nullable=False),
            sa.Column('domain', sa.String(length=255), nullable=False),
            sa.Column('status', sa.String(length=30), nullable=True),
            sa.Column('resend_domain_id', sa.String(length=255), nullable=True),
            sa.Column('dns_records_required', sa.JSON(), nullable=True),
            sa.Column('verified_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['org_id'], ['company_profile.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('domain')
        )
        with op.batch_alter_table('sending_domain', schema=None) as batch_op:
            batch_op.create_index('idx_sending_domain_org', ['org_id'], unique=False)
            batch_op.create_index('idx_sending_domain_status', ['status'], unique=False)

    # Create briefing table
    if not table_exists('briefing'):
        op.create_table('briefing',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('owner_type', sa.String(length=20), nullable=False),
            sa.Column('owner_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('theme_template_id', sa.Integer(), nullable=True),
            sa.Column('cadence', sa.String(length=20), nullable=True),
            sa.Column('timezone', sa.String(length=50), nullable=True),
            sa.Column('preferred_send_hour', sa.Integer(), nullable=True),
            sa.Column('mode', sa.String(length=20), nullable=True),
            sa.Column('visibility', sa.String(length=20), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('from_name', sa.String(length=200), nullable=True),
            sa.Column('from_email', sa.String(length=255), nullable=True),
            sa.Column('sending_domain_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['theme_template_id'], ['brief_template.id'], ),
            sa.ForeignKeyConstraint(['sending_domain_id'], ['sending_domain.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('briefing', schema=None) as batch_op:
            batch_op.create_index('idx_briefing_owner', ['owner_type', 'owner_id'], unique=False)
            batch_op.create_index('idx_briefing_status', ['status'], unique=False)
            batch_op.create_index('idx_briefing_visibility', ['visibility'], unique=False)

    # Create briefing_source table (many-to-many)
    if not table_exists('briefing_source'):
        op.create_table('briefing_source',
            sa.Column('briefing_id', sa.Integer(), nullable=False),
            sa.Column('source_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['briefing_id'], ['briefing.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['source_id'], ['input_source.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('briefing_id', 'source_id'),
            sa.UniqueConstraint('briefing_id', 'source_id', name='uq_briefing_source')
        )

    # Create brief_run table
    if not table_exists('brief_run'):
        op.create_table('brief_run',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('briefing_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(length=30), nullable=True),
            sa.Column('draft_markdown', sa.Text(), nullable=True),
            sa.Column('draft_html', sa.Text(), nullable=True),
            sa.Column('approved_markdown', sa.Text(), nullable=True),
            sa.Column('approved_html', sa.Text(), nullable=True),
            sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
            sa.Column('approved_at', sa.DateTime(), nullable=True),
            sa.Column('scheduled_at', sa.DateTime(), nullable=False),
            sa.Column('generated_at', sa.DateTime(), nullable=True),
            sa.Column('sent_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['briefing_id'], ['briefing.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['approved_by_user_id'], ['user.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('brief_run', schema=None) as batch_op:
            batch_op.create_index('idx_brief_run_briefing', ['briefing_id'], unique=False)
            batch_op.create_index('idx_brief_run_status', ['status'], unique=False)
            batch_op.create_index('idx_brief_run_scheduled', ['scheduled_at'], unique=False)

    # Create brief_run_item table
    if not table_exists('brief_run_item'):
        op.create_table('brief_run_item',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('brief_run_id', sa.Integer(), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('ingested_item_id', sa.Integer(), nullable=True),
            sa.Column('trending_topic_id', sa.Integer(), nullable=True),
            sa.Column('headline', sa.String(length=200), nullable=True),
            sa.Column('summary_bullets', sa.JSON(), nullable=True),
            sa.Column('content_markdown', sa.Text(), nullable=True),
            sa.Column('content_html', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['brief_run_id'], ['brief_run.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['ingested_item_id'], ['ingested_item.id'], ),
            sa.ForeignKeyConstraint(['trending_topic_id'], ['trending_topic.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('brief_run_id', 'position', name='uq_brief_run_position')
        )
        with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
            batch_op.create_index('idx_brief_run_item_run', ['brief_run_id'], unique=False)

    # Create brief_recipient table
    if not table_exists('brief_recipient'):
        op.create_table('brief_recipient',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('briefing_id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('unsubscribed_at', sa.DateTime(), nullable=True),
            sa.Column('magic_token', sa.String(length=64), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['briefing_id'], ['briefing.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('briefing_id', 'email', name='uq_briefing_recipient'),
            sa.UniqueConstraint('magic_token')
        )
        with op.batch_alter_table('brief_recipient', schema=None) as batch_op:
            batch_op.create_index('idx_brief_recipient_status', ['briefing_id', 'status'], unique=False)
            batch_op.create_index('idx_brief_recipient_token', ['magic_token'], unique=False)

    # Create brief_edit table
    if not table_exists('brief_edit'):
        op.create_table('brief_edit',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('brief_run_id', sa.Integer(), nullable=False),
            sa.Column('edited_by_user_id', sa.Integer(), nullable=False),
            sa.Column('content_markdown', sa.Text(), nullable=True),
            sa.Column('content_html', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['brief_run_id'], ['brief_run.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['edited_by_user_id'], ['user.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('brief_edit', schema=None) as batch_op:
            batch_op.create_index('idx_brief_edit_run', ['brief_run_id'], unique=False)
            batch_op.create_index('idx_brief_edit_user', ['edited_by_user_id'], unique=False)


def downgrade():
    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table('brief_edit')
    op.drop_table('brief_recipient')
    op.drop_table('brief_run_item')
    op.drop_table('brief_run')
    op.drop_table('briefing_source')
    op.drop_table('briefing')
    op.drop_table('sending_domain')
    op.drop_table('ingested_item')
    op.drop_table('input_source')
    op.drop_table('brief_template')
