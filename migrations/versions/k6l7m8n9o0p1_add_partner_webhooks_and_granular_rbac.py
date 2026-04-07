"""Add partner webhooks and granular partner-member permissions

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa


revision = 'k6l7m8n9o0p1'
down_revision = 'j5k6l7m8n9o0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'partner_member',
        sa.Column('permissions_json', sa.JSON(), nullable=False, server_default='{}'),
    )
    op.alter_column('partner_member', 'permissions_json', server_default=None)

    op.create_table(
        'partner_webhook_endpoint',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('partner_id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=1000), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('event_types', sa.JSON(), nullable=False),
        sa.Column('encrypted_signing_secret', sa.Text(), nullable=False),
        sa.Column('secret_last4', sa.String(length=4), nullable=False),
        sa.Column('last_delivery_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['partner_id'], ['partner.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_partner_webhook_partner_status',
        'partner_webhook_endpoint',
        ['partner_id', 'status'],
        unique=False,
    )
    # Note: JSON columns cannot be indexed with btree (PostgreSQL default).
    # Webhook event_type filtering is done in application code; no index needed.

    op.create_table(
        'partner_webhook_delivery',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('endpoint_id', sa.Integer(), nullable=False),
        sa.Column('partner_id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(length=80), nullable=False),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('last_http_status', sa.Integer(), nullable=True),
        sa.Column('last_response_body', sa.Text(), nullable=True),
        sa.Column('last_error', sa.String(length=500), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['endpoint_id'], ['partner_webhook_endpoint.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['partner_id'], ['partner.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint_id', 'event_id', name='uq_partner_webhook_delivery_endpoint_event'),
    )
    op.create_index(
        'idx_partner_webhook_delivery_status_next',
        'partner_webhook_delivery',
        ['status', 'next_attempt_at'],
        unique=False,
    )
    op.create_index(
        'idx_partner_webhook_delivery_endpoint_created',
        'partner_webhook_delivery',
        ['endpoint_id', 'created_at'],
        unique=False,
    )

    bind = op.get_bind()
    duplicate_rows = bind.execute(
        sa.text(
            """
            SELECT partner_env, partner_id, partner_external_id, COUNT(*) AS c
            FROM discussion
            WHERE partner_external_id IS NOT NULL
            GROUP BY partner_env, partner_id, partner_external_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).fetchall()
    if duplicate_rows:
        env, partner_id, external_id, count = duplicate_rows[0]
        raise RuntimeError(
            "Cannot add unique partner external_id constraint: duplicate rows found "
            f"(env={env}, partner_id={partner_id}, external_id={external_id}, count={count})."
        )

    op.create_index(
        'uq_discussion_partner_env_external_id_slug',
        'discussion',
        ['partner_env', 'partner_id', 'partner_external_id'],
        unique=True,
    )


def downgrade():
    op.drop_index('uq_discussion_partner_env_external_id_slug', table_name='discussion')

    op.drop_index('idx_partner_webhook_delivery_endpoint_created', table_name='partner_webhook_delivery')
    op.drop_index('idx_partner_webhook_delivery_status_next', table_name='partner_webhook_delivery')
    op.drop_table('partner_webhook_delivery')

    op.drop_index('idx_partner_webhook_partner_status', table_name='partner_webhook_endpoint')
    op.drop_table('partner_webhook_endpoint')

    op.drop_column('partner_member', 'permissions_json')
