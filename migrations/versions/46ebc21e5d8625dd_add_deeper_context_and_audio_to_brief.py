"""Add deeper context and audio to brief items

Revision ID: 46ebc21e5d8625dd
Revises: h2i3j4k5l6m7
Create Date: 2026-01-26 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '46ebc21e5d8625dd'
down_revision = 'p1q2r3s4t5u6'  # After polymarket integration
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    # Add deeper_context field to brief_item
    if not column_exists('brief_item', 'deeper_context'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('deeper_context', sa.Text(), nullable=True))
    
    # Add audio fields to brief_item
    if not column_exists('brief_item', 'audio_url'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('audio_url', sa.String(length=500), nullable=True))
    
    if not column_exists('brief_item', 'audio_voice_id'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('audio_voice_id', sa.String(length=100), nullable=True))
    
    if not column_exists('brief_item', 'audio_generated_at'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('audio_generated_at', sa.DateTime(), nullable=True))


def downgrade():
    # Remove audio fields
    if column_exists('brief_item', 'audio_generated_at'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.drop_column('audio_generated_at')
    
    if column_exists('brief_item', 'audio_voice_id'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.drop_column('audio_voice_id')
    
    if column_exists('brief_item', 'audio_url'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.drop_column('audio_url')
    
    # Remove deeper_context field
    if column_exists('brief_item', 'deeper_context'):
        with op.batch_alter_table('brief_item', schema=None) as batch_op:
            batch_op.drop_column('deeper_context')
