"""Add slug to Discussion model

Revision ID: d3fad8d6533c
Revises: e0ccc49c9b2d
Create Date: 2024-10-30 09:24:58.384199

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3fad8d6533c'
down_revision = 'e0ccc49c9b2d'
branch_labels = None
depends_on = None

def upgrade():
    # Step 1: Add the slug column as nullable initially
    with op.batch_alter_table('discussion', schema=None) as batch_op:
        batch_op.add_column(sa.Column('slug', sa.String(length=150), nullable=True))
        batch_op.create_unique_constraint(None, ['slug'])

    # Step 2: Set slug for the existing discussion row
    op.execute("UPDATE discussion SET slug = 'how_should_we_improve_the_nhs' WHERE id = 1")

    # Step 3: Alter slug column to be NOT NULL
    with op.batch_alter_table('discussion', schema=None) as batch_op:
        batch_op.alter_column('slug', nullable=False)


def downgrade():
    with op.batch_alter_table('discussion', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='unique')
        batch_op.drop_column('slug')