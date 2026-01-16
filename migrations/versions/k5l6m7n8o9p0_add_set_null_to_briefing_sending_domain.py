"""Add SET NULL to briefing.sending_domain_id foreign key

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2025-01-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'k5l6m7n8o9p0'
down_revision = 'j4k5l6m7n8o9'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add SET NULL ondelete behavior to briefing.sending_domain_id foreign key.
    This allows graceful cleanup: when a domain is deleted, briefings automatically
    fall back to default email instead of causing foreign key constraint errors.
    """
    # Get the database dialect
    bind = op.get_bind()
    dialect = bind.dialect.name
    
    if dialect == 'sqlite':
        # SQLite doesn't support ALTER for foreign keys easily
        # The ORM will handle this at application level
        print("SQLite detected - SET NULL behavior will be handled at application level")
        return
    
    # PostgreSQL/MySQL - can modify foreign keys
    # Find the existing constraint name by inspecting the table
    from sqlalchemy import inspect
    inspector = inspect(bind)
    fks = inspector.get_foreign_keys('briefing')
    constraint_name = None
    
    for fk in fks:
        if 'sending_domain_id' in fk['constrained_columns']:
            constraint_name = fk['name']
            break
    
    if constraint_name:
        with op.batch_alter_table('briefing', schema=None) as batch_op:
            # Drop existing constraint
            batch_op.drop_constraint(constraint_name, type_='foreignkey')
            
            # Recreate with SET NULL ondelete
            batch_op.create_foreign_key(
                constraint_name,
                'sending_domain',
                ['sending_domain_id'],
                ['id'],
                ondelete='SET NULL'
            )
    else:
        # Constraint not found - might be a new database, create it
        with op.batch_alter_table('briefing', schema=None) as batch_op:
            batch_op.create_foreign_key(
                'briefing_sending_domain_id_fkey',
                'sending_domain',
                ['sending_domain_id'],
                ['id'],
                ondelete='SET NULL'
            )


def downgrade():
    """
    Revert to original foreign key constraint (no ondelete specified).
    """
    bind = op.get_bind()
    dialect = bind.dialect.name
    
    if dialect == 'sqlite':
        print("SQLite detected - downgrade skipped")
        return
    
    # Find the constraint name
    from sqlalchemy import inspect
    inspector = inspect(bind)
    fks = inspector.get_foreign_keys('briefing')
    constraint_name = None
    
    for fk in fks:
        if 'sending_domain_id' in fk['constrained_columns']:
            constraint_name = fk['name']
            break
    
    if constraint_name:
        with op.batch_alter_table('briefing', schema=None) as batch_op:
            # Drop SET NULL constraint
            batch_op.drop_constraint(constraint_name, type_='foreignkey')
            
            # Recreate original constraint (no ondelete)
            batch_op.create_foreign_key(
                constraint_name,
                'sending_domain',
                ['sending_domain_id'],
                ['id']
            )
