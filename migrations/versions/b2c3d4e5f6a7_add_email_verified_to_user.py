"""Add email_verified column to user table

Revision ID: b2c3d4e5f6a7
Revises: 03b0c73eaa2f
Create Date: 2026-03-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = '03b0c73eaa2f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('email_verified', sa.Boolean(), nullable=True))
    # Grandfather in existing users who already have a profile — they went through onboarding
    # and are clearly active, so treat their email as verified.
    op.execute("""
        UPDATE "user" u
        SET email_verified = TRUE
        WHERE EXISTS (
            SELECT 1 FROM individual_profile ip WHERE ip.user_id = u.id
        ) OR EXISTS (
            SELECT 1 FROM company_profile cp WHERE cp.user_id = u.id
        )
    """)
    # Any remaining users (no profile yet) are considered unverified
    op.execute('UPDATE "user" SET email_verified = FALSE WHERE email_verified IS NULL')
    op.alter_column('user', 'email_verified', nullable=False, server_default=sa.text('false'))


def downgrade():
    op.drop_column('user', 'email_verified')
