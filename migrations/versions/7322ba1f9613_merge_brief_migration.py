"""merge brief migration

Revision ID: 7322ba1f9613
Revises: c06937a4cf5f, d8e9f0a1b2c3
Create Date: 2026-01-07 10:28:47.068406

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7322ba1f9613'
down_revision = ('c06937a4cf5f', 'd8e9f0a1b2c3')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
