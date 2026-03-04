"""add pending_email to programme_steward

Allows inviting stewards who have not yet registered.
user_id becomes nullable; pending_email stores the invited address
until the user creates an account and the record is linked.

Revision ID: t9u0v1w2x3y4
Revises: s8t9u0v1w2x3
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa

revision = 't9u0v1w2x3y4'
down_revision = 's8t9u0v1w2x3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('programme_steward', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pending_email', sa.String(150), nullable=True))
        batch_op.alter_column('user_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table('programme_steward', schema=None) as batch_op:
        batch_op.alter_column('user_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('pending_email')
