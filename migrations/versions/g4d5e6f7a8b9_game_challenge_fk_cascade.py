"""Add ON DELETE CASCADE to game_challenge.creator_run_id FK.

The table was created in g3c4h5a6l7l8 without the CASCADE rule.  That
migration file was later edited in-place, but Alembic tracks revisions by ID
so the edit never ran in any environment that had already applied
g3c4h5a6l7l8.  This revision drops the bare FK and recreates it with
ON DELETE CASCADE so that deleting a game_run automatically removes any
associated game_challenge row, honouring the account-deletion privacy promise.

Revision ID: g4d5e6f7a8b9
Revises: g3c4h5a6l7l8
Create Date: 2026-05-22
"""

from alembic import op

revision = 'g4d5e6f7a8b9'
down_revision = 'g3c4h5a6l7l8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('game_challenge') as batch_op:
        # Drop the constraint regardless of its auto-generated name.
        batch_op.drop_constraint(
            'game_challenge_creator_run_id_fkey', type_='foreignkey'
        )
        batch_op.create_foreign_key(
            'game_challenge_creator_run_id_fkey',
            'game_run',
            ['creator_run_id'],
            ['id'],
            ondelete='CASCADE',
        )


def downgrade():
    with op.batch_alter_table('game_challenge') as batch_op:
        batch_op.drop_constraint(
            'game_challenge_creator_run_id_fkey', type_='foreignkey'
        )
        batch_op.create_foreign_key(
            'game_challenge_creator_run_id_fkey',
            'game_run',
            ['creator_run_id'],
            ['id'],
        )
