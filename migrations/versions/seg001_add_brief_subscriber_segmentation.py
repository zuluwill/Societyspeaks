"""Add segment metadata columns to daily_brief_subscriber

Revision ID: seg001
Revises: sil001
Create Date: 2026-07-11

Nullable segment metadata (chapter / function / geography) on brief
subscribers so sends and analytics can be segmented; organic signups leave
them NULL. Also introduces the 'imported' status: present with metadata but
excluded from every send path (all of which gate on status == 'active') until
explicitly activated during a deliverability ramp.

DDL is IF NOT EXISTS so the migration is a no-op where the columns were
already applied directly (ops runs ahead of deploys for import tooling).
"""
from alembic import op

revision = 'seg001'
down_revision = 'sil001'
branch_labels = None
depends_on = None

COLUMNS = (
    ('source', 'VARCHAR(50)'),
    ('chapter', 'VARCHAR(120)'),
    ('function', 'VARCHAR(100)'),
    ('job_title', 'VARCHAR(255)'),
    ('company', 'VARCHAR(255)'),
    ('country', 'VARCHAR(100)'),
    ('city', 'VARCHAR(100)'),
    ('imported_at', 'TIMESTAMP'),
)


def upgrade():
    for name, ddl_type in COLUMNS:
        op.execute(f'ALTER TABLE daily_brief_subscriber ADD COLUMN IF NOT EXISTS "{name}" {ddl_type}')
    op.execute('CREATE INDEX IF NOT EXISTS idx_dbs_source_status ON daily_brief_subscriber (source, status)')


def downgrade():
    op.execute('DROP INDEX IF EXISTS idx_dbs_source_status')
    for name, _ in reversed(COLUMNS):
        op.execute(f'ALTER TABLE daily_brief_subscriber DROP COLUMN IF EXISTS "{name}"')
