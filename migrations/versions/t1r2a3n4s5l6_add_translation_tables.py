"""Add statement_translation and discussion_translation tables.

Stores machine-translated content for statements and discussion titles/descriptions.
Votes continue to target the canonical statement_id — these tables are a display cache only.

Revision ID: t1r2a3n4s5l6
Revises: 00788e2801eb
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa


revision = 't1r2a3n4s5l6'
down_revision = '00788e2801eb'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'statement_translation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('statement_id', sa.Integer(), nullable=False),
        sa.Column('language_code', sa.String(10), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('translation_source', sa.String(20), nullable=True, server_default='machine'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['statement_id'], ['statement.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('statement_id', 'language_code', name='uq_statement_translation'),
    )
    op.create_index('idx_stmt_translation_stmt_lang', 'statement_translation', ['statement_id', 'language_code'])

    op.create_table(
        'discussion_translation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('discussion_id', sa.Integer(), nullable=False),
        sa.Column('language_code', sa.String(10), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('information_title', sa.Text(), nullable=True),
        sa.Column('information_body', sa.Text(), nullable=True),
        sa.Column('translation_source', sa.String(20), nullable=True, server_default='machine'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('discussion_id', 'language_code', name='uq_discussion_translation'),
    )
    op.create_index('idx_disc_translation_disc_lang', 'discussion_translation', ['discussion_id', 'language_code'])


def downgrade():
    op.drop_index('idx_disc_translation_disc_lang', table_name='discussion_translation')
    op.drop_table('discussion_translation')
    op.drop_index('idx_stmt_translation_stmt_lang', table_name='statement_translation')
    op.drop_table('statement_translation')
