"""add statement read-path sort indexes

Revision ID: u1v2w3x4y5z6
Revises: p6q7r8s9t0u1
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'u1v2w3x4y5z6'
down_revision = 't0u1v2w3x4y5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    # Emit COMMIT to exit Alembic's implicit transaction on Postgres.
    # On SQLite (tests), postgresql_concurrently is silently ignored and
    # the COMMIT guard is skipped, so tests run without change.
    if bind.dialect.name == 'postgresql':
        bind.execute(sa.text('COMMIT'))

    op.create_index(
        'idx_statement_discussion_visibility_recent',
        'statement',
        ['discussion_id', 'is_deleted', 'mod_status', 'created_at', 'id'],
        unique=False,
        postgresql_concurrently=True
    )
    op.create_index(
        'idx_statement_discussion_visibility_agree',
        'statement',
        ['discussion_id', 'is_deleted', 'mod_status', 'vote_count_agree', 'id'],
        unique=False,
        postgresql_concurrently=True
    )


def downgrade():
    op.drop_index('idx_statement_discussion_visibility_agree', table_name='statement')
    op.drop_index('idx_statement_discussion_visibility_recent', table_name='statement')
