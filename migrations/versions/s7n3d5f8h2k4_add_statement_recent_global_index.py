"""Add idx_statement_recent_global for the cross-discussion statement feed

Revision ID: s7n3d5f8h2k4
Revises: m4k7t2p9q1r3
Create Date: 2026-09-02

/statements/search lists statements across all discussions ordered by
created_at DESC. Every existing "recent" index on statement is prefixed by
discussion_id, so none of them could serve a query with no discussion filter.

Measured on production (71,973 statements) before this index:

    Parallel Seq Scan on statement -> Hash Join -> top-N heapsort
    3,714 buffers, 68.7 ms warm (200 ms mean / 852 ms max in
    pg_stat_statements) to return 20 rows

and after:

    Index Scan Backward using idx_statement_recent_global -> Nested Loop
    10 buffers, 0.12 ms

The filter (is_deleted IS false AND mod_status >= 0) currently removes zero
rows, so a partial index would add predicate-matching fragility for no gain;
the ordering is what the planner could not satisfy. Ascending is deliberate:
Postgres scans it backwards for the DESC ordering, and it keeps the same
DDL working on SQLite in CI.

Not added: a covering index for the pagination COUNT. Measured, it turned the
scan into an index-only scan but left total execution at ~44 ms (the cost is
the hash join, not the scan), which does not justify a second index on a
write path.

Idempotent: safe to re-run against a database that already has the index.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 's7n3d5f8h2k4'
down_revision = 'm4k7t2p9q1r3'
branch_labels = None
depends_on = None

INDEX_NAME = 'idx_statement_recent_global'


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'statement' not in inspector.get_table_names():
        return
    existing = {ix['name'] for ix in inspector.get_indexes('statement')}
    if INDEX_NAME in existing:
        return
    op.create_index(INDEX_NAME, 'statement', ['created_at', 'id'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'statement' not in inspector.get_table_names():
        return
    existing = {ix['name'] for ix in inspector.get_indexes('statement')}
    if INDEX_NAME not in existing:
        return
    op.drop_index(INDEX_NAME, table_name='statement')
