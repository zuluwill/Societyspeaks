"""Classify transient database *connectivity* failures vs permanent configuration errors.

Used by:

- ``app.db_retry`` / ``app.lib.db_utils`` — retry only when safe.
- Flask error handlers — **503** only for genuine transient outages; other
  ``OperationalError`` / ``DisconnectionError`` become **500** with full logging.

``HTTP_RETRY_AFTER_DB_UNAVAILABLE_SEC`` — shared ``Retry-After`` value (seconds) for
503 responses when the database is temporarily unreachable.

Phrases are matched (case-insensitive) as substrings of ``str(exc)``.  The set is
the union of messages historically seen from psycopg2/SQLAlchemy in this codebase
(Neon pooler, Replit IPv4/IPv6, SSL drops, etc.).

Engine-level connection retry in ``config._make_retry_creator`` intentionally uses
a smaller subset (only failures possible at TCP connect time).  Do not import
``config`` from here — this module must stay cheap to import at startup.
"""

from __future__ import annotations

# Retry-After header (seconds) for transient database outage responses (503).
HTTP_RETRY_AFTER_DB_UNAVAILABLE_SEC = 10

# Lowercase substrings — single source of truth for HTTP + decorator classification.
TRANSIENT_DB_ERROR_PHRASES: tuple[str, ...] = (
    "ssl connection has been closed",
    "ssl syscall",
    "eof detected",
    "connection reset",
    "connection refused",
    "connection timed out",
    "server closed the connection",
    "connection was closed",
    "lost connection",
    "could not connect",
    "network error",
    "broken pipe",
    "terminating connection due to administrator command",
    "network is unreachable",
    # Neon serverless: compute node is waking from sleep (cold start).
    # Typically resolves within 1-3 s; always safe to retry.
    "couldn't connect to compute node",
    "compute node",
)


def is_transient_db_connectivity_error(exc: BaseException) -> bool:
    """Return True when *exc* looks like a temporary network or server-side drop."""
    msg = str(exc).lower()
    return any(phrase in msg for phrase in TRANSIENT_DB_ERROR_PHRASES)
