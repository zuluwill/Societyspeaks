"""Add flag system to daily responses

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-01-12 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'i3j4k5l6m7n8'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def upgrade():
    # Add flag tracking fields to daily_question_response table
    op.add_column('daily_question_response', sa.Column('is_hidden', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('daily_question_response', sa.Column('flag_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('daily_question_response', sa.Column('reviewed_by_admin', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('daily_question_response', sa.Column('reviewed_at', sa.DateTime(), nullable=True))
    op.add_column('daily_question_response', sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True))

    # Add foreign key for reviewed_by_user_id
    op.create_foreign_key(
        'fk_dqr_reviewed_by_user',
        'daily_question_response', 'user',
        ['reviewed_by_user_id'], ['id']
    )

    # Create daily_question_response_flag table
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

    # Create indexes
    op.create_index('idx_dqrf_response', 'daily_question_response_flag', ['response_id'])
    op.create_index('idx_dqrf_status', 'daily_question_response_flag', ['status'])
    op.create_index('idx_dqrf_created', 'daily_question_response_flag', ['created_at'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_dqrf_created', table_name='daily_question_response_flag')
    op.drop_index('idx_dqrf_status', table_name='daily_question_response_flag')
    op.drop_index('idx_dqrf_response', table_name='daily_question_response_flag')

    # Drop daily_question_response_flag table
    op.drop_table('daily_question_response_flag')

    # Drop foreign key and columns from daily_question_response
    op.drop_constraint('fk_dqr_reviewed_by_user', 'daily_question_response', type_='foreignkey')
    op.drop_column('daily_question_response', 'reviewed_by_user_id')
    op.drop_column('daily_question_response', 'reviewed_at')
    op.drop_column('daily_question_response', 'reviewed_by_admin')
    op.drop_column('daily_question_response', 'flag_count')
    op.drop_column('daily_question_response', 'is_hidden')
