"""Add User.language preference and programme_translation table.

User.language — BCP 47 language code saved per authenticated user. NULL means
the system falls back to cookie/Accept-Language detection.

programme_translation — cached machine translations for programme name and
description (civic journey guide metadata).

Revision ID: u2v3w4x5y6z7
Revises: t1r2a3n4s5l6
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa


revision = 'u2v3w4x5y6z7'
down_revision = 't1r2a3n4s5l6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user') as batch_op:
        batch_op.add_column(sa.Column('language', sa.String(10), nullable=True))

    op.create_table(
        'programme_translation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('programme_id', sa.Integer(), nullable=False),
        sa.Column('language_code', sa.String(10), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('translation_source', sa.String(20), nullable=True, server_default='machine'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['programme_id'], ['programme.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('programme_id', 'language_code', name='uq_programme_translation'),
    )
    op.create_index('idx_prog_translation_prog_lang', 'programme_translation', ['programme_id', 'language_code'])


def downgrade():
    op.drop_index('idx_prog_translation_prog_lang', table_name='programme_translation')
    op.drop_table('programme_translation')
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('language')
