"""Add magic_login_valid_after to user.

Backs the magic-link login flow. Semantics: a magic-link token carries an
issued-at timestamp (``iat``) in its signed payload; on consume, the token
is valid iff ``token.iat >= user.magic_login_valid_after``. The column is
bumped to ``utcnow()`` on every new link send (invalidating any prior
pending tokens) and again on consume (invalidating the just-used token).
NULL means "no magic-link has ever been issued for this user" — any
fresh token will satisfy the iat comparison.

Revision ID: m7a8g9i0c1l2
Revises: b1u2e3s4k5y6
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa


revision = 'm7a8g9i0c1l2'
down_revision = 'b1u2e3s4k5y6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user') as batch_op:
        batch_op.add_column(sa.Column('magic_login_valid_after', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('magic_login_valid_after')
