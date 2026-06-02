"""Partial index on completed game runs for participation counters

Revision ID: gmr004
Revises: gmr003
Create Date: 2026-06-02

Supports stats_service.participation_stats (total completed + completed-today),
which filter on status='completed' (and a started_at day range). A partial index
keyed on started_at is small and selective vs a low-cardinality status index.
"""
import sqlalchemy as sa
from alembic import op


revision = 'gmr004'
down_revision = 'gmr003'
branch_labels = None
depends_on = None


def upgrade():
    # Both dialect ``where`` clauses so the migration produces the same *partial*
    # index the model declares (game.py __table_args__) on Postgres and SQLite —
    # no model/migration drift, identical query plans across prod and local dev.
    op.create_index(
        'idx_game_run_completed_started',
        'game_run',
        ['started_at'],
        postgresql_where=sa.text("status = 'completed'"),
        sqlite_where=sa.text("status = 'completed'"),
    )


def downgrade():
    op.drop_index('idx_game_run_completed_started', table_name='game_run')
