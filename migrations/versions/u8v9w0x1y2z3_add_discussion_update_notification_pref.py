"""add discussion_update_notifications to user

Revision ID: u8v9w0x1y2z3
Revises: p2q3r4s5t6u7
Create Date: 2026-04-15

Separate email preference for organiser / steward \"what happened next\" updates
vs. general discussion activity (new_response).
"""

from alembic import op
import sqlalchemy as sa


revision = 'u8v9w0x1y2z3'
down_revision = 'p2q3r4s5t6u7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'discussion_update_notifications',
                sa.Boolean(),
                nullable=True,
                server_default=sa.true(),
            )
        )


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('discussion_update_notifications')
