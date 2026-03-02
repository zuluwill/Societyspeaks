"""add information fields to discussion

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm3n4o5p6q7r8'
down_revision = 'l2m3n4o5p6q7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('discussion', sa.Column('information_title', sa.String(length=200), nullable=True))
    op.add_column('discussion', sa.Column('information_body', sa.Text(), nullable=True))
    op.add_column('discussion', sa.Column('information_links', sa.JSON(), nullable=False, server_default='[]'))


def downgrade():
    op.drop_column('discussion', 'information_links')
    op.drop_column('discussion', 'information_body')
    op.drop_column('discussion', 'information_title')
