"""Fix programme_access_grant.programme_id FK to add ON DELETE CASCADE

Revision ID: s8t9u0v1w2x3
Revises: r7s8t9u0v1w2
Create Date: 2026-03-03
"""

from alembic import op


revision = 's8t9u0v1w2x3'
down_revision = 'r7s8t9u0v1w2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'sqlite':
        # SQLite FK alteration is not reliably portable across existing unnamed constraints.
        # Keep SQLite as a no-op: new installs already get CASCADE from model metadata.
        return

    # PostgreSQL
    op.drop_constraint(
        'programme_access_grant_programme_id_fkey',
        'programme_access_grant',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'programme_access_grant_programme_id_fkey',
        'programme_access_grant',
        'programme',
        ['programme_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'sqlite':
        # See upgrade() note: keep SQLite no-op for safe portability.
        return

    # PostgreSQL
    op.drop_constraint(
        'programme_access_grant_programme_id_fkey',
        'programme_access_grant',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'programme_access_grant_programme_id_fkey',
        'programme_access_grant',
        'programme',
        ['programme_id'],
        ['id'],
    )
