"""add programme export job queue table

Revision ID: r1s2t3u4v5w6
Revises: a3b4c5d6e7f8
Create Date: 2026-03-09 12:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'r1s2t3u4v5w6'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'programme_export_job',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('programme_id', sa.Integer(), nullable=False),
        sa.Column('requested_by_user_id', sa.Integer(), nullable=False),
        sa.Column('export_format', sa.String(length=10), nullable=False),
        sa.Column('cohort_slug', sa.String(length=80), nullable=True),
        sa.Column('dedupe_key', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('storage_key', sa.String(length=500), nullable=True),
        sa.Column('artifact_filename', sa.String(length=255), nullable=True),
        sa.Column('content_type', sa.String(length=100), nullable=True),
        sa.Column('artifact_size_bytes', sa.Integer(), nullable=True),
        sa.Column('queued_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['programme_id'], ['programme.id']),
        sa.ForeignKeyConstraint(['requested_by_user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_export_job_status_queued_at', 'programme_export_job', ['status', 'queued_at'], unique=False)
    op.create_index('idx_export_job_programme_created', 'programme_export_job', ['programme_id', 'created_at'], unique=False)
    op.create_index('idx_export_job_requested_by', 'programme_export_job', ['requested_by_user_id', 'created_at'], unique=False)
    op.create_index('idx_export_job_dedupe', 'programme_export_job', ['dedupe_key'], unique=False)


def downgrade():
    op.drop_index('idx_export_job_dedupe', table_name='programme_export_job')
    op.drop_index('idx_export_job_requested_by', table_name='programme_export_job')
    op.drop_index('idx_export_job_programme_created', table_name='programme_export_job')
    op.drop_index('idx_export_job_status_queued_at', table_name='programme_export_job')
    op.drop_table('programme_export_job')
