"""A live trial, and credit for a pass upgraded to annual

Adds consultation_trial (one per account and one per normalised email) and
consultation_purchase.credited_at. A work domain is recorded so a run of
trials can be reviewed; it is not unique. ending_notified_at records that
the host has been warned the window is about to end.

Revision ID: t14d6r1a1l9s
Revises: p30d4y5p6a7s
Create Date: 2026-10-02

"""
from alembic import op
import sqlalchemy as sa


revision = 't14d6r1a1l9s'
down_revision = 'p30d4y5p6a7s'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if 'consultation_trial' not in tables:
        op.create_table(
            'consultation_trial',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('email_key', sa.String(length=320), nullable=False),
            sa.Column('domain', sa.String(length=253), nullable=True),
            sa.Column('acquisition_source', sa.String(length=80), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=False),
            sa.Column('ends_at', sa.DateTime(), nullable=False),
            sa.Column('ending_notified_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
            sa.UniqueConstraint('email_key'),
        )
        op.create_index('ix_consultation_trial_ends_at', 'consultation_trial', ['ends_at'])
        op.create_index('ix_consultation_trial_domain', 'consultation_trial', ['domain'])
    else:
        trial_columns = {column['name'] for column in inspector.get_columns('consultation_trial')}
        if 'ending_notified_at' not in trial_columns:
            op.add_column('consultation_trial', sa.Column('ending_notified_at', sa.DateTime(), nullable=True))
        if 'acquisition_source' not in trial_columns:
            op.add_column('consultation_trial', sa.Column('acquisition_source', sa.String(length=80), nullable=True))

    purchase_columns = {column['name'] for column in inspector.get_columns('consultation_purchase')}
    if 'credited_at' not in purchase_columns:
        op.add_column('consultation_purchase', sa.Column('credited_at', sa.DateTime(), nullable=True))
    if 'ending_notified_at' not in purchase_columns:
        op.add_column('consultation_purchase', sa.Column('ending_notified_at', sa.DateTime(), nullable=True))

    if 'consultation_plan' in tables:
        plan_columns = {column['name'] for column in inspector.get_columns('consultation_plan')}
        if 'ending_notified_at' not in plan_columns:
            op.add_column('consultation_plan', sa.Column('ending_notified_at', sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if 'consultation_plan' in tables:
        plan_columns = {column['name'] for column in inspector.get_columns('consultation_plan')}
        if 'ending_notified_at' in plan_columns:
            op.drop_column('consultation_plan', 'ending_notified_at')
    purchase_columns = {column['name'] for column in inspector.get_columns('consultation_purchase')}
    if 'ending_notified_at' in purchase_columns:
        op.drop_column('consultation_purchase', 'ending_notified_at')
    if 'credited_at' in purchase_columns:
        op.drop_column('consultation_purchase', 'credited_at')
    if 'consultation_trial' in tables:
        op.drop_index('ix_consultation_trial_domain', table_name='consultation_trial')
        op.drop_index('ix_consultation_trial_ends_at', table_name='consultation_trial')
        op.drop_table('consultation_trial')
