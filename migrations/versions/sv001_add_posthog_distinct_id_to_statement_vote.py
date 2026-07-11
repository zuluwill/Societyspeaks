"""Add posthog_distinct_id to statement_vote (stable per-vote analytics identity)

Revision ID: sv001
Revises: gmr006
Create Date: 2026-07-11

Mirrors game_run.posthog_distinct_id (gmr005): stamped once at vote creation so
votes — the core participation act, mostly by intentionally-anonymous users —
can be joined to the JS SDK's person in PostHog (browser cookie id for
anonymous voters, str(user_id) for logged-in). Without it, votes and web
sessions are unjoinable identity islands. Nullable: legacy votes and votes
recorded outside a request context fall back to session_fingerprint.
"""
from alembic import op
import sqlalchemy as sa

revision = 'sv001'
down_revision = 'gmr006'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('statement_vote', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('posthog_distinct_id', sa.String(length=255), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('statement_vote', schema=None) as batch_op:
        batch_op.drop_column('posthog_distinct_id')
