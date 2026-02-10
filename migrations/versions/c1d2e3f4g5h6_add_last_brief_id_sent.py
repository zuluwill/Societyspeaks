"""add last_brief_id_sent to daily_brief_subscriber

Revision ID: c1d2e3f4g5h6
Revises: 837a538b5b96
Create Date: 2026-02-10 18:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c1d2e3f4g5h6'
down_revision = '837a538b5b96'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('daily_brief_subscriber', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_brief_id_sent', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_dbs_last_brief_id_sent',
            'daily_brief',
            ['last_brief_id_sent'],
            ['id']
        )


def downgrade():
    with op.batch_alter_table('daily_brief_subscriber', schema=None) as batch_op:
        batch_op.drop_constraint('fk_dbs_last_brief_id_sent', type_='foreignkey')
        batch_op.drop_column('last_brief_id_sent')
