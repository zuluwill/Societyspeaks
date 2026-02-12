"""add admin audit events table

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-02-12 21:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_audit_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('target_type', sa.String(length=50), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('request_ip', sa.String(length=64), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['admin_user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_admin_audit_event_created_at', 'admin_audit_event', ['created_at'], unique=False)
    op.create_index('ix_admin_audit_event_admin_user_id', 'admin_audit_event', ['admin_user_id'], unique=False)
    op.create_index('ix_admin_audit_event_action', 'admin_audit_event', ['action'], unique=False)


def downgrade():
    op.drop_index('ix_admin_audit_event_action', table_name='admin_audit_event')
    op.drop_index('ix_admin_audit_event_admin_user_id', table_name='admin_audit_event')
    op.drop_index('ix_admin_audit_event_created_at', table_name='admin_audit_event')
    op.drop_table('admin_audit_event')
