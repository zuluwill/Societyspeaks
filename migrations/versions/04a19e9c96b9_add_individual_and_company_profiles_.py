"""Add individual and company profiles with discussion relationships

Revision ID: 04a19e9c96b9
Revises: d031d43fab90
Create Date: 2024-10-25 08:19:34.719198

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '04a19e9c96b9'
down_revision = 'd031d43fab90'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('company_profile',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('company_name', sa.String(length=150), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('banner_image', sa.String(length=255), nullable=True),
    sa.Column('logo', sa.String(length=255), nullable=True),
    sa.Column('social_links', sa.JSON(), nullable=True),
    sa.Column('slug', sa.String(length=150), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('individual_profile',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('full_name', sa.String(length=150), nullable=False),
    sa.Column('bio', sa.Text(), nullable=True),
    sa.Column('banner_image', sa.String(length=255), nullable=True),
    sa.Column('profile_image', sa.String(length=255), nullable=True),
    sa.Column('social_links', sa.JSON(), nullable=True),
    sa.Column('slug', sa.String(length=150), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    with op.batch_alter_table('discussion', schema=None) as batch_op:
        batch_op.add_column(sa.Column('individual_profile_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('company_profile_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(None, 'individual_profile', ['individual_profile_id'], ['id'])
        batch_op.create_foreign_key(None, 'company_profile', ['company_profile_id'], ['id'])

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('profile_type', sa.String(length=50), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('profile_type')

    with op.batch_alter_table('discussion', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('company_profile_id')
        batch_op.drop_column('individual_profile_id')

    op.drop_table('individual_profile')
    op.drop_table('company_profile')
    # ### end Alembic commands ###
