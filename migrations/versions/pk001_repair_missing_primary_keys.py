"""Repair tables imported without primary keys: dedupe and add PK + uniques

Revision ID: pk001
Revises: bes001
Create Date: 2026-07-12

Eight tables (admin_audit_event, alembic_version, analytics_daily_aggregate,
analytics_event, audio_generation_job, brief_item, brief_recipient,
brief_run) existed in production without their primary keys — a data import
had run twice, physically duplicating every row (identical ids), which then
blocked the PK constraints from being created. Symptoms included ORM
StaleDataError ("expected to update 1 row(s); 2 were matched") and doubled
analytics counts. All duplicate groups were verified byte-identical before
dedupe, which uses ctid because duplicates share ids.

Everything is guarded so the migration no-ops where the repair was already
applied directly.
"""
from alembic import op

revision = 'pk001'
down_revision = 'bes001'
branch_labels = None
depends_on = None

ID_TABLES = (
    'admin_audit_event',
    'analytics_daily_aggregate',
    'analytics_event',
    'audio_generation_job',
    'brief_item',
    'brief_recipient',
    'brief_run',
)

UNIQUE_INDEXES = (
    ('uq_brief_run_briefing_scheduled', 'brief_run', '(briefing_id, scheduled_at)'),
    ('uq_briefing_recipient', 'brief_recipient', '(briefing_id, email)'),
    ('uq_brief_position', 'brief_item', '(brief_id, position)'),
    ('uq_analytics_daily_dims', 'analytics_daily_aggregate',
     '(event_date, event_name, programme_id, discussion_id, cohort_slug, country)'),
)


def _add_pk(table, constraint, columns):
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = '{table}'::regclass AND contype = 'p'
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {constraint} PRIMARY KEY {columns};
            END IF;
        END $$
        """
    )


def upgrade():
    for table in ID_TABLES:
        op.execute(
            f'DELETE FROM {table} a USING {table} b '
            f'WHERE a.id = b.id AND a.ctid > b.ctid'
        )
        _add_pk(table, f'{table}_pkey', '(id)')
        op.execute(
            f"SELECT setval('{table}_id_seq', (SELECT coalesce(max(id), 1) FROM {table}))"
        )
    _add_pk('alembic_version', 'alembic_version_pkc', '(version_num)')
    for name, table, columns in UNIQUE_INDEXES:
        op.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} {columns}')


def downgrade():
    # PKs stay: dropping them would reintroduce the corruption this repairs.
    pass
