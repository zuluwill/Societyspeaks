"""email_event: add ON DELETE SET NULL to brief_id and daily_question_id FKs

These columns reference daily_brief and daily_question rows that can be
deleted after the email is sent (e.g. brief rotation / question expiry).
Without ON DELETE SET NULL, clicking a link in an old email after the
referenced row is deleted causes a ForeignKeyViolation on INSERT into
email_event. Setting ON DELETE SET NULL makes the database self-healing:
deleted parents simply null-out the reference rather than blocking.

Revision ID: ee1
Revises: lwr001
"""

from alembic import op

revision = 'ee1'
down_revision = 'lwr001'
branch_labels = None
depends_on = None


def upgrade():
    # Drop existing FK constraints and recreate with ON DELETE SET NULL.
    # Constraint names come from the initial migration that created the table
    # (a2b3c4d5e6f7_add_unified_email_analytics).

    with op.batch_alter_table('email_event') as batch_op:
        # brief_id → daily_brief.id
        batch_op.drop_constraint('email_event_brief_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'email_event_brief_id_fkey',
            'daily_brief',
            ['brief_id'],
            ['id'],
            ondelete='SET NULL',
        )

        # daily_question_id → daily_question.id
        batch_op.drop_constraint('email_event_daily_question_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'email_event_daily_question_id_fkey',
            'daily_question',
            ['daily_question_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('email_event') as batch_op:
        batch_op.drop_constraint('email_event_brief_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'email_event_brief_id_fkey',
            'daily_brief',
            ['brief_id'],
            ['id'],
        )

        batch_op.drop_constraint('email_event_daily_question_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'email_event_daily_question_id_fkey',
            'daily_question',
            ['daily_question_id'],
            ['id'],
        )
