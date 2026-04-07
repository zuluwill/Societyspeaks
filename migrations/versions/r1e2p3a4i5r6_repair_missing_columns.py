"""Repair missing columns: seed_stance, embed_disabled, created_by_key_id

Revision ID: r1e2p3a4i5r6
Revises: 3f4e5d6c7b8a
Create Date: 2026-04-07

WHY THIS EXISTS
---------------
Three migrations were added to a branch of the migration graph that the
production database had already passed through.  Alembic only tracks revision
IDs in alembic_version; it does not detect that new migrations were inserted
*before* the recorded head.  When the build ran `flask db upgrade`, Alembic
saw the DB was already at (or past) the point where these branches diverge and
skipped them entirely.

As a result, the following columns are absent from the production schema even
though the code expects them:

  statement.seed_stance        (added by 2a3b4c5d6e7f)
  partner.embed_disabled       (added by w9x0y1z2a3b4)
  discussion.created_by_key_id (added by 3f4e5d6c7b8a)

This migration uses PostgreSQL's IF NOT EXISTS / DO $$ … $$ idiom so it is
fully idempotent — running it on a database that already has some or all of
the columns is a no-op.  The FK constraint is guarded by a check against
information_schema.table_constraints for the same reason.

After this migration the schema is definitively correct regardless of which
path the production DB took to get here.
"""
from alembic import op


revision = 'r1e2p3a4i5r6'
down_revision = '3f4e5d6c7b8a'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$
        BEGIN
            -- statement.seed_stance (2a3b4c5d6e7f)
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'statement' AND column_name = 'seed_stance'
            ) THEN
                ALTER TABLE statement ADD COLUMN seed_stance VARCHAR(20);
            END IF;

            -- partner.embed_disabled (w9x0y1z2a3b4)
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'partner' AND column_name = 'embed_disabled'
            ) THEN
                ALTER TABLE partner ADD COLUMN embed_disabled BOOLEAN NOT NULL DEFAULT FALSE;
                ALTER TABLE partner ALTER COLUMN embed_disabled DROP DEFAULT;
            END IF;

            -- discussion.created_by_key_id column (3f4e5d6c7b8a)
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'discussion' AND column_name = 'created_by_key_id'
            ) THEN
                ALTER TABLE discussion ADD COLUMN created_by_key_id INTEGER;
            END IF;

            -- discussion.created_by_key_id FK (3f4e5d6c7b8a)
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_discussion_created_by_key'
                  AND table_name = 'discussion'
            ) THEN
                ALTER TABLE discussion
                    ADD CONSTRAINT fk_discussion_created_by_key
                    FOREIGN KEY (created_by_key_id)
                    REFERENCES partner_api_key(id)
                    ON DELETE SET NULL;
            END IF;
        END
        $$;
    """)


def downgrade():
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_discussion_created_by_key'
                  AND table_name = 'discussion'
            ) THEN
                ALTER TABLE discussion DROP CONSTRAINT fk_discussion_created_by_key;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'discussion' AND column_name = 'created_by_key_id'
            ) THEN
                ALTER TABLE discussion DROP COLUMN created_by_key_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'partner' AND column_name = 'embed_disabled'
            ) THEN
                ALTER TABLE partner DROP COLUMN embed_disabled;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'statement' AND column_name = 'seed_stance'
            ) THEN
                ALTER TABLE statement DROP COLUMN seed_stance;
            END IF;
        END
        $$;
    """)
