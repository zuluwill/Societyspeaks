"""Add game_reminder_subscription table (daily play re-engagement nudge)

Revision ID: gmr001
Revises: jrs003
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = 'gmr001'
down_revision = 'jrs003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'game_reminder_subscription',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(length=150), nullable=False),
        sa.Column('session_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('timezone', sa.String(length=50), nullable=False, server_default='UTC'),
        sa.Column('preferred_hour', sa.Integer(), nullable=False, server_default='8'),
        sa.Column('next_send_at', sa.DateTime(), nullable=True),
        sa.Column('last_sent_at', sa.DateTime(), nullable=True),
        sa.Column('reminder_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('consecutive_misses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unsubscribe_token', sa.String(length=255), nullable=True),
        sa.Column('unsubscribed_at', sa.DateTime(), nullable=True),
        sa.Column('unsubscribe_reason', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_game_reminder_email'),
        sa.UniqueConstraint('unsubscribe_token'),
    )
    with op.batch_alter_table('game_reminder_subscription', schema=None) as batch_op:
        batch_op.create_index('idx_game_reminder_next_send', ['next_send_at'], unique=False)
        batch_op.create_index('idx_game_reminder_user', ['user_id'], unique=False)
        batch_op.create_index('idx_game_reminder_fingerprint', ['session_fingerprint'], unique=False)


def downgrade():
    with op.batch_alter_table('game_reminder_subscription', schema=None) as batch_op:
        batch_op.drop_index('idx_game_reminder_fingerprint')
        batch_op.drop_index('idx_game_reminder_user')
        batch_op.drop_index('idx_game_reminder_next_send')
    op.drop_table('game_reminder_subscription')
