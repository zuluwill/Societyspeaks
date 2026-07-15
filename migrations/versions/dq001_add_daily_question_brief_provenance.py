"""Add brief provenance fields to daily_question

Revision ID: dq001
Revises: jrs004
Create Date: 2026-07-15

Press-vs-public loop: label daily questions sourced from brief items with
coverage-frame snapshot for longitudinal framing→stance analysis.
"""
from alembic import op
import sqlalchemy as sa


revision = 'dq001'
down_revision = 'jrs004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'daily_question',
        sa.Column('source_brief_item_id', sa.Integer(), nullable=True),
    )
    op.add_column(
        'daily_question',
        sa.Column('coverage_frame_json', sa.JSON(), nullable=True),
    )
    op.create_foreign_key(
        'fk_daily_question_source_brief_item',
        'daily_question',
        'brief_item',
        ['source_brief_item_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'idx_daily_question_source_brief_item',
        'daily_question',
        ['source_brief_item_id'],
    )

    op.add_column(
        'daily_question_selection',
        sa.Column('source_brief_item_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_daily_question_selection_source_brief_item',
        'daily_question_selection',
        'brief_item',
        ['source_brief_item_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint(
        'fk_daily_question_selection_source_brief_item',
        'daily_question_selection',
        type_='foreignkey',
    )
    op.drop_column('daily_question_selection', 'source_brief_item_id')
    op.drop_index('idx_daily_question_source_brief_item', table_name='daily_question')
    op.drop_constraint(
        'fk_daily_question_source_brief_item',
        'daily_question',
        type_='foreignkey',
    )
    op.drop_column('daily_question', 'coverage_frame_json')
    op.drop_column('daily_question', 'source_brief_item_id')
