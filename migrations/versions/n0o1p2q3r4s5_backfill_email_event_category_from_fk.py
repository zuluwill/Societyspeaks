"""Backfill email_event.email_category from subscriber FKs

Revision ID: n0o1p2q3r4s5
Revises: m7a8g9i0c1l2
Create Date: 2026-04-24

Rows stored as auth while brief_subscriber_id / question_subscriber_id were set
(due to old webhook classification) are corrected to daily_brief / daily_question.
Downgrade is an intentional no-op: a naive reverse would set 'auth' on every
daily_brief / daily_question row that carries an FK, including rows that were
already correctly categorised before this fix shipped.
"""
from alembic import op

revision = "n0o1p2q3r4s5"
down_revision = "m7a8g9i0c1l2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE email_event
        SET email_category = 'daily_brief'
        WHERE email_category = 'auth'
          AND brief_subscriber_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE email_event
        SET email_category = 'daily_question'
        WHERE email_category = 'auth'
          AND question_subscriber_id IS NOT NULL
          AND brief_subscriber_id IS NULL
        """
    )


def downgrade():
    # Irreversible: reversing would set `auth` on all daily_brief/daily_question rows
    # with these FKs, including rows that were correctly categorized before this fix.
    pass
