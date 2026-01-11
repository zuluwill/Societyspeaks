"""Add vote token improvements: email_question_id, unsubscribe tracking, anonymous responses

Revision ID: de16e9f9813c
Revises: e7f6296de849
Create Date: 2026-01-11 16:00:00.000000

This migration adds:
1. email_question_id to daily_question_response (for vote mismatch analytics)
2. unsubscribe_reason and unsubscribed_at to daily_question_subscriber
3. session_fingerprint and is_anonymous to response table (for anonymous responses)
4. Makes response.user_id nullable to support anonymous responses

All changes are backward compatible and non-breaking.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'de16e9f9813c'
down_revision = 'e7f6296de849'
branch_labels = None
depends_on = None


def upgrade():
    # Add email_question_id to daily_question_response for analytics
    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_question_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_dqr_email_question',
            'daily_question',
            ['email_question_id'],
            ['id']
        )
        # Add index for analytics queries (vote mismatch detection)
        batch_op.create_index('idx_dqr_email_question', ['email_question_id'])

    # Add unsubscribe tracking to daily_question_subscriber
    with op.batch_alter_table('daily_question_subscriber', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unsubscribe_reason', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('unsubscribed_at', sa.DateTime(), nullable=True))
        # Add index for unsubscribe analytics queries
        batch_op.create_index('idx_dqs_unsubscribe_reason', ['unsubscribe_reason'])

    # Add anonymous response support to response table
    with op.batch_alter_table('response', schema=None) as batch_op:
        # Make user_id nullable to support anonymous responses
        batch_op.alter_column('user_id',
                            existing_type=sa.INTEGER(),
                            nullable=True)
        # Add session fingerprint for anonymous tracking
        batch_op.add_column(sa.Column('session_fingerprint', sa.String(length=64), nullable=True))
        # Add is_anonymous flag
        batch_op.add_column(sa.Column('is_anonymous', sa.Boolean(), nullable=True, server_default='false'))
        # Add index for session fingerprint lookups
        batch_op.create_index('idx_response_session_fingerprint', ['session_fingerprint'])

    # Set default value for existing rows
    op.execute("UPDATE response SET is_anonymous = false WHERE is_anonymous IS NULL")


def downgrade():
    """
    Downgrade migration with safety checks.
    
    WARNING: This will DELETE anonymous responses (where user_id IS NULL and session_fingerprint IS NOT NULL)
    to allow making user_id non-nullable again. If you need to preserve this data, backup first.
    """
    from sqlalchemy import text
    
    # Check for anonymous responses before proceeding
    connection = op.get_bind()
    result = connection.execute(
        text("SELECT COUNT(*) FROM response WHERE user_id IS NULL AND session_fingerprint IS NOT NULL")
    )
    anonymous_count = result.scalar()
    
    if anonymous_count > 0:
        print(f"WARNING: Found {anonymous_count} anonymous responses that will be deleted during downgrade.")
        # Delete anonymous responses to allow making user_id non-nullable
        connection.execute(
            text("DELETE FROM response WHERE user_id IS NULL AND session_fingerprint IS NOT NULL")
        )
        print(f"Deleted {anonymous_count} anonymous responses.")
    
    # Remove anonymous response support from response table
    with op.batch_alter_table('response', schema=None) as batch_op:
        batch_op.drop_index('idx_response_session_fingerprint')
        batch_op.drop_column('is_anonymous')
        batch_op.drop_column('session_fingerprint')
        # Now safe to restore user_id to non-nullable
        batch_op.alter_column('user_id',
                            existing_type=sa.INTEGER(),
                            nullable=False)

    # Remove unsubscribe tracking from daily_question_subscriber
    with op.batch_alter_table('daily_question_subscriber', schema=None) as batch_op:
        batch_op.drop_index('idx_dqs_unsubscribe_reason')
        batch_op.drop_column('unsubscribed_at')
        batch_op.drop_column('unsubscribe_reason')

    # Remove email_question_id from daily_question_response
    with op.batch_alter_table('daily_question_response', schema=None) as batch_op:
        batch_op.drop_index('idx_dqr_email_question')
        batch_op.drop_constraint('fk_dqr_email_question', type_='foreignkey')
        batch_op.drop_column('email_question_id')
