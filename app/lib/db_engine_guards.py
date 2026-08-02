"""SQLAlchemy engine guards for Neon / PgBouncer transaction pooling.

Neon pooler (PgBouncer ``pool_mode=transaction``) reuses Postgres backends
across clients. A session-level ``SET default_transaction_read_only = on``
(or ``connection.set_session(readonly=True)``) sticks on that backend and
causes later requests to fail with ``ReadOnlySqlTransaction`` on INSERT /
UPDATE / ``SELECT FOR UPDATE``.

BEST-EFFORT, NOT A GUARANTEE. This checkout guard clears the flag on whichever
backend serves the checkout statement. Under transaction pooling a backend is
pinned only for the duration of a transaction, so the backend that later serves
a write in the same SQLAlchemy connection may be a *different*, still-poisoned
one. The guard therefore cleans the pool *gradually* as connections cycle; it
does not guarantee any single write runs read-write.

The reliable controls, in order:

1. Prevention (primary): never run session-level READ ONLY against the
   ``-pooler`` URL. Ops/investigation scripts must use a direct Neon URL or a
   scoped ``BEGIN TRANSACTION READ ONLY``. See OPS.md.
2. Self-healing call sites: hot paths (daily-send loop, scheduler phases,
   click tracking) already catch, roll back, and recover via claim-release +
   catch-up / next-tick retry, so a contaminated window degrades transiently.
3. Transient classification: ``read-only transaction`` is transient in
   :mod:`app.lib.db_transient_errors`; retry decorators invalidate the poisoned
   connection before retrying so the next attempt gets a fresh backend.

For a hard per-write guarantee (if prevention ever proves insufficient) the
only pooling-safe mechanism is a per-transaction ``SET LOCAL
default_transaction_read_only = off`` on a ``begin`` event — deliberately not
enabled here: it adds a round-trip per transaction and must be verified against
the live pooler first.
"""

from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.exc import DisconnectionError

from app.lib.db_transient_errors import is_transient_db_connectivity_error

logger = logging.getLogger(__name__)

_GUARD_FLAG = "_societyspeaks_rw_checkout_guard"


def _force_read_write(dbapi_conn, connection_record, _connection_proxy=None):
    """Clear session-level READ ONLY left on a pooled Postgres backend.

    If the socket is already dead (SSL tear-down / closed), invalidate it and
    raise ``DisconnectionError`` so the pool retries checkout with a fresh
    connection instead of handing the corpse to the request.
    """
    try:
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("SET default_transaction_read_only TO off")
        finally:
            cursor.close()
    except Exception as exc:
        # Never block checkout on a best-effort hygiene statement for soft
        # failures; but dead sockets must leave the pool immediately.
        dead = is_transient_db_connectivity_error(exc) or (
            "already closed" in str(exc).lower()
        )
        logger.warning(
            "Failed to clear default_transaction_read_only on checkout%s",
            " — discarding dead connection" if dead else "",
            exc_info=not dead,
        )
        if dead:
            try:
                connection_record.invalidate(exc)
            except Exception:
                pass
            raise DisconnectionError(
                "Checkout hygiene failed on a dead connection",
                {},
                exc,
            ) from exc


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
