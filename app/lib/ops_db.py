"""Direct (non-pooler) DB connections for ops / investigation scripts.

Root-cause guardrail for the Neon/PgBouncer read-only contamination class.
Session-level state run against the ``-pooler`` endpoint — ``set_session(
readonly=True)``, ``SET default_transaction_read_only``, ``SET SESSION ...``,
temp tables, session advisory locks, ``LISTEN``/``NOTIFY`` — sticks on a shared
PgBouncer backend and poisons later production requests (the 2026-07-14
``ReadOnlySqlTransaction`` burst).

Any script that opens a raw psycopg2 connection — especially one that changes
session state — MUST use :func:`direct_db_connection` so it lands on a
dedicated direct endpoint, never a shared pooler backend. It fails closed:
if it can only resolve a pooler URL it raises rather than risk contamination.

Example::

    from app.lib.ops_db import direct_db_connection

    with direct_db_connection() as conn:          # autocommit, direct endpoint
        cur = conn.cursor()
        cur.execute("SET default_transaction_read_only TO on")  # safe here
        cur.execute("SELECT ...")
"""

from __future__ import annotations

import os
import re

_POOLER_MARKER = '-pooler.'
# Neon pooler host: ep-<id>-pooler.<region>.neon.tech → drop the -pooler segment.
_NEON_POOLER_RE = re.compile(r'(ep-[a-z0-9-]+)-pooler(\.[\w.-]+\.neon\.tech)')


class PoolerUrlError(RuntimeError):
    """Raised when only a pooler URL is available for a direct-only operation."""


def to_direct_neon_url(url: str | None) -> str | None:
    """Strip Neon's ``-pooler`` host segment so the URL targets the direct endpoint.

    Non-Neon URLs (and already-direct ones) are returned unchanged.
    """
    if not url:
        return url
    return _NEON_POOLER_RE.sub(r'\1\2', url)


def resolve_direct_db_url(url: str | None = None) -> str:
    """Return a direct (non-pooler) DB URL for ops use, or raise ``PoolerUrlError``.

    Preference order: explicit ``NEON_DIRECT_DATABASE_URL`` / ``DATABASE_URL_DIRECT``
    → the supplied ``url`` → ``NEON_OWNER_DATABASE_URL`` / ``DATABASE_URL`` /
    ``NEON_DATABASE_URL`` — always de-poolered before use. Fails closed if the
    result still looks like a pooler endpoint.
    """
    candidate = (
        os.getenv('NEON_DIRECT_DATABASE_URL')
        or os.getenv('DATABASE_URL_DIRECT')
        or url
        or os.getenv('NEON_OWNER_DATABASE_URL')
        or os.getenv('DATABASE_URL')
        or os.getenv('NEON_DATABASE_URL')
    )
    if not candidate:
        raise PoolerUrlError(
            'No database URL available to resolve a direct connection '
            '(set NEON_DIRECT_DATABASE_URL to a non-pooler endpoint).'
        )
    direct = to_direct_neon_url(candidate) or ''
    if _POOLER_MARKER in direct:
        raise PoolerUrlError(
            'Refusing a pooler URL for a direct-only operation. Session-level '
            'state on the pooler poisons shared backends — set '
            'NEON_DIRECT_DATABASE_URL to a direct (non-pooler) Neon endpoint.'
        )
    return direct


class direct_db_connection:  # noqa: N801 — context-manager, used like a function
    """Context manager yielding a psycopg2 connection to the DIRECT endpoint.

    Safe for session-level state (readonly probes, temp tables, advisory locks)
    because it never touches a shared pooler backend. Autocommit by default so a
    stray open transaction can't pin a backend.
    """

    def __init__(self, *, autocommit: bool = True, connect_timeout: int = 15,
                 url: str | None = None):
        self._autocommit = autocommit
        self._connect_timeout = connect_timeout
        self._url = url
        self._conn = None

    def __enter__(self):
        import psycopg2
        self._conn = psycopg2.connect(
            resolve_direct_db_url(self._url),
            connect_timeout=self._connect_timeout,
        )
        self._conn.autocommit = self._autocommit
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        try:
            self._conn.close()
        except Exception:
            pass
        return False
