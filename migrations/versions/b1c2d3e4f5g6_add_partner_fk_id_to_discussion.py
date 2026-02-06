"""Add partner_fk_id to discussions

Revision ID: b1c2d3e4f5g6
Revises: a0b1c2d3e4f5
Create Date: 2026-02-06
"""
from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5g6'
down_revision = 'a0b1c2d3e4f5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('discussion') as batch_op:
        batch_op.add_column(sa.Column('partner_fk_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_discussion_partner_fk_id', ['partner_fk_id'])
        batch_op.create_foreign_key(
            'fk_discussion_partner_fk_id',
            'partner',
            ['partner_fk_id'],
            ['id']
        )

    # Backfill using partner slug stored in discussion.partner_id
    op.execute("""
        UPDATE discussion
        SET partner_fk_id = (
            SELECT partner.id
            FROM partner
            WHERE partner.slug = discussion.partner_id
        )
        WHERE discussion.partner_id IS NOT NULL
          AND discussion.partner_fk_id IS NULL
    """)


def downgrade():
    with op.batch_alter_table('discussion') as batch_op:
        batch_op.drop_constraint('fk_discussion_partner_fk_id', type_='foreignkey')
        batch_op.drop_index('ix_discussion_partner_fk_id')
        batch_op.drop_column('partner_fk_id')
