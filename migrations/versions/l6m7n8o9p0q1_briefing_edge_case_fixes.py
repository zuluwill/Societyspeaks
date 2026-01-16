"""Briefing edge case fixes

- Add unique constraint on BriefRun (briefing_id, scheduled_at) to prevent duplicate runs
- Add ondelete='SET NULL' to BriefRunItem foreign keys to prevent orphaned references
- Add magic_token_expires_at column to BriefRecipient for token expiry tracking

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2025-01-16 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l6m7n8o9p0q1'
down_revision = 'k5l6m7n8o9p0'
branch_labels = None
depends_on = None


def upgrade():
    """
    Apply edge case fixes:
    1. Add unique constraint to prevent duplicate BriefRuns
    2. Update BriefRunItem FKs to SET NULL on delete
    3. Add token expiry tracking to BriefRecipient
    """
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Add magic_token_expires_at column to brief_recipient
    with op.batch_alter_table('brief_recipient', schema=None) as batch_op:
        batch_op.add_column(sa.Column('magic_token_expires_at', sa.DateTime(), nullable=True))

    # 2. Add unique constraint to brief_run (briefing_id, scheduled_at)
    with op.batch_alter_table('brief_run', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_brief_run_briefing_scheduled',
            ['briefing_id', 'scheduled_at']
        )

    # 3. Update BriefRunItem foreign keys to have ondelete='SET NULL'
    if dialect == 'sqlite':
        # SQLite doesn't support ALTER for foreign keys easily
        # The ORM will handle this at application level
        print("SQLite detected - SET NULL behavior for BriefRunItem FKs will be handled at application level")
        return

    # For PostgreSQL/MySQL - update foreign keys
    from sqlalchemy import inspect
    inspector = inspect(bind)
    fks = inspector.get_foreign_keys('brief_run_item')

    with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
        # Find and update ingested_item_id FK
        for fk in fks:
            if 'ingested_item_id' in fk['constrained_columns']:
                if fk['name']:
                    batch_op.drop_constraint(fk['name'], type_='foreignkey')
                batch_op.create_foreign_key(
                    'fk_brief_run_item_ingested_item',
                    'ingested_item',
                    ['ingested_item_id'],
                    ['id'],
                    ondelete='SET NULL'
                )
                break

        # Find and update trending_topic_id FK
        for fk in fks:
            if 'trending_topic_id' in fk['constrained_columns']:
                if fk['name']:
                    batch_op.drop_constraint(fk['name'], type_='foreignkey')
                batch_op.create_foreign_key(
                    'fk_brief_run_item_trending_topic',
                    'trending_topic',
                    ['trending_topic_id'],
                    ['id'],
                    ondelete='SET NULL'
                )
                break


def downgrade():
    """
    Revert changes:
    1. Remove magic_token_expires_at column
    2. Remove unique constraint
    3. Revert FK ondelete behavior (handled by ORM for SQLite)
    """
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Remove unique constraint from brief_run
    with op.batch_alter_table('brief_run', schema=None) as batch_op:
        batch_op.drop_constraint('uq_brief_run_briefing_scheduled', type_='unique')

    # 2. Remove magic_token_expires_at column
    with op.batch_alter_table('brief_recipient', schema=None) as batch_op:
        batch_op.drop_column('magic_token_expires_at')

    # 3. Revert FK changes (PostgreSQL/MySQL only)
    if dialect == 'sqlite':
        print("SQLite detected - FK changes handled at application level")
        return

    from sqlalchemy import inspect
    inspector = inspect(bind)
    fks = inspector.get_foreign_keys('brief_run_item')

    with op.batch_alter_table('brief_run_item', schema=None) as batch_op:
        # Revert ingested_item_id FK
        for fk in fks:
            if 'ingested_item_id' in fk['constrained_columns']:
                if fk['name']:
                    batch_op.drop_constraint(fk['name'], type_='foreignkey')
                batch_op.create_foreign_key(
                    'fk_brief_run_item_ingested_item',
                    'ingested_item',
                    ['ingested_item_id'],
                    ['id']
                )
                break

        # Revert trending_topic_id FK
        for fk in fks:
            if 'trending_topic_id' in fk['constrained_columns']:
                if fk['name']:
                    batch_op.drop_constraint(fk['name'], type_='foreignkey')
                batch_op.create_foreign_key(
                    'fk_brief_run_item_trending_topic',
                    'trending_topic',
                    ['trending_topic_id'],
                    ['id']
                )
                break
