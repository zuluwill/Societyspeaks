"""Game tables: user/run FK cascades and daily in-progress uniqueness.

Revision ID: gmr006
Revises: ee2
Create Date: 2026-06-06

- game_run.user_id ON DELETE CASCADE — account deletion removes linked runs
- game_run_outcome.run_id ON DELETE CASCADE — outcomes follow their run
- Partial unique indexes — one in-progress daily per user or fingerprint

SQLite (local tests) relies on application-level deletion in delete_account();
these constraints apply on PostgreSQL production.
"""
import sqlalchemy as sa
from alembic import op

revision = 'gmr006'
down_revision = 'ee2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'sqlite':
        return

    op.drop_constraint('game_run_user_id_fkey', 'game_run', type_='foreignkey')
    op.create_foreign_key(
        'game_run_user_id_fkey',
        'game_run',
        'user',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )

    op.drop_constraint('game_run_outcome_run_id_fkey', 'game_run_outcome', type_='foreignkey')
    op.create_foreign_key(
        'game_run_outcome_run_id_fkey',
        'game_run_outcome',
        'game_run',
        ['run_id'],
        ['id'],
        ondelete='CASCADE',
    )

    op.create_index(
        'idx_game_run_daily_in_progress_user',
        'game_run',
        ['user_id', 'scenario_slug'],
        unique=True,
        postgresql_where=sa.text(
            "mode = 'daily' AND status = 'in_progress' AND user_id IS NOT NULL"
        ),
    )
    op.create_index(
        'idx_game_run_daily_in_progress_fp',
        'game_run',
        ['session_fingerprint', 'scenario_slug'],
        unique=True,
        postgresql_where=sa.text(
            "mode = 'daily' AND status = 'in_progress' "
            "AND user_id IS NULL AND session_fingerprint IS NOT NULL"
        ),
    )


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'sqlite':
        return

    op.drop_index('idx_game_run_daily_in_progress_fp', table_name='game_run')
    op.drop_index('idx_game_run_daily_in_progress_user', table_name='game_run')

    op.drop_constraint('game_run_outcome_run_id_fkey', 'game_run_outcome', type_='foreignkey')
    op.create_foreign_key(
        'game_run_outcome_run_id_fkey',
        'game_run_outcome',
        'game_run',
        ['run_id'],
        ['id'],
    )

    op.drop_constraint('game_run_user_id_fkey', 'game_run', type_='foreignkey')
    op.create_foreign_key(
        'game_run_user_id_fkey',
        'game_run',
        'user',
        ['user_id'],
        ['id'],
    )
