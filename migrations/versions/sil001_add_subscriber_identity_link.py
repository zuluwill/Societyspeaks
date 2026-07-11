"""Add subscriber_identity_link (email subscriber <-> anonymous visitor bridge)

Revision ID: sil001
Revises: sv001
Create Date: 2026-07-11

The product is intentionally anonymous-first: participants vote without
accounts. This table joins the two otherwise-disconnected identity spaces —
email subscribers and session fingerprints / PostHog distinct_ids — populated
when a visitor who arrived via a signed email link participates. Measurement
infrastructure only; safe to truncate (loses joins, never product data).
"""
from alembic import op
import sqlalchemy as sa

revision = 'sil001'
down_revision = 'sv001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'subscriber_identity_link',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'brief_subscriber_id',
            sa.Integer(),
            sa.ForeignKey('daily_brief_subscriber.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column(
            'question_subscriber_id',
            sa.Integer(),
            sa.ForeignKey('daily_question_subscriber.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('user.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('session_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('posthog_distinct_id', sa.String(length=255), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
    )
    op.create_index('idx_sil_brief_subscriber', 'subscriber_identity_link', ['brief_subscriber_id'])
    op.create_index('idx_sil_question_subscriber', 'subscriber_identity_link', ['question_subscriber_id'])
    op.create_index('idx_sil_fingerprint', 'subscriber_identity_link', ['session_fingerprint'])
    op.create_index('idx_sil_posthog', 'subscriber_identity_link', ['posthog_distinct_id'])


def downgrade():
    op.drop_index('idx_sil_posthog', table_name='subscriber_identity_link')
    op.drop_index('idx_sil_fingerprint', table_name='subscriber_identity_link')
    op.drop_index('idx_sil_question_subscriber', table_name='subscriber_identity_link')
    op.drop_index('idx_sil_brief_subscriber', table_name='subscriber_identity_link')
    op.drop_table('subscriber_identity_link')
