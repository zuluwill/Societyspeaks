"""email_event: ON DELETE SET NULL for brief/question subscriber FKs

When a Daily Brief or Daily Question list subscriber is removed, linked
``email_event`` rows must keep their delivery/open/click history for reporting.
Application code nulls FKs before delete; this migration makes the database
self-healing if any path deletes a subscriber without the explicit unlink.

Revision ID: ee2
Revises: gmr005
"""

from alembic import op

revision = 'ee2'
down_revision = 'gmr005'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('email_event') as batch_op:
        batch_op.drop_constraint('email_event_brief_subscriber_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'email_event_brief_subscriber_id_fkey',
            'daily_brief_subscriber',
            ['brief_subscriber_id'],
            ['id'],
            ondelete='SET NULL',
        )

        batch_op.drop_constraint('email_event_question_subscriber_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'email_event_question_subscriber_id_fkey',
            'daily_question_subscriber',
            ['question_subscriber_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('email_event') as batch_op:
        batch_op.drop_constraint('email_event_brief_subscriber_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'email_event_brief_subscriber_id_fkey',
            'daily_brief_subscriber',
            ['brief_subscriber_id'],
            ['id'],
        )

        batch_op.drop_constraint('email_event_question_subscriber_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'email_event_question_subscriber_id_fkey',
            'daily_question_subscriber',
            ['question_subscriber_id'],
            ['id'],
        )
