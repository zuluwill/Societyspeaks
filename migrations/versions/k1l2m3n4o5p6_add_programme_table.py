"""add programme table

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'k1l2m3n4o5p6'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'programme',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=150), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('creator_id', sa.Integer(), nullable=True),
        sa.Column('company_profile_id', sa.Integer(), nullable=True),
        sa.Column('geographic_scope', sa.String(length=20), nullable=False, server_default='global'),
        sa.Column('country', sa.String(length=100), nullable=True),
        sa.Column('logo_url', sa.String(length=255), nullable=True),
        sa.Column('themes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('phases', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('cohorts', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['creator_id'], ['user.id']),
        sa.ForeignKeyConstraint(['company_profile_id'], ['company_profile.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('ix_programme_slug', 'programme', ['slug'], unique=True)
    op.create_index('ix_programme_creator_id', 'programme', ['creator_id'], unique=False)
    op.create_index('ix_programme_company_profile_id', 'programme', ['company_profile_id'], unique=False)
    op.create_index('ix_programme_scope_country', 'programme', ['geographic_scope', 'country'], unique=False)

    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.create_check_constraint(
            'ck_programme_exactly_one_owner',
            'programme',
            '((creator_id IS NULL) != (company_profile_id IS NULL))'
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.drop_constraint('ck_programme_exactly_one_owner', 'programme', type_='check')

    op.drop_index('ix_programme_scope_country', table_name='programme')
    op.drop_index('ix_programme_company_profile_id', table_name='programme')
    op.drop_index('ix_programme_creator_id', table_name='programme')
    op.drop_index('ix_programme_slug', table_name='programme')
    op.drop_table('programme')
