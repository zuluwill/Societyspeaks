"""add consensus job queue table

Revision ID: q9r8s7t6u5v4
Revises: 3cbe2f0a6b2c
Create Date: 2026-03-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'q9r8s7t6u5v4'
down_revision = '3cbe2f0a6b2c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'consensus_job',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('discussion_id', sa.Integer(), nullable=False),
        sa.Column('requested_by_user_id', sa.Integer(), nullable=True),
        sa.Column('analysis_id', sa.Integer(), nullable=True),
        sa.Column('dedupe_key', sa.String(length=255), nullable=False),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('queued_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['consensus_analysis.id']),
        sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id']),
        sa.ForeignKeyConstraint(['requested_by_user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_consensus_job_status_queued_at', 'consensus_job', ['status', 'queued_at'], unique=False)
    op.create_index('idx_consensus_job_discussion', 'consensus_job', ['discussion_id', 'created_at'], unique=False)
    op.create_index('idx_consensus_job_dedupe', 'consensus_job', ['dedupe_key'], unique=False)


def downgrade():
    op.drop_index('idx_consensus_job_dedupe', table_name='consensus_job')
    op.drop_index('idx_consensus_job_discussion', table_name='consensus_job')
    op.drop_index('idx_consensus_job_status_queued_at', table_name='consensus_job')
    op.drop_table('consensus_job')
