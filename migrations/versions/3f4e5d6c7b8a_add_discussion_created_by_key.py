"""Add created_by_key_id to discussion for API key audit attribution

Revision ID: 3f4e5d6c7b8a
Revises: c4d5e6f7a8b9
Create Date: 2026-04-07

Allows the partner portal to answer "which API key created this discussion?"
without exposing the raw key value. Join to partner_api_key for key_prefix
and key_last4. Nullable for RSS-ingested rows and legacy discussions created
before this migration.

Deploy: Standard flask db upgrade. No data migration needed; existing rows
will have NULL (shown as "Unknown key" in the portal).
"""
from alembic import op
import sqlalchemy as sa


revision = '3f4e5d6c7b8a'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'discussion',
        sa.Column('created_by_key_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_discussion_created_by_key',
        'discussion', 'partner_api_key',
        ['created_by_key_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_discussion_created_by_key', 'discussion', type_='foreignkey')
    op.drop_column('discussion', 'created_by_key_id')
