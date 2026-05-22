"""Ensure game_challenge table exists.

The batch_alter_table call in g4d5e6f7a8b9 inadvertently dropped the
game_challenge table on PostgreSQL via its table-recreation codepath.
This migration recreates it idempotently using CREATE TABLE IF NOT EXISTS.

Revision ID: h5e6f7g8h9i0
Revises: g4d5e6f7a8b9
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa


revision = 'h5e6f7g8h9i0'
down_revision = 'g4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS game_challenge (
            id          SERIAL PRIMARY KEY,
            token       VARCHAR(48)  NOT NULL,
            creator_run_id INTEGER   NOT NULL,
            scenario_slug VARCHAR(80) NOT NULL,
            mode        VARCHAR(20)  NOT NULL,
            schedule_date DATE,
            creator_display_name VARCHAR(48) NOT NULL DEFAULT 'Someone',
            creator_headline VARCHAR(300) NOT NULL,
            created_at  TIMESTAMP,
            CONSTRAINT game_challenge_token_key UNIQUE (token),
            CONSTRAINT game_challenge_creator_run_id_key UNIQUE (creator_run_id),
            CONSTRAINT game_challenge_creator_run_id_fkey
                FOREIGN KEY (creator_run_id) REFERENCES game_run(id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_game_challenge_token
            ON game_challenge (token)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_game_challenge_creator_run
            ON game_challenge (creator_run_id)
    """)


def downgrade():
    op.drop_index('idx_game_challenge_creator_run', table_name='game_challenge')
    op.drop_index('idx_game_challenge_token', table_name='game_challenge')
    op.drop_table('game_challenge')
