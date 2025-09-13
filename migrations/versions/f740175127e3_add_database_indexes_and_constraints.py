"""add_database_indexes_and_constraints

Revision ID: f740175127e3
Revises: 294c806bafa6
Create Date: 2025-09-13 12:29:35.165039

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f740175127e3'
down_revision = '294c806bafa6'
branch_labels = None
depends_on = None


def upgrade():
    # Clean up duplicate participants before adding unique constraint
    # Keep the oldest record for each discussion_id, participant_identifier pair
    connection = op.get_bind()
    connection.execute(sa.text("""
        DELETE FROM discussion_participant 
        WHERE id NOT IN (
            SELECT MIN(id) 
            FROM discussion_participant 
            GROUP BY discussion_id, participant_identifier
        );
    """))
    
    # Add unique constraint to prevent duplicate participants
    # Note: This includes handling nullable user_id
    op.create_unique_constraint(
        'uq_discussion_participant_identifier',
        'discussion_participant',
        ['discussion_id', 'participant_identifier']
    )
    
    # Add performance indexes for notifications
    op.create_index(
        'ix_notification_user_created',
        'notification',
        ['user_id', 'created_at']
    )
    
    op.create_index(
        'ix_notification_discussion_created',
        'notification',
        ['discussion_id', 'created_at']
    )
    
    op.create_index(
        'ix_notification_type',
        'notification',
        ['type']
    )
    
    # Add performance indexes for discussion participants
    op.create_index(
        'ix_discussion_participant_discussion',
        'discussion_participant',
        ['discussion_id']
    )
    
    op.create_index(
        'ix_discussion_participant_user',
        'discussion_participant',
        ['user_id']
    )
    
    op.create_index(
        'ix_discussion_participant_activity',
        'discussion_participant',
        ['last_activity']
    )
    
    # Add performance indexes for discussions
    op.create_index(
        'ix_discussion_creator_created',
        'discussion',
        ['creator_id', 'created_at']
    )
    
    op.create_index(
        'ix_discussion_topic_country',
        'discussion',
        ['topic', 'country']
    )


def downgrade():
    # Remove indexes (in reverse order)
    op.drop_index('ix_discussion_topic_country', 'discussion')
    op.drop_index('ix_discussion_creator_created', 'discussion')
    op.drop_index('ix_discussion_participant_activity', 'discussion_participant')
    op.drop_index('ix_discussion_participant_user', 'discussion_participant')
    op.drop_index('ix_discussion_participant_discussion', 'discussion_participant')
    op.drop_index('ix_notification_type', 'notification')
    op.drop_index('ix_notification_discussion_created', 'notification')
    op.drop_index('ix_notification_user_created', 'notification')
    
    # Remove unique constraint
    op.drop_constraint('uq_discussion_participant_identifier', 'discussion_participant')
