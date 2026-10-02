"""Add self-serve consultations

Adds:
- discussion.link_only: a discussion reachable only through its participant link
- consultation, consultation_report, consultation_purchase, consultation_plan
- background_job: queue for drafting, screening, report and notification work
- llm_usage: tokens per platform LLM call, for measuring the cost of a consultation

Revision ID: c1n2s3l4t5a6
Revises: c8d9e0f1a2b3
Create Date: 2026-10-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1n2s3l4t5a6'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'discussion',
        sa.Column('link_only', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        'consultation',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('discussion_id', sa.Integer(), sa.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('question', sa.String(300), nullable=False),
        sa.Column('context', sa.Text(), nullable=True),
        sa.Column('organisation_name', sa.String(200), nullable=False),
        sa.Column('audience_label', sa.String(200), nullable=True),
        sa.Column('audience_size', sa.Integer(), nullable=True),
        sa.Column('access_token', sa.String(64), nullable=False),
        sa.Column('allow_audience_statements', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('show_results_to_participants', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('closes_at', sa.DateTime(), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('first_response_notified_at', sa.DateTime(), nullable=True),
        sa.Column('low_turnout_notified_at', sa.DateTime(), nullable=True),
        sa.Column('moderation_notified_at', sa.DateTime(), nullable=True),
        sa.Column('covered_by', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('discussion_id', name='uq_consultation_discussion'),
        sa.UniqueConstraint('access_token', name='uq_consultation_access_token'),
    )
    op.create_index('idx_consultation_owner_created', 'consultation', ['owner_user_id', 'created_at'])
    op.create_index('idx_consultation_status_closes', 'consultation', ['status', 'closes_at'])

    op.create_table(
        'consultation_report',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('consultation_id', sa.Integer(), sa.ForeignKey('consultation.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False, server_default='final'),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('data_hash', sa.String(64), nullable=False),
        sa.Column('narrative', sa.JSON(), nullable=False),
        sa.Column('narrative_source', sa.String(20), nullable=False, server_default='template'),
        sa.Column('pdf_storage_key', sa.String(500), nullable=True),
        sa.Column('share_token', sa.String(64), nullable=True),
        sa.Column('shared_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('share_token', name='uq_consultation_report_share_token'),
    )
    op.create_index('idx_consultation_report_consultation', 'consultation_report', ['consultation_id', 'created_at'])

    op.create_table(
        'consultation_purchase',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('stripe_checkout_session_id', sa.String(255), nullable=False),
        sa.Column('stripe_payment_intent_id', sa.String(255), nullable=True),
        sa.Column('stripe_charge_id', sa.String(255), nullable=True),
        sa.Column('amount_pence', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='gbp'),
        sa.Column('status', sa.String(20), nullable=False, server_default='paid'),
        sa.Column('consumed_at', sa.DateTime(), nullable=True),
        sa.Column('consultation_id', sa.Integer(), sa.ForeignKey('consultation.id', ondelete='SET NULL'), nullable=True),
        sa.Column('refunded_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('stripe_checkout_session_id', name='uq_consultation_purchase_checkout_session'),
        sa.UniqueConstraint('consultation_id', name='uq_consultation_purchase_consultation'),
    )
    op.create_index('idx_consultation_purchase_user_status', 'consultation_purchase', ['user_id', 'status'])
    op.create_index('ix_consultation_purchase_stripe_payment_intent_id', 'consultation_purchase', ['stripe_payment_intent_id'])
    op.create_index('ix_consultation_purchase_stripe_charge_id', 'consultation_purchase', ['stripe_charge_id'])

    op.create_table(
        'consultation_plan',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stripe_subscription_id', sa.String(255), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='inactive'),
        sa.Column('current_period_end', sa.DateTime(), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', name='uq_consultation_plan_user'),
        sa.UniqueConstraint('stripe_subscription_id', name='uq_consultation_plan_stripe_subscription'),
    )

    op.create_table(
        'background_job',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(50), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('consultation_id', sa.Integer(), sa.ForeignKey('consultation.id', ondelete='CASCADE'), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('dedupe_key', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('run_after', sa.DateTime(), nullable=False),
        sa.Column('queued_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('idx_background_job_claim', 'background_job', ['status', 'run_after', 'queued_at'])
    op.create_index('idx_background_job_dedupe', 'background_job', ['dedupe_key'])
    op.create_index('idx_background_job_consultation', 'background_job', ['consultation_id', 'kind', 'created_at'])
    op.create_index('idx_background_job_user_kind', 'background_job', ['user_id', 'kind', 'created_at'])
    op.create_index(
        'uq_background_job_active_dedupe', 'background_job', ['dedupe_key'], unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        'llm_usage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('purpose', sa.String(50), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('succeeded', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('consultation_id', sa.Integer(), sa.ForeignKey('consultation.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('idx_llm_usage_consultation', 'llm_usage', ['consultation_id', 'created_at'])
    op.create_index('idx_llm_usage_purpose_created', 'llm_usage', ['purpose', 'created_at'])


def downgrade():
    op.drop_table('llm_usage')
    op.drop_table('background_job')
    op.drop_table('consultation_plan')
    op.drop_table('consultation_purchase')
    op.drop_table('consultation_report')
    op.drop_table('consultation')
    op.drop_column('discussion', 'link_only')
