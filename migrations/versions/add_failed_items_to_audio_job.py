"""Add failed_items column to audio_generation_job

Revision ID: add_failed_items
Revises: audio_job_model
Create Date: 2026-01-26 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'add_failed_items'
down_revision = 'audio_job_model'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(table_name):
    """Check if a table exists."""
    conn = op.get_bind()
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def upgrade():
    # Add failed_items column if table exists but column doesn't
    if table_exists('audio_generation_job'):
        if not column_exists('audio_generation_job', 'failed_items'):
            with op.batch_alter_table('audio_generation_job', schema=None) as batch_op:
                batch_op.add_column(sa.Column('failed_items', sa.Integer(), server_default='0'))


def downgrade():
    if table_exists('audio_generation_job'):
        if column_exists('audio_generation_job', 'failed_items'):
            with op.batch_alter_table('audio_generation_job', schema=None) as batch_op:
                batch_op.drop_column('failed_items')
