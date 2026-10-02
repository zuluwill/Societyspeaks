"""A one-off consultation payment is a 30-day pass

Adds consultation_purchase.valid_from and valid_until (the window) and
consultation.covered_by_purchase_id (many consultations, one pass).

A pass already spent on one consultation stays spent: it is not reopened.
A payment that has not been used yet becomes a pass for the 30 days after
this migration runs, whenever it was bought, so nobody loses what they paid for.

Revision ID: p30d4y5p6a7s
Revises: c1n2s3l4t5a6
Create Date: 2026-10-02

"""
from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa


revision = 'p30d4y5p6a7s'
down_revision = 'c1n2s3l4t5a6'
branch_labels = None
depends_on = None

# Matches the CONSULTATION_PASS_DAYS default. Existing unused payments were
# bought as a single consultation; each becomes a full pass from today.
_PASS_DAYS = 30


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    purchase_columns = {column['name'] for column in inspector.get_columns('consultation_purchase')}
    if 'valid_from' not in purchase_columns:
        op.add_column('consultation_purchase', sa.Column('valid_from', sa.DateTime(), nullable=True))
    if 'valid_until' not in purchase_columns:
        op.add_column('consultation_purchase', sa.Column('valid_until', sa.DateTime(), nullable=True))

    consultation_columns = {column['name'] for column in inspector.get_columns('consultation')}
    if 'covered_by_purchase_id' not in consultation_columns:
        op.add_column(
            'consultation',
            sa.Column('covered_by_purchase_id', sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            'fk_consultation_covered_by_purchase',
            'consultation',
            'consultation_purchase',
            ['covered_by_purchase_id'],
            ['id'],
            ondelete='SET NULL',
        )
        op.create_index(
            'idx_consultation_covered_by_purchase',
            'consultation',
            ['covered_by_purchase_id'],
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    bind.execute(
        sa.text(
            "UPDATE consultation_purchase SET valid_from = :start, valid_until = :until "
            "WHERE status = 'paid' AND consumed_at IS NULL AND valid_until IS NULL"
        ),
        {'start': now, 'until': now + timedelta(days=_PASS_DAYS)},
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    consultation_columns = {column['name'] for column in inspector.get_columns('consultation')}
    if 'covered_by_purchase_id' in consultation_columns:
        op.drop_index('idx_consultation_covered_by_purchase', table_name='consultation')
        op.drop_constraint('fk_consultation_covered_by_purchase', 'consultation', type_='foreignkey')
        op.drop_column('consultation', 'covered_by_purchase_id')
    purchase_columns = {column['name'] for column in inspector.get_columns('consultation_purchase')}
    if 'valid_until' in purchase_columns:
        op.drop_column('consultation_purchase', 'valid_until')
    if 'valid_from' in purchase_columns:
        op.drop_column('consultation_purchase', 'valid_from')
