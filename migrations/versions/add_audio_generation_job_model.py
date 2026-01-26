"""Add audio generation job model for batch processing

Revision ID: audio_job_model
Revises: 46ebc21e5d8625dd
Create Date: 2026-01-26 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'audio_job_model'
down_revision = '46ebc21e5d8625dd'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if a table exists."""
    conn = op.get_bind()
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def upgrade():
    # Create audio_generation_job table
    if not table_exists('audio_generation_job'):
        op.create_table('audio_generation_job',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('brief_id', sa.Integer(), sa.ForeignKey('daily_brief.id', ondelete='CASCADE'), nullable=False),
            sa.Column('voice_id', sa.String(100), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='queued'),  # queued, processing, completed, failed
            sa.Column('progress', sa.Integer(), server_default='0'),  # 0-100 percentage
            sa.Column('total_items', sa.Integer(), nullable=False),
            sa.Column('completed_items', sa.Integer(), server_default='0'),
            sa.Column('failed_items', sa.Integer(), server_default='0'),  # Track failed items
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('audio_generation_job', schema=None) as batch_op:
            batch_op.create_index('idx_audio_job_brief', ['brief_id'])
            batch_op.create_index('idx_audio_job_status', ['status'])
    
    # Update BriefItem audio fields comment
    # (No schema change, just updating the comment to reflect XTTS instead of Eleven Labs)
    pass


def downgrade():
    if table_exists('audio_generation_job'):
        op.drop_table('audio_generation_job')
