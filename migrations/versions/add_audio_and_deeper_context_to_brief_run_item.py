"""Add audio and deeper context to BriefRunItem

Revision ID: brief_run_item_audio
Revises: audio_job_model
Create Date: 2026-01-26 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'brief_run_item_audio'
down_revision = 'audio_job_model'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    # Add deeper_context field to brief_run_item
    if not column_exists('brief_run_item', 'deeper_context'):
        with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('deeper_context', sa.Text(), nullable=True))
    
    # Add audio fields to brief_run_item
    if not column_exists('brief_run_item', 'audio_url'):
        with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('audio_url', sa.String(length=500), nullable=True))
    
    if not column_exists('brief_run_item', 'audio_voice_id'):
        with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('audio_voice_id', sa.String(length=100), nullable=True))
    
    if not column_exists('brief_run_item', 'audio_generated_at'):
        with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('audio_generated_at', sa.DateTime(), nullable=True))
    
    # Add brief_run_id to audio_generation_job (make it support both types)
    if not column_exists('audio_generation_job', 'brief_run_id'):
        with op.batch_alter_table('audio_generation_job', schema=None) as batch_op:
            batch_op.add_column(sa.Column('brief_run_id', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('brief_type', sa.String(length=20), server_default='daily_brief', nullable=False))
            # Make brief_id nullable (since we now support BriefRun too)
            batch_op.alter_column('brief_id', nullable=True)


def downgrade():
    # Remove audio fields from brief_run_item
    if column_exists('brief_run_item', 'audio_generated_at'):
        with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
            batch_op.drop_column('audio_generated_at')
    
    if column_exists('brief_run_item', 'audio_voice_id'):
        with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
            batch_op.drop_column('audio_voice_id')
    
    if column_exists('brief_run_item', 'audio_url'):
        with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
            batch_op.drop_column('audio_url')
    
    # Remove deeper_context field
    if column_exists('brief_run_item', 'deeper_context'):
        with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
            batch_op.drop_column('deeper_context')
    
    # Revert audio_generation_job changes
    if column_exists('audio_generation_job', 'brief_type'):
        with op.batch_alter_table('audio_generation_job', schema=None) as batch_op:
            batch_op.drop_column('brief_type')
            batch_op.drop_column('brief_run_id')
            batch_op.alter_column('brief_id', nullable=False)
