"""add embed statement submission policy on discussion

Revision ID: n0p1q2r3s4t5
Revises: k6l7m8n9o0p1
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa


revision = 'n0p1q2r3s4t5'
down_revision = 'k6l7m8n9o0p1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'discussion',
        sa.Column(
            'embed_statement_submissions_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column('discussion', 'embed_statement_submissions_enabled', server_default=None)


def downgrade():
    op.drop_column('discussion', 'embed_statement_submissions_enabled')
