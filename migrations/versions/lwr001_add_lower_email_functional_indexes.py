"""Add lower(email) functional indexes for case-insensitive lookups

Without these, every login / magic-link request / partner session lookup
applies func.lower() to the email column, which prevents PostgreSQL from
using the existing B-tree index and forces a sequential scan of the whole
table.

Affected tables / queries
--------------------------
user              – auth login, magic-link request, programmes invite,
                    trial abuse detection
partner_member    – partner portal session lookup
partner           – partner portal session lookup (contact_email)

Note: CONCURRENTLY is intentionally omitted — it cannot run inside
Alembic's implicit transaction. The index builds hold a brief share lock
only; at user-table scale this is negligible.

Revision ID: lwr001
Revises: h5e6f7g8h9i0
Create Date: 2026-05-23
"""
from alembic import op


revision = 'lwr001'
down_revision = 'h5e6f7g8h9i0'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_user_email_lower '
        'ON "user" (lower(email))'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_partner_member_email_lower '
        'ON partner_member (lower(email))'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_partner_contact_email_lower '
        'ON partner (lower(contact_email))'
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS ix_user_email_lower')
    op.execute('DROP INDEX IF EXISTS ix_partner_member_email_lower')
    op.execute('DROP INDEX IF EXISTS ix_partner_contact_email_lower')
