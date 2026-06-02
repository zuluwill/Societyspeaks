"""Add posthog_distinct_id to game_run (stable per-run analytics identity)

Revision ID: gmr005
Revises: gmr004
Create Date: 2026-06-02

Stamped once at run creation so every server-side game event for a run shares a
single distinct_id that stitches to the JS SDK's person profile (the browser's
PostHog cookie id for anonymous players, str(user_id) for logged-in). Nullable:
legacy runs and events fired outside a request fall back to the fingerprint.
"""
from alembic import op
import sqlalchemy as sa

revision = 'gmr005'
down_revision = 'gmr004'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('game_run', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('posthog_distinct_id', sa.String(length=255), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('game_run', schema=None) as batch_op:
        batch_op.drop_column('posthog_distinct_id')
