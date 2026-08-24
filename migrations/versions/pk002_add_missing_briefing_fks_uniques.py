"""Add FKs and unique constraints missing from production; rebuild aggregates

Revision ID: pk002
Revises: pk001
Create Date: 2026-07-12

Follow-up to pk001 from the full model-vs-production schema audit. Because
brief_run/brief_recipient had no primary keys, every foreign key referencing
them was also absent, as were the token unique constraints on
brief_recipient. Adds them (orphan/duplicate checks passed before the direct
repair), promotes the repair-created unique indexes to named table
constraints so the schema matches the models exactly, and rebuilds
analytics_daily_aggregate over full history — rows older than the rollup
job's 14-day window had event_count roughly doubled because they were
computed while analytics_event contained duplicated rows.

All DDL is guarded; the rebuild is deterministic — safe to rerun.
"""
from alembic import op

revision = 'pk002'
down_revision = 'pk001'
branch_labels = None
depends_on = None

FKS = (
    ('audio_generation_job', 'audio_generation_job_brief_run_id_fkey',
     'FOREIGN KEY (brief_run_id) REFERENCES brief_run(id) ON DELETE CASCADE'),
    ('brief_edit', 'brief_edit_brief_run_id_fkey',
     'FOREIGN KEY (brief_run_id) REFERENCES brief_run(id) ON DELETE CASCADE'),
    ('brief_email_open', 'brief_email_open_brief_run_id_fkey',
     'FOREIGN KEY (brief_run_id) REFERENCES brief_run(id) ON DELETE CASCADE'),
    ('brief_email_send', 'brief_email_send_brief_run_id_fkey',
     'FOREIGN KEY (brief_run_id) REFERENCES brief_run(id) ON DELETE CASCADE'),
    ('brief_email_send', 'brief_email_send_recipient_id_fkey',
     'FOREIGN KEY (recipient_id) REFERENCES brief_recipient(id) ON DELETE CASCADE'),
    ('brief_link_click', 'brief_link_click_brief_run_id_fkey',
     'FOREIGN KEY (brief_run_id) REFERENCES brief_run(id) ON DELETE CASCADE'),
    ('brief_run_item', 'brief_run_item_brief_run_id_fkey',
     'FOREIGN KEY (brief_run_id) REFERENCES brief_run(id) ON DELETE CASCADE'),
)

PROMOTIONS = (
    ('brief_email_send', 'uq_brief_run_recipient_send', '(brief_run_id, recipient_id)'),
    ('brief_item', 'uq_brief_position', '(brief_id, position)'),
    ('brief_recipient', 'uq_briefing_recipient', '(briefing_id, email)'),
    ('brief_run', 'uq_brief_run_briefing_scheduled', '(briefing_id, scheduled_at)'),
)

CANONICAL_EVENTS = (
    "'account_created','user_logged_in','discussion_viewed',"
    "'statement_voted','response_created','cohort_assigned','analysis_generated'"
)


def _guarded(table, name, ddl):
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('public.{table}') IS NULL THEN
                RETURN;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = '{table}'::regclass AND conname = '{name}'
            ) THEN
                {ddl};
            END IF;
        END $$
        """
    )


def upgrade():
    for table, name, clause in FKS:
        _guarded(table, name, f'ALTER TABLE {table} ADD CONSTRAINT {name} {clause}')

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.brief_recipient') IS NULL THEN
                RETURN;
            END IF;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_brief_recipient_magic_token
                ON brief_recipient (magic_token);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_brief_recipient_unsubscribe_token
                ON brief_recipient (unsubscribe_token);
        END $$;
        """
    )

    # Promote unique indexes created by bes001/pk001 into named table
    # constraints; create outright where neither exists (fresh databases).
    for table, name, columns in PROMOTIONS:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('public.{table}') IS NULL THEN
                    RETURN;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_constraint
                           WHERE conrelid = '{table}'::regclass AND conname = '{name}') THEN
                    NULL;  -- already a constraint
                ELSIF EXISTS (SELECT 1 FROM pg_indexes
                              WHERE tablename = '{table}' AND indexname = '{name}') THEN
                    ALTER TABLE {table} ADD CONSTRAINT {name}_c UNIQUE USING INDEX {name};
                    ALTER TABLE {table} RENAME CONSTRAINT {name}_c TO {name};
                ELSE
                    ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE {columns};
                END IF;
            END $$
            """
        )

    # Notification FKs existed without the CASCADE the models declare, so
    # deleting a user/discussion with notifications raised FK violations.
    for col, reftable in (('user_id', '"user"'), ('discussion_id', 'discussion')):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('public.notification') IS NULL THEN
                    RETURN;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_constraint
                           WHERE conname = 'notification_{col}_fkey'
                             AND confdeltype <> 'c') THEN
                    ALTER TABLE notification DROP CONSTRAINT notification_{col}_fkey;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint
                               WHERE conname = 'notification_{col}_fkey') THEN
                    ALTER TABLE notification ADD CONSTRAINT notification_{col}_fkey
                        FOREIGN KEY ({col}) REFERENCES {reftable}(id) ON DELETE CASCADE;
                END IF;
            END $$
            """
        )

    # Deterministic full-history aggregate rebuild (mirrors
    # rollup_analytics_daily, which only covers the last 14 days).
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.analytics_daily_aggregate') IS NULL
               OR to_regclass('public.analytics_event') IS NULL THEN
                RETURN;
            END IF;
            DELETE FROM analytics_daily_aggregate;
            INSERT INTO analytics_daily_aggregate
                (event_date, event_name, programme_id, discussion_id, cohort_slug,
                 country, event_count, unique_users, updated_at)
            SELECT date(created_at), event_name, programme_id, discussion_id,
                   cohort_slug, country, count(id), count(DISTINCT user_id), now()
            FROM analytics_event
            WHERE event_name IN (
                'account_created','user_logged_in','discussion_viewed',
                'statement_voted','response_created','cohort_assigned','analysis_generated'
            )
            GROUP BY 1, 2, 3, 4, 5, 6;
        END $$;
        """
    )


def downgrade():
    for table, name, _ in FKS:
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}')
    op.execute('DROP INDEX IF EXISTS uq_brief_recipient_magic_token')
    op.execute('DROP INDEX IF EXISTS uq_brief_recipient_unsubscribe_token')
