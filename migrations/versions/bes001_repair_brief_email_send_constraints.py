"""Repair brief_email_send: dedupe, add missing PK and unique constraint

Revision ID: bes001
Revises: seg001
Create Date: 2026-07-12

The production table existed without its primary key or the
uq_brief_run_recipient_send unique constraint declared on the model, so
(1) every row had been physically duplicated (identical ids included), and
(2) the two-phase send's INSERT ... ON CONFLICT (brief_run_id, recipient_id)
failed outright — BriefRun sends burned all attempts and were marked failed
daily from 2026-07-09.

Dedupe uses ctid because duplicate rows share the same id. All DDL is
guarded so the migration is a no-op where the repair was already applied
directly.
"""
from alembic import op

revision = 'bes001'
down_revision = 'seg001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DELETE FROM brief_email_send a
        USING brief_email_send b
        WHERE a.brief_run_id = b.brief_run_id
          AND a.recipient_id = b.recipient_id
          AND a.ctid > b.ctid
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'brief_email_send'::regclass AND contype = 'p'
            ) THEN
                ALTER TABLE brief_email_send
                    ADD CONSTRAINT brief_email_send_pkey PRIMARY KEY (id);
            END IF;
        END $$
        """
    )
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_brief_run_recipient_send '
        'ON brief_email_send (brief_run_id, recipient_id)'
    )
    op.execute(
        "SELECT setval('brief_email_send_id_seq', "
        "(SELECT coalesce(max(id), 1) FROM brief_email_send))"
    )


def downgrade():
    # The PK is left in place: removing it would reintroduce the corruption
    # this migration exists to repair.
    op.execute('DROP INDEX IF EXISTS uq_brief_run_recipient_send')
