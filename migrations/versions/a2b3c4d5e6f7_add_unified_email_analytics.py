"""Add unified email analytics

Revision ID: a2b3c4d5e6f7
Revises: 615fd0b16628
Create Date: 2026-01-08

Creates unified EmailEvent table that tracks all email types
(auth, daily_brief, daily_question, discussion, admin).

Replaces the brief-specific BriefEmailEvent table with a generic system.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = '615fd0b16628'
branch_labels = None
depends_on = None


def upgrade():
    # Create the unified email_event table
    op.create_table('email_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('resend_email_id', sa.String(length=255), nullable=True),
        sa.Column('email_category', sa.String(length=30), nullable=False),
        sa.Column('email_subject', sa.String(length=500), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('brief_subscriber_id', sa.Integer(), nullable=True),
        sa.Column('question_subscriber_id', sa.Integer(), nullable=True),
        sa.Column('brief_id', sa.Integer(), nullable=True),
        sa.Column('daily_question_id', sa.Integer(), nullable=True),
        sa.Column('click_url', sa.String(length=500), nullable=True),
        sa.Column('bounce_type', sa.String(length=50), nullable=True),
        sa.Column('complaint_type', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['brief_id'], ['daily_brief.id'], ),
        sa.ForeignKeyConstraint(['brief_subscriber_id'], ['daily_brief_subscriber.id'], ),
        sa.ForeignKeyConstraint(['daily_question_id'], ['daily_question.id'], ),
        sa.ForeignKeyConstraint(['question_subscriber_id'], ['daily_question_subscriber.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for efficient querying
    op.create_index('idx_ee_email', 'email_event', ['recipient_email'], unique=False)
    op.create_index('idx_ee_category', 'email_event', ['email_category'], unique=False)
    op.create_index('idx_ee_event_type', 'email_event', ['event_type'], unique=False)
    op.create_index('idx_ee_created', 'email_event', ['created_at'], unique=False)
    op.create_index('idx_ee_resend_id', 'email_event', ['resend_email_id'], unique=False)

    # Migrate data from brief_email_event if it exists
    # Note: This is done safely - only runs if the old table exists
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = inspector.get_table_names()
    
    if 'brief_email_event' in tables:
        # Migrate existing data to new table
        connection.execute(sa.text("""
            INSERT INTO email_event (
                recipient_email, resend_email_id, email_category, event_type,
                brief_subscriber_id, brief_id, click_url, bounce_type, 
                user_agent, ip_address, created_at
            )
            SELECT 
                COALESCE(dbs.email, 'unknown@email.com') as recipient_email,
                bee.resend_email_id,
                'daily_brief' as email_category,
                REPLACE(bee.event_type, 'email.', '') as event_type,
                bee.subscriber_id as brief_subscriber_id,
                bee.brief_id,
                bee.click_url,
                bee.bounce_type,
                bee.user_agent,
                bee.ip_address,
                bee.created_at
            FROM brief_email_event bee
            LEFT JOIN daily_brief_subscriber dbs ON bee.subscriber_id = dbs.id
        """))
        
        # Drop old table after migration
        op.drop_table('brief_email_event')


def downgrade():
    # Recreate the old brief_email_event table
    op.create_table('brief_email_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subscriber_id', sa.Integer(), nullable=True),
        sa.Column('brief_id', sa.Integer(), nullable=True),
        sa.Column('resend_email_id', sa.String(length=255), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('click_url', sa.String(length=500), nullable=True),
        sa.Column('bounce_type', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['brief_id'], ['daily_brief.id'], ),
        sa.ForeignKeyConstraint(['subscriber_id'], ['daily_brief_subscriber.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_bee_subscriber', 'brief_email_event', ['subscriber_id'], unique=False)
    op.create_index('idx_bee_brief', 'brief_email_event', ['brief_id'], unique=False)
    op.create_index('idx_bee_type', 'brief_email_event', ['event_type'], unique=False)
    op.create_index('idx_bee_created', 'brief_email_event', ['created_at'], unique=False)
    
    # Migrate data back from email_event to brief_email_event
    connection = op.get_bind()
    connection.execute(sa.text("""
        INSERT INTO brief_email_event (
            subscriber_id, brief_id, resend_email_id, event_type,
            click_url, bounce_type, user_agent, ip_address, created_at
        )
        SELECT 
            brief_subscriber_id,
            brief_id,
            resend_email_id,
            CONCAT('email.', event_type) as event_type,
            click_url,
            bounce_type,
            user_agent,
            ip_address,
            created_at
        FROM email_event
        WHERE email_category = 'daily_brief'
    """))
    
    # Drop new table
    op.drop_index('idx_ee_resend_id', table_name='email_event')
    op.drop_index('idx_ee_created', table_name='email_event')
    op.drop_index('idx_ee_event_type', table_name='email_event')
    op.drop_index('idx_ee_category', table_name='email_event')
    op.drop_index('idx_ee_email', table_name='email_event')
    op.drop_table('email_event')
