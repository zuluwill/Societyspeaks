"""Add flag system to daily responses

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-01-12 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'i3j4k5l6m7n8'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column already exists in the table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(table_name):
    """Check if a table already exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def constraint_exists(table_name, constraint_name):
    """Check if a foreign key constraint exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    fks = inspector.get_foreign_keys(table_name)
    return any(fk.get('name') == constraint_name for fk in fks)


def index_exists(table_name, index_name):
    """Check if an index exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = inspector.get_indexes(table_name)
    return any(idx.get('name') == index_name for idx in indexes)


def upgrade():
    # Add flag tracking fields to daily_question_response table (idempotent)
    if not column_exists('daily_question_response', 'is_hidden'):
        op.add_column('daily_question_response', sa.Column('is_hidden', sa.Boolean(), nullable=False, server_default='0'))
    if not column_exists('daily_question_response', 'flag_count'):
        op.add_column('daily_question_response', sa.Column('flag_count', sa.Integer(), nullable=False, server_default='0'))
    if not column_exists('daily_question_response', 'reviewed_by_admin'):
        op.add_column('daily_question_response', sa.Column('reviewed_by_admin', sa.Boolean(), nullable=False, server_default='0'))
    if not column_exists('daily_question_response', 'reviewed_at'):
        op.add_column('daily_question_response', sa.Column('reviewed_at', sa.DateTime(), nullable=True))
    if not column_exists('daily_question_response', 'reviewed_by_user_id'):
        op.add_column('daily_question_response', sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True))

    # Add foreign key for reviewed_by_user_id (idempotent)
    if not constraint_exists('daily_question_response', 'fk_dqr_reviewed_by_user'):
        op.create_foreign_key(
            'fk_dqr_reviewed_by_user',
            'daily_question_response', 'user',
            ['reviewed_by_user_id'], ['id']
        )

    # Create daily_question_response_flag table (idempotent)
    if not table_exists('daily_question_response_flag'):
        op.create_table(
            'daily_question_response_flag',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('response_id', sa.Integer(), nullable=False),
            sa.Column('flagged_by_user_id', sa.Integer(), nullable=True),
            sa.Column('flagged_by_fingerprint', sa.String(length=64), nullable=True),
            sa.Column('reason', sa.String(length=50), nullable=False),
            sa.Column('details', sa.String(length=500), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('reviewed_at', sa.DateTime(), nullable=True),
            sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
            sa.Column('review_notes', sa.String(length=500), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['response_id'], ['daily_question_response.id'], name='fk_dqrf_response'),
            sa.ForeignKeyConstraint(['flagged_by_user_id'], ['user.id'], name='fk_dqrf_flagged_by'),
            sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['user.id'], name='fk_dqrf_reviewed_by'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('response_id', 'flagged_by_fingerprint', name='uq_response_flag_fingerprint')
        )

    # Create indexes (idempotent)
    if table_exists('daily_question_response_flag'):
        if not index_exists('daily_question_response_flag', 'idx_dqrf_response'):
            op.create_index('idx_dqrf_response', 'daily_question_response_flag', ['response_id'])
        if not index_exists('daily_question_response_flag', 'idx_dqrf_status'):
            op.create_index('idx_dqrf_status', 'daily_question_response_flag', ['status'])
        if not index_exists('daily_question_response_flag', 'idx_dqrf_created'):
            op.create_index('idx_dqrf_created', 'daily_question_response_flag', ['created_at'])


def downgrade():
    # Drop indexes (idempotent)
    if table_exists('daily_question_response_flag'):
        if index_exists('daily_question_response_flag', 'idx_dqrf_created'):
            op.drop_index('idx_dqrf_created', table_name='daily_question_response_flag')
        if index_exists('daily_question_response_flag', 'idx_dqrf_status'):
            op.drop_index('idx_dqrf_status', table_name='daily_question_response_flag')
        if index_exists('daily_question_response_flag', 'idx_dqrf_response'):
            op.drop_index('idx_dqrf_response', table_name='daily_question_response_flag')

    # Drop daily_question_response_flag table (idempotent)
    if table_exists('daily_question_response_flag'):
        op.drop_table('daily_question_response_flag')

    # Drop foreign key and columns from daily_question_response (idempotent)
    if constraint_exists('daily_question_response', 'fk_dqr_reviewed_by_user'):
        op.drop_constraint('fk_dqr_reviewed_by_user', 'daily_question_response', type_='foreignkey')
    if column_exists('daily_question_response', 'reviewed_by_user_id'):
        op.drop_column('daily_question_response', 'reviewed_by_user_id')
    if column_exists('daily_question_response', 'reviewed_at'):
        op.drop_column('daily_question_response', 'reviewed_at')
    if column_exists('daily_question_response', 'reviewed_by_admin'):
        op.drop_column('daily_question_response', 'reviewed_by_admin')
    if column_exists('daily_question_response', 'flag_count'):
        op.drop_column('daily_question_response', 'flag_count')
    if column_exists('daily_question_response', 'is_hidden'):
        op.drop_column('daily_question_response', 'is_hidden')
