"""Add Society Play game tables.

Revision ID: g1a2m3e4p5l6
Revises: z9y8x7w6v5u4
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = 'g1a2m3e4p5l6'
down_revision = 'z9y8x7w6v5u4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'game_run',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('scenario_slug', sa.String(length=80), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('session_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('society_name', sa.String(length=80), nullable=True),
        sa.Column('emblem_seed', sa.String(length=36), nullable=True),
        sa.Column('state_json', sa.JSON(), nullable=False),
        sa.Column('choice_log_json', sa.JSON(), nullable=False),
        sa.Column('delayed_queue_json', sa.JSON(), nullable=False),
        sa.Column('headline_log_json', sa.JSON(), nullable=False),
        sa.Column('turn_index', sa.Integer(), nullable=False),
        sa.Column('total_turns', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('last_active_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid'),
    )
    op.create_index('idx_game_run_fingerprint_status', 'game_run', ['session_fingerprint', 'status'])
    op.create_index('idx_game_run_user_status', 'game_run', ['user_id', 'status'])
    op.create_index('idx_game_run_uuid', 'game_run', ['uuid'], unique=True)

    op.create_table(
        'game_run_outcome',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('headline', sa.String(length=300), nullable=False),
        sa.Column('governance_label', sa.String(length=120), nullable=True),
        sa.Column('outcome_category', sa.String(length=40), nullable=True),
        sa.Column('axis_trust_autonomy', sa.Float(), nullable=True),
        sa.Column('axis_prosperity_fairness', sa.Float(), nullable=True),
        sa.Column('stat_finals_json', sa.JSON(), nullable=False),
        sa.Column('trait_chips_json', sa.JSON(), nullable=False),
        sa.Column('contradiction_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['game_run.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id'),
    )


def downgrade():
    op.drop_table('game_run_outcome')
    op.drop_index('idx_game_run_uuid', table_name='game_run')
    op.drop_index('idx_game_run_user_status', table_name='game_run')
    op.drop_index('idx_game_run_fingerprint_status', table_name='game_run')
    op.drop_table('game_run')
