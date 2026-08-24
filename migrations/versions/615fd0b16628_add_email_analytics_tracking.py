"""Add email analytics tracking

Revision ID: 615fd0b16628
Revises: 7322ba1f9613
Create Date: 2026-01-07 15:00:03.722211

Made defensive for from-empty installs: `brief_item.perspectives` and some
vote uniqueness objects only existed in production (or later revisions) when
this was authored. Production already stamped this revision and will not
re-execute it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '615fd0b16628'
down_revision = '7322ba1f9613'
branch_labels = None
depends_on = None


def _columns(table_name):
    return {c['name'] for c in inspect(op.get_bind()).get_columns(table_name)}


def upgrade():
    if 'perspectives' in _columns('brief_item'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.alter_column(
                'perspectives',
                existing_type=postgresql.JSONB(astext_type=sa.Text()),
                type_=sa.JSON(),
                existing_nullable=True,
            )

    # magic_token uniqueness — create only if missing (index already exists as
    # idx_dbs_token in d8e9 on from-empty; production had a separate constraint).
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'daily_brief_subscriber'::regclass
                  AND contype = 'u'
                  AND conname LIKE '%magic_token%'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'daily_brief_subscriber'
                  AND indexdef ILIKE '%UNIQUE%'
                  AND indexdef ILIKE '%magic_token%'
            ) THEN
                ALTER TABLE daily_brief_subscriber
                    ADD CONSTRAINT daily_brief_subscriber_magic_token_key UNIQUE (magic_token);
            END IF;
        END $$;
    """)

    # Temporarily drop vote uniqueness (restored later by v1w2x3y4z5a6 as
    # partial indexes). IF EXISTS: from-empty may only have the constraint,
    # not the session partial index, or vice versa depending on branch order.
    op.execute("DROP INDEX IF EXISTS uq_statement_session_vote")
    op.execute(
        "ALTER TABLE statement_vote DROP CONSTRAINT IF EXISTS uq_statement_user_vote"
    )


def downgrade():
    with op.batch_alter_table('statement_vote', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_statement_user_vote', ['statement_id', 'user_id'])
        batch_op.create_index(
            'uq_statement_session_vote',
            ['statement_id', 'session_fingerprint'],
            unique=True,
            postgresql_where='(session_fingerprint IS NOT NULL)',
        )

    op.execute(
        "ALTER TABLE daily_brief_subscriber "
        "DROP CONSTRAINT IF EXISTS daily_brief_subscriber_magic_token_key"
    )

    if 'perspectives' in _columns('brief_item'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.alter_column(
                'perspectives',
                existing_type=sa.JSON(),
                type_=postgresql.JSONB(astext_type=sa.Text()),
                existing_nullable=True,
            )
