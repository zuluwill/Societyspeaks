"""SQLAlchemy engine guards for Neon / PgBouncer transaction pooling.

Neon pooler (PgBouncer ``pool_mode=transaction``) reuses Postgres backends
across clients. A session-level ``SET default_transaction_read_only = on``
(or ``connection.set_session(readonly=True)``) sticks on that backend and
causes later requests to fail with ``ReadOnlySqlTransaction`` on INSERT /
UPDATE / ``SELECT FOR UPDATE``.

These guards clear that flag on every pool checkout so a contaminated backend
cannot poison production traffic. Pair with classifying
``read-only transaction`` as transient in :mod:`app.lib.db_transient_errors`
so mid-request failures still invalidate and retry.
"""

from __future__ import annotations

import logging

from sqlalchemy import event

logger = logging.getLogger(__name__)

_GUARD_FLAG = "_societyspeaks_rw_checkout_guard"


def _force_read_write(dbapi_conn, _connection_record, _connection_proxy=None):
    """Clear session-level READ ONLY left on a pooled Postgres backend."""
    try:
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("SET default_transaction_read_only TO off")
        finally:
            cursor.close()
    except Exception:
        # Never block checkout on a best-effort hygiene statement; the
        # transient-error retry path still recovers if a write fails.
        logger.warning(
            "Failed to clear default_transaction_read_only on checkout",
            exc_info=True,
        )


def register_engine_read_write_guard(engine) -> bool:
    """Attach the checkout guard once. Returns True if newly registered.

    No-op for SQLite (tests) and for engines that already have the guard.
    """
    if engine is None:
        return False
    try:
        url = str(getattr(engine, "url", "") or "")
    except Exception:
        url = ""
    if "sqlite" in url:
        return False
    if getattr(engine, _GUARD_FLAG, False):
        return False

    event.listen(engine, "checkout", _force_read_write)
    setattr(engine, _GUARD_FLAG, True)
    logger.info("Registered Neon/PgBouncer read-write checkout guard on DB engine")
    return True
