"""Add email_vote_funnel_event for server-side device funnel analytics

Revision ID: dq004
Revises: dq003
Create Date: 2026-07-24

Persists confirm_view and vote_confirmed steps with coarse device_class from
the browser User-Agent. Ground-truth complement to PostHog for E1 stance loop.
"""
from alembic import op
import sqlalchemy as sa


revision = 'dq004'
down_revision = 'dq003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'email_vote_funnel_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('step', sa.String(length=20), nullable=False),
        sa.Column('device_class', sa.String(length=20), nullable=False),
        sa.Column('daily_question_id', sa.Integer(), nullable=False),
        sa.Column('brief_subscriber_id', sa.Integer(), nullable=True),
        sa.Column('question_subscriber_id', sa.Integer(), nullable=True),
        sa.Column('response_id', sa.Integer(), nullable=True),
        sa.Column('vote_choice', sa.String(length=20), nullable=True),
        sa.Column('voter_channel', sa.String(length=20), nullable=False),
        sa.Column('participation_source', sa.String(length=40), nullable=False),
        sa.Column('posthog_distinct_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['brief_subscriber_id'], ['daily_brief_subscriber.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['daily_question_id'], ['daily_question.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_subscriber_id'], ['daily_question_subscriber.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['response_id'], ['daily_question_response.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_evfe_question_step_created',
        'email_vote_funnel_event',
        ['daily_question_id', 'step', 'created_at'],
    )
    op.create_index(
        'idx_evfe_brief_subscriber',
        'email_vote_funnel_event',
        ['brief_subscriber_id', 'created_at'],
    )
    op.create_index(
        'idx_evfe_question_subscriber',
        'email_vote_funnel_event',
        ['question_subscriber_id', 'created_at'],
    )
    op.create_index('idx_evfe_response', 'email_vote_funnel_event', ['response_id'])


def downgrade():
    op.drop_index('idx_evfe_response', table_name='email_vote_funnel_event')
    op.drop_index('idx_evfe_question_subscriber', table_name='email_vote_funnel_event')
    op.drop_index('idx_evfe_brief_subscriber', table_name='email_vote_funnel_event')
    op.drop_index('idx_evfe_question_step_created', table_name='email_vote_funnel_event')
    op.drop_table('email_vote_funnel_event')
