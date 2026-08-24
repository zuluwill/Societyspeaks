"""Repair model/schema parity: billing + briefing analytics columns

Revision ID: 30a9831d56e0
Revises: wk001
Create Date: 2026-08-24

WHY THIS EXISTS
---------------
SQLAlchemy models for paid briefings / billing grew ahead of the Alembic
graph. Five tables were never `create_table`'d in any revision
(`pricing_plan`, `subscription`, `brief_email_open`, `brief_email_send`,
`brief_link_click`), and dozens of columns were added only on the models
after thin creates (`j4k5`, `d8e9`, …). Mid-chain "sibling branch" alters
(`r3s4`, `c4d5`, `bes001`, `pk002`, `f0a1`) intentionally no-op when those
tables/columns are missing, so from-empty `flask db upgrade` stopped at
`wk001` with HIGH schema drift (and runtime failures such as
`user.stripe_customer_id does not exist`).

Production databases that already gained these objects via `create_all`,
manual SQL, or an unmerged branch stay safe: every step is idempotent
(`checkfirst` / `IF NOT EXISTS`).

This is the same repair pattern as `r1e2p3a4i5r6` / `bes001` / `pk002`.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = '30a9831d56e0'
down_revision = 'wk001'
branch_labels = None
depends_on = None


def _inspector():
    return inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return name in _inspector().get_table_names()


def _column_names(table: str) -> set:
    if not _table_exists(table):
        return set()
    return {c['name'] for c in _inspector().get_columns(table)}


def _index_names(table: str) -> set:
    if not _table_exists(table):
        return set()
    return {ix['name'] for ix in _inspector().get_indexes(table) if ix.get('name')}


def _quote_table(table: str) -> str:
    return '"user"' if table == 'user' else table


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name in _column_names(table):
        return
    col_type = column.type.compile(dialect=op.get_bind().dialect)
    op.execute(
        sa.text(
            f'ALTER TABLE {_quote_table(table)} '
            f'ADD COLUMN IF NOT EXISTS {column.name} {col_type}'
        )
    )


def _ensure_index(table: str, name: str, columns: list, unique: bool = False) -> None:
    if name in _index_names(table):
        return
    unique_sql = 'UNIQUE ' if unique else ''
    cols_sql = ', '.join(columns)
    op.execute(
        sa.text(
            f'CREATE {unique_sql}INDEX IF NOT EXISTS {name} '
            f'ON {_quote_table(table)} ({cols_sql})'
        )
    )


def upgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Missing tables — create from current model metadata (checkfirst)
    # ------------------------------------------------------------------
    from app.models.billing import PricingPlan, Subscription  # noqa: WPS433
    from app.models.briefing import (  # noqa: WPS433
        BriefEmailOpen,
        BriefEmailSend,
        BriefLinkClick,
    )

    PricingPlan.__table__.create(bind=bind, checkfirst=True)
    Subscription.__table__.create(bind=bind, checkfirst=True)
    BriefEmailOpen.__table__.create(bind=bind, checkfirst=True)
    BriefEmailSend.__table__.create(bind=bind, checkfirst=True)
    BriefLinkClick.__table__.create(bind=bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 2. Missing columns on existing tables
    # ------------------------------------------------------------------
    columns_to_add = [
        # user / billing
        ('user', sa.Column('stripe_customer_id', sa.String(255), nullable=True)),

        # brief_item (daily brief)
        ('brief_item', sa.Column('so_what', sa.Text(), nullable=True)),
        ('brief_item', sa.Column('perspectives', sa.JSON(), nullable=True)),

        # brief_run analytics
        ('brief_run', sa.Column('emails_sent', sa.Integer(), nullable=True)),
        ('brief_run', sa.Column('unique_opens', sa.Integer(), nullable=True)),
        ('brief_run', sa.Column('total_clicks', sa.Integer(), nullable=True)),
        ('brief_run', sa.Column('slack_sent', sa.Boolean(), nullable=True)),

        # brief_run_item denormalized source
        ('brief_run_item', sa.Column('source_name', sa.String(200), nullable=True)),
        ('brief_run_item', sa.Column('source_url', sa.String(1000), nullable=True)),

        # brief_template marketplace
        ('brief_template', sa.Column('category', sa.String(50), nullable=True)),
        ('brief_template', sa.Column('audience_type', sa.String(30), nullable=True)),
        ('brief_template', sa.Column('icon', sa.String(50), nullable=True)),
        ('brief_template', sa.Column('tagline', sa.String(200), nullable=True)),
        ('brief_template', sa.Column('sample_output', sa.Text(), nullable=True)),
        ('brief_template', sa.Column('is_featured', sa.Boolean(), nullable=True)),
        ('brief_template', sa.Column('is_active', sa.Boolean(), nullable=True)),
        ('brief_template', sa.Column('sort_order', sa.Integer(), nullable=True)),
        ('brief_template', sa.Column('default_accent_color', sa.String(20), nullable=True)),
        ('brief_template', sa.Column('configurable_options', JSONB(), nullable=True)),
        ('brief_template', sa.Column('guardrails', JSONB(), nullable=True)),
        ('brief_template', sa.Column('custom_prompt_prefix', sa.Text(), nullable=True)),
        ('brief_template', sa.Column('focus_keywords', JSONB(), nullable=True)),
        ('brief_template', sa.Column('exclude_keywords', JSONB(), nullable=True)),
        ('brief_template', sa.Column('times_used', sa.Integer(), nullable=True)),

        # briefing branding / delivery
        ('briefing', sa.Column('tone', sa.String(50), nullable=True)),
        ('briefing', sa.Column('max_items', sa.Integer(), nullable=True)),
        ('briefing', sa.Column('include_summaries', sa.Boolean(), nullable=True)),
        ('briefing', sa.Column('custom_prompt', sa.Text(), nullable=True)),
        ('briefing', sa.Column('guardrails', JSONB(), nullable=True)),
        ('briefing', sa.Column('topic_preferences', JSONB(), nullable=True)),
        ('briefing', sa.Column('filters_json', JSONB(), nullable=True)),
        ('briefing', sa.Column('logo_url', sa.String(500), nullable=True)),
        ('briefing', sa.Column('header_text', sa.String(200), nullable=True)),
        ('briefing', sa.Column('accent_color', sa.String(20), nullable=True)),
        ('briefing', sa.Column('slack_webhook_url', sa.String(500), nullable=True)),
        ('briefing', sa.Column('slack_channel_name', sa.String(100), nullable=True)),

        # briefing_source
        ('briefing_source', sa.Column('priority', sa.Integer(), nullable=True)),

        # daily_brief_subscriber analytics
        ('daily_brief_subscriber', sa.Column('total_opens', sa.Integer(), nullable=True)),
        ('daily_brief_subscriber', sa.Column('total_clicks', sa.Integer(), nullable=True)),
        ('daily_brief_subscriber', sa.Column('last_opened_at', sa.DateTime(), nullable=True)),
        ('daily_brief_subscriber', sa.Column('last_clicked_at', sa.DateTime(), nullable=True)),

        # input_source provenance
        ('input_source', sa.Column('origin_type', sa.String(20), nullable=True)),
        ('input_source', sa.Column('content_domain', sa.String(50), nullable=True)),
        ('input_source', sa.Column('allowed_channels', JSONB(), nullable=True)),
        ('input_source', sa.Column('political_leaning', sa.Float(), nullable=True)),
        ('input_source', sa.Column('is_verified', sa.Boolean(), nullable=True)),

        # news_article scoring
        ('news_article', sa.Column('relevance_score', sa.Float(), nullable=True)),
    ]

    for table, column in columns_to_add:
        if not _table_exists(table):
            continue
        _add_column_if_missing(table, column)

    # ------------------------------------------------------------------
    # 3. Unique index on user.stripe_customer_id (model: unique=True)
    # ------------------------------------------------------------------
    if _table_exists('user') and 'stripe_customer_id' in _column_names('user'):
        _ensure_index(
            'user', 'idx_user_stripe_customer_id', ['stripe_customer_id'], unique=True
        )

    # Model-declared indexes that clear residual LOW drift for repaired cols.
    for table, name, cols, unique in (
        ('brief_template', 'idx_brief_template_category', ['category'], False),
        ('brief_template', 'idx_brief_template_audience', ['audience_type'], False),
        ('brief_template', 'idx_brief_template_featured', ['is_featured'], False),
        ('daily_brief_subscriber', 'idx_dbs_tier_status', ['tier', 'status'], False),
    ):
        if not _table_exists(table):
            continue
        existing_cols = _column_names(table)
        if not all(c in existing_cols for c in cols):
            continue
        _ensure_index(table, name, cols, unique=unique)


def downgrade():
    # Non-destructive repair — do not drop columns/tables that may hold
    # production data introduced outside this revision.
    pass
