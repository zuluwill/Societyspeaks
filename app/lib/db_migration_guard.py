"""
Database migration safety for multi-service deploys.

Two complementary guards:

``assert_db_at_head`` — fail fast when the database revision lags Alembic head.
Both web and scheduler run ``flask db upgrade`` in ``preDeployCommand``, but a
worker can still restart against a stale schema (preDeploy failed, a service
was rolled independently, someone restarted a worker by hand). Code expecting
``brief_item.weekly_development`` before ``wk001`` lands would 500 on *every*
``BriefItem`` query — SQLAlchemy selects all mapped columns — taking down daily
brief sends, not just the weekly. Refusing to start is the loud failure.

``acquire_migration_lock`` — serialise concurrent ``flask db upgrade`` runs.
Called from ``migrations/env.py``. Because preDeploy is declared on two
services, a blueprint deploy can run both upgrades at once; without a lock both
read ``alembic_version``, both attempt the same DDL, and the loser fails with
"column already exists", failing that service's deploy.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Iterable, Optional, Set

logger = logging.getLogger(__name__)

# Stable, arbitrary 64-bit key. Every process running `flask db upgrade`
# against this database must use the same value for the lock to serialise them.
MIGRATION_ADVISORY_LOCK_KEY = 4048202576565135872


def acquire_migration_lock(connection) -> bool:
    """Take the migration advisory lock on PostgreSQL. Returns True if taken.

    ``pg_advisory_xact_lock`` blocks until the lock is free and is released
    automatically when the surrounding transaction commits or rolls back, so a
    crashed or killed migration can never strand it — no manual recovery.

    No-ops on other backends: SQLite (tests, local) has no cross-process
    upgrade concurrency to guard, and the statement is Postgres-specific.
    """
    import sqlalchemy as sa

    if connection.dialect.name != 'postgresql':
        return False

    connection.execute(
        sa.text('SELECT pg_advisory_xact_lock(:key)'),
        {'key': MIGRATION_ADVISORY_LOCK_KEY},
    )
    logger.info('Acquired migration advisory lock')
    return True


def _alembic_heads(script_dir) -> Set[str]:
    heads = set(script_dir.get_heads())
    if not heads:
        raise RuntimeError("Alembic script has no head revision")
    return heads


def _current_db_revision(connection) -> Optional[str]:
    from alembic.runtime.migration import MigrationContext

    context = MigrationContext.configure(connection)
    return context.get_current_revision()


def assert_db_at_head(app, *, role: str = 'worker') -> None:
    """
    Exit the process when ``DATABASE_URL`` is not at Alembic head.

    Set ``SKIP_DB_MIGRATION_GUARD=1`` only for local dev when intentionally
    running against an older schema (not supported in production).
    """
    if os.environ.get('SKIP_DB_MIGRATION_GUARD', '').strip() in ('1', 'true', 'yes'):
        logger.warning("SKIP_DB_MIGRATION_GUARD set — skipping DB revision check")
        return

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app import db

    migrations_dir = os.path.join(app.root_path, '..', 'migrations')
    config = Config(os.path.join(migrations_dir, 'alembic.ini'))
    config.set_main_option('script_location', migrations_dir)
    script = ScriptDirectory.from_config(config)
    heads = _alembic_heads(script)

    with app.app_context():
        with db.engine.connect() as connection:
            current = _current_db_revision(connection)

    if current in heads:
        logger.info("DB revision %s matches Alembic head (%s)", current, ', '.join(sorted(heads)))
        return

    message = (
        f"{role} refusing to start: database revision {current!r} is not at Alembic head "
        f"{_format_heads(heads)}. Run `flask db upgrade` on the web service (or manually) "
        f"before restarting workers."
    )
    logger.critical(message)
    sys.exit(1)


def _format_heads(heads: Iterable[str]) -> str:
    items = sorted(heads)
    if len(items) == 1:
        return repr(items[0])
    return repr(items)
