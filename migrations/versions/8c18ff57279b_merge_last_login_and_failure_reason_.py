"""merge_last_login_and_failure_reason_heads

Revision ID: 8c18ff57279b
Revises: f9e8d7c6b5a4, fa1b2c3d4e5f
Create Date: 2026-03-24 16:07:49.943295

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c18ff57279b'
down_revision = ('f9e8d7c6b5a4', 'fa1b2c3d4e5f')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
