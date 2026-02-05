"""Add anonymous flagging support to StatementFlag

Adds:
- Makes flagger_user_id nullable for anonymous flags
- Adds session_fingerprint for tracking anonymous flaggers
- Adds index on session_fingerprint

Revision ID: w8x9y0z1a2b3
Revises: v7w8x9y0z1a2
Create Date: 2026-02-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'w8x9y0z1a2b3'
down_revision = 'v7w8x9y0z1a2'
branch_labels = None
depends_on = None


def upgrade():
    # Make flagger_user_id nullable for anonymous flagging
    with op.batch_alter_table('statement_flag', schema=None) as batch_op:
        batch_op.alter_column('flagger_user_id',
                              existing_type=sa.INTEGER(),
                              nullable=True)
        batch_op.add_column(sa.Column('session_fingerprint', sa.String(64), nullable=True))
        batch_op.create_index('idx_flag_fingerprint', ['session_fingerprint'])


def downgrade():
    with op.batch_alter_table('statement_flag', schema=None) as batch_op:
        batch_op.drop_index('idx_flag_fingerprint')
        batch_op.drop_column('session_fingerprint')
        # Note: Making flagger_user_id NOT NULL again would fail if there are anonymous flags
        # You may need to delete anonymous flags first or keep the column nullable
        batch_op.alter_column('flagger_user_id',
                              existing_type=sa.INTEGER(),
                              nullable=False)
