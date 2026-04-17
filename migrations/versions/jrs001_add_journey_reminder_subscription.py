"""Add journey_reminder_subscription table

Merges heads z3a4b5c6d7e8 and u8v9w0x1y2z3, then creates the table.

Revision ID: jrs001
Revises: z3a4b5c6d7e8, u8v9w0x1y2z3
Create Date: 2026-04-17

"""
from alembic import op
import sqlalchemy as sa


revision = 'jrs001'
down_revision = ('z3a4b5c6d7e8', 'u8v9w0x1y2z3')
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'journey_reminder_subscription',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('programme_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(150), nullable=False),
        sa.Column('cadence', sa.String(20), nullable=False),
        sa.Column('next_send_at', sa.DateTime(), nullable=True),
        sa.Column('last_sent_at', sa.DateTime(), nullable=True),
        sa.Column('reminder_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('resume_token', sa.String(255), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('unsubscribed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['programme_id'], ['programme.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('programme_id', 'user_id', name='uq_jrs_programme_user'),
        sa.UniqueConstraint('resume_token'),
    )
    op.create_index('ix_jrs_programme_id', 'journey_reminder_subscription', ['programme_id'])
    op.create_index('ix_jrs_user_id', 'journey_reminder_subscription', ['user_id'])
    op.create_index('ix_jrs_next_send_at', 'journey_reminder_subscription', ['next_send_at'])


def downgrade():
    op.drop_index('ix_jrs_next_send_at', table_name='journey_reminder_subscription')
    op.drop_index('ix_jrs_user_id', table_name='journey_reminder_subscription')
    op.drop_index('ix_jrs_programme_id', table_name='journey_reminder_subscription')
    op.drop_table('journey_reminder_subscription')
