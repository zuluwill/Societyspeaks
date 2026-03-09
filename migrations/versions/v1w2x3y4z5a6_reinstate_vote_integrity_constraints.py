"""Reinstate vote integrity constraints and add participant user uniqueness

Phase 0 integrity fixes for NSP 2M scale readiness:
- Deduplicates statement_vote rows (keeps latest by updated_at, then id)
- Restores partial unique indexes on statement_vote dropped in 615fd0b16628
- Deduplicates discussion_participant rows by user_id
- Adds missing UNIQUE(discussion_id, user_id) partial index on discussion_participant
- Reconciles denormalized statement vote counters after dedup

Revision ID: v1w2x3y4z5a6
Revises: u0v1w2x3y4z5
Create Date: 2026-03-09
"""

from alembic import op

revision = 'v1w2x3y4z5a6'
down_revision = 'u0v1w2x3y4z5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'

    # ------------------------------------------------------------------ #
    # 1. Deduplicate statement_vote by (statement_id, user_id)            #
    #    Keep the row with the latest updated_at; break ties by higher id #
    # ------------------------------------------------------------------ #
    op.execute("""
        DELETE FROM statement_vote
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY statement_id, user_id
                           ORDER BY COALESCE(updated_at, created_at) DESC NULLS LAST, id DESC
                       ) AS rn
                FROM statement_vote
                WHERE user_id IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
    """)

    # ------------------------------------------------------------------ #
    # 2. Deduplicate statement_vote by (statement_id, session_fingerprint) #
    #                                                                      #
    # The restored index covers ALL rows where session_fingerprint IS NOT  #
    # NULL, regardless of user_id.  Authenticated rows can legitimately    #
    # carry a fingerprint (embed flows), so we must deduplicate across the #
    # full population, not just anonymous (user_id IS NULL) rows.          #
    # ------------------------------------------------------------------ #
    op.execute("""
        DELETE FROM statement_vote
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY statement_id, session_fingerprint
                           ORDER BY COALESCE(updated_at, created_at) DESC NULLS LAST, id DESC
                       ) AS rn
                FROM statement_vote
                WHERE session_fingerprint IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
    """)

    # ------------------------------------------------------------------ #
    # 3. Reconcile denormalized statement counters after dedup            #
    # ------------------------------------------------------------------ #
    op.execute("""
        UPDATE statement s
        SET
            vote_count_agree    = (
                SELECT COUNT(*) FROM statement_vote
                WHERE statement_id = s.id AND vote = 1
            ),
            vote_count_disagree = (
                SELECT COUNT(*) FROM statement_vote
                WHERE statement_id = s.id AND vote = -1
            ),
            vote_count_unsure   = (
                SELECT COUNT(*) FROM statement_vote
                WHERE statement_id = s.id AND vote = 0
            )
    """)

    # ------------------------------------------------------------------ #
    # 4. Restore partial unique indexes on statement_vote                 #
    #    Use CONCURRENTLY on Postgres to avoid write blocking on hot tbls #
    # ------------------------------------------------------------------ #
    if is_postgres:
        with op.get_context().autocommit_block():
            op.execute("""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_statement_user_vote
                    ON statement_vote (statement_id, user_id)
                    WHERE user_id IS NOT NULL
            """)

        with op.get_context().autocommit_block():
            op.execute("""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_statement_session_vote
                    ON statement_vote (statement_id, session_fingerprint)
                    WHERE session_fingerprint IS NOT NULL
            """)
    else:
        op.execute("""
            CREATE UNIQUE INDEX uq_statement_user_vote
                ON statement_vote (statement_id, user_id)
                WHERE user_id IS NOT NULL
        """)

        op.execute("""
            CREATE UNIQUE INDEX uq_statement_session_vote
                ON statement_vote (statement_id, session_fingerprint)
                WHERE session_fingerprint IS NOT NULL
        """)

    # ------------------------------------------------------------------ #
    # 5. Deduplicate discussion_participant by (discussion_id, user_id)   #
    # ------------------------------------------------------------------ #
    op.execute("""
        DELETE FROM discussion_participant
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY discussion_id, user_id
                           ORDER BY last_activity DESC NULLS LAST, id DESC
                       ) AS rn
                FROM discussion_participant
                WHERE user_id IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
    """)

    # ------------------------------------------------------------------ #
    # 6. Add UNIQUE(discussion_id, user_id) partial index                 #
    # ------------------------------------------------------------------ #
    if is_postgres:
        with op.get_context().autocommit_block():
            op.execute("""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_discussion_participant_user
                    ON discussion_participant (discussion_id, user_id)
                    WHERE user_id IS NOT NULL
            """)
    else:
        op.execute("""
            CREATE UNIQUE INDEX uq_discussion_participant_user
                ON discussion_participant (discussion_id, user_id)
                WHERE user_id IS NOT NULL
        """)


def downgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    if is_postgres:
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_discussion_participant_user")
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_statement_session_vote")
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_statement_user_vote")
    else:
        op.execute("DROP INDEX IF EXISTS uq_discussion_participant_user")
        op.execute("DROP INDEX IF EXISTS uq_statement_session_vote")
        op.execute("DROP INDEX IF EXISTS uq_statement_user_vote")
    # Counter reconciliation and deduplication are not reversible.
    # Downgrade removes only the constraints; data changes are permanent.
