"""Add native statement system models (Phase 1)

Revision ID: c1a2b3c4d5e6
Revises: f740175127e3
Create Date: 2025-10-26 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1a2b3c4d5e6'
down_revision = 'f740175127e3'
branch_labels = None
depends_on = None


def upgrade():
    # Add has_native_statements column to discussion table
    with op.batch_alter_table('discussion', schema=None) as batch_op:
        batch_op.add_column(sa.Column('has_native_statements', sa.Boolean(), nullable=True))
        batch_op.alter_column('embed_code', existing_type=sa.String(length=800), nullable=True)
    
    # Set default value for existing rows
    op.execute("UPDATE discussion SET has_native_statements = FALSE WHERE has_native_statements IS NULL")
    
    # Make has_native_statements not nullable
    with op.batch_alter_table('discussion', schema=None) as batch_op:
        batch_op.alter_column('has_native_statements', nullable=False)
    
    # Create statement table
    op.create_table('statement',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('discussion_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('statement_type', sa.String(length=20), nullable=True),
        sa.Column('parent_statement_id', sa.Integer(), nullable=True),
        sa.Column('vote_count_agree', sa.Integer(), nullable=True),
        sa.Column('vote_count_disagree', sa.Integer(), nullable=True),
        sa.Column('vote_count_unsure', sa.Integer(), nullable=True),
        sa.Column('mod_status', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('is_seed', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id'], ),
        sa.ForeignKeyConstraint(['parent_statement_id'], ['statement.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('discussion_id', 'content', name='uq_discussion_statement')
    )
    with op.batch_alter_table('statement', schema=None) as batch_op:
        batch_op.create_index('idx_statement_discussion', ['discussion_id'], unique=False)
        batch_op.create_index('idx_statement_user', ['user_id'], unique=False)

    # Create statement_vote table
    op.create_table('statement_vote',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('statement_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('discussion_id', sa.Integer(), nullable=False),
        sa.Column('vote', sa.SmallInteger(), nullable=False),
        sa.Column('confidence', sa.SmallInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id'], ),
        sa.ForeignKeyConstraint(['statement_id'], ['statement.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('statement_id', 'user_id', name='uq_statement_user_vote')
    )
    with op.batch_alter_table('statement_vote', schema=None) as batch_op:
        batch_op.create_index('idx_vote_discussion_statement', ['discussion_id', 'statement_id'], unique=False)
        batch_op.create_index('idx_vote_discussion_user', ['discussion_id', 'user_id'], unique=False)

    # Create response table
    op.create_table('response',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('statement_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('parent_response_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.String(length=20), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['parent_response_id'], ['response.id'], ),
        sa.ForeignKeyConstraint(['statement_id'], ['statement.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('response', schema=None) as batch_op:
        batch_op.create_index('idx_response_statement', ['statement_id'], unique=False)
        batch_op.create_index('idx_response_user', ['user_id'], unique=False)

    # Create evidence table
    op.create_table('evidence',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('response_id', sa.Integer(), nullable=False),
        sa.Column('source_title', sa.String(length=500), nullable=True),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.Column('citation', sa.Text(), nullable=True),
        sa.Column('quality_status', sa.String(length=20), nullable=True),
        sa.Column('storage_key', sa.String(length=500), nullable=True),
        sa.Column('storage_url', sa.String(length=1000), nullable=True),
        sa.Column('added_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['added_by_user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['response_id'], ['response.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('evidence', schema=None) as batch_op:
        batch_op.create_index('idx_evidence_response', ['response_id'], unique=False)

    # Create consensus_analysis table
    op.create_table('consensus_analysis',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('discussion_id', sa.Integer(), nullable=False),
        sa.Column('cluster_data', sa.JSON(), nullable=False),
        sa.Column('num_clusters', sa.Integer(), nullable=True),
        sa.Column('silhouette_score', sa.Float(), nullable=True),
        sa.Column('method', sa.String(length=50), nullable=True),
        sa.Column('participants_count', sa.Integer(), nullable=True),
        sa.Column('statements_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['discussion_id'], ['discussion.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('consensus_analysis', schema=None) as batch_op:
        batch_op.create_index('idx_consensus_discussion', ['discussion_id'], unique=False)

    # Create statement_flag table
    op.create_table('statement_flag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('statement_id', sa.Integer(), nullable=False),
        sa.Column('flagger_user_id', sa.Integer(), nullable=False),
        sa.Column('flag_reason', sa.String(length=50), nullable=True),
        sa.Column('additional_context', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['flagger_user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['statement_id'], ['statement.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('statement_flag', schema=None) as batch_op:
        batch_op.create_index('idx_flag_statement', ['statement_id'], unique=False)
        batch_op.create_index('idx_flag_status', ['status'], unique=False)

    # Create user_api_key table
    op.create_table('user_api_key',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('encrypted_api_key', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('last_validated', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('user_api_key', schema=None) as batch_op:
        batch_op.create_index('idx_api_key_user', ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('user_api_key', schema=None) as batch_op:
        batch_op.drop_index('idx_api_key_user')
    op.drop_table('user_api_key')

    with op.batch_alter_table('statement_flag', schema=None) as batch_op:
        batch_op.drop_index('idx_flag_status')
        batch_op.drop_index('idx_flag_statement')
    op.drop_table('statement_flag')

    with op.batch_alter_table('consensus_analysis', schema=None) as batch_op:
        batch_op.drop_index('idx_consensus_discussion')
    op.drop_table('consensus_analysis')

    with op.batch_alter_table('evidence', schema=None) as batch_op:
        batch_op.drop_index('idx_evidence_response')
    op.drop_table('evidence')

    with op.batch_alter_table('response', schema=None) as batch_op:
        batch_op.drop_index('idx_response_user')
        batch_op.drop_index('idx_response_statement')
    op.drop_table('response')

    with op.batch_alter_table('statement_vote', schema=None) as batch_op:
        batch_op.drop_index('idx_vote_discussion_user')
        batch_op.drop_index('idx_vote_discussion_statement')
    op.drop_table('statement_vote')

    with op.batch_alter_table('statement', schema=None) as batch_op:
        batch_op.drop_index('idx_statement_user')
        batch_op.drop_index('idx_statement_discussion')
    op.drop_table('statement')

    with op.batch_alter_table('discussion', schema=None) as batch_op:
        batch_op.drop_column('has_native_statements')
        batch_op.alter_column('embed_code', existing_type=sa.String(length=800), nullable=False)

