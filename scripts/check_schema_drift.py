#!/usr/bin/env python3
"""
Diff the SQLAlchemy model metadata against a live database schema.

Surfaces missing primary keys, constraints, indexes, FKs, columns and tables
in either direction. Run against production after any incident that touches
the schema, and periodically as hygiene — this is how the July 2026
missing-PK corruption (StaleDataError, failing ON CONFLICT upserts, doubled
analytics) would have been caught early.

Usage:
    DATABASE_URL=postgres://... python3 scripts/check_schema_drift.py

Exit code 1 if any HIGH-severity drift is found (missing PK/unique/FK in the
database), 0 otherwise. Cosmetic differences (extra DB indexes, constraint
vs index representation of the same rule) are listed but non-fatal.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.autogenerate import compare_metadata  # noqa: E402


def main():
    url = os.environ.get('DATABASE_URL')
    if not url:
        sys.exit('DATABASE_URL is not set')

    from app import db
    import app.models  # noqa: F401 — populate metadata

    engine = create_engine(url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={'compare_type': False, 'compare_server_default': False},
        )
        diffs = compare_metadata(ctx, db.metadata)

        # Unique indexes satisfy the same rule as unique constraints; match by
        # column set so naming differences don't false-positive.
        db_unique_column_sets = {
            (row.tablename, frozenset(row.cols))
            for row in conn.exec_driver_sql(
                """
                SELECT t.relname AS tablename,
                       array_agg(a.attname) AS cols
                FROM pg_index i
                JOIN pg_class ix ON ix.oid = i.indexrelid
                JOIN pg_class t ON t.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey)
                WHERE n.nspname = 'public' AND i.indisunique
                GROUP BY t.relname, ix.relname
                """
            )
        }
        # FK relationships by (table, columns, referenced table) — name-agnostic.
        db_fk_signatures = {
            (row.tablename, frozenset(row.cols), row.reftable)
            for row in conn.exec_driver_sql(
                """
                SELECT t.relname AS tablename,
                       (SELECT array_agg(a.attname) FROM unnest(c.conkey) k
                        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k) AS cols,
                       rt.relname AS reftable
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_class rt ON rt.oid = c.confrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public' AND c.contype = 'f'
                """
            )
        }

        # Tables with no PK at all — the corruption precondition.
        no_pk = [
            row.relname
            for row in conn.exec_driver_sql(
                """
                SELECT c.relname FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname='public' AND c.relkind='r'
                  AND NOT EXISTS (SELECT 1 FROM pg_constraint p
                                  WHERE p.conrelid=c.oid AND p.contype='p')
                ORDER BY 1
                """
            )
        ]

    high, low = [], []
    for diff in diffs:
        if isinstance(diff, list):
            diff = diff[0]
        kind = diff[0]
        if kind == 'add_table':
            high.append(f'missing table: {diff[1].name}')
        elif kind == 'add_column':
            high.append(f'missing column: {diff[2]}.{diff[3].name}')
        elif kind == 'add_constraint':
            c = diff[1]
            name = c.name if isinstance(c.name, str) else None
            cols = frozenset(col.name for col in c.columns)
            if (c.table.name, cols) in db_unique_column_sets:
                low.append(f'unique rule present as index, not constraint: '
                           f'{c.table.name}.{name or ",".join(sorted(cols))}')
            else:
                high.append(f'missing unique constraint: '
                            f'{c.table.name}.{name or ",".join(sorted(cols))}')
        elif kind == 'add_fk':
            fk = diff[1]
            cols = frozenset(e.parent.name for e in fk.elements)
            if (fk.table.name, cols, fk.referred_table.name) in db_fk_signatures:
                low.append(f'FK present under different name/options: '
                           f'{fk.table.name} -> {fk.referred_table.name}')
            else:
                high.append(f'missing foreign key: {fk.table.name} -> {fk.referred_table.name}')
        elif kind == 'add_index':
            ix = diff[1]
            low.append(f'missing index: {ix.table.name}.{ix.name}')
        elif kind in ('remove_index', 'remove_constraint', 'remove_fk',
                      'remove_column', 'remove_table'):
            low.append(f'{kind} (in DB, not in models): {getattr(diff[1], "name", diff[1])}')
        else:
            low.append(f'{kind}: {diff[1:]!r}'[:140])

    for t in no_pk:
        if t != 'alembic_version':
            high.append(f'TABLE HAS NO PRIMARY KEY: {t}')

    if high:
        print(f'HIGH severity drift ({len(high)}):')
        for line in sorted(high):
            print(f'  {line}')
    if low:
        print(f'\nlow severity / cosmetic ({len(low)}):')
        for line in sorted(low):
            print(f'  {line}')
    if not high and not low:
        print('schema matches models — no drift')

    sys.exit(1 if high else 0)


if __name__ == '__main__':
    main()
