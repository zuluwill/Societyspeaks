"""
Request-level database retry decorator for Flask views.

Two-layer retry architecture
-----------------------------
Layer 1 — Engine (config.py ``_make_retry_creator``):
    Retries the *establishment* of a new physical DB connection.  Fires when
    SQLAlchemy needs a fresh socket — e.g. pool recycle, pool expansion under
    load, or process startup.  Covers every route, job, and worker process
    without requiring any per-route decoration.

Layer 2 — Request (``retry_on_db_disconnect`` in this module):
    Retries an *entire view function* when a connection that was already
    checked out from the pool dies mid-request — e.g. the database server
    drops an idle connection between the checkout and the first execute.  Must
    be applied as a decorator to individual views.

The two layers are complementary: Layer 1 never sees mid-request drops and
Layer 2 never sees new-connection failures.  Neither calls
``db.engine.dispose()`` — that nukes the entire shared pool and would degrade
all concurrent requests for a single failure.

Canonical transient phrases live in :mod:`app.lib.db_transient_errors`.
"""

import time
import logging
import functools
from sqlalchemy.exc import OperationalError, DisconnectionError

from app.lib.db_transient_errors import is_transient_db_connectivity_error

logger = logging.getLogger(__name__)


def _is_transient_db_error(exc: Exception) -> bool:
    """Return True when ``exc`` is a recoverable connection drop worth retrying."""
    return is_transient_db_connectivity_error(exc)


def retry_on_db_disconnect(max_attempts: int = 2, backoff_s: float = 0.2):
    """Decorator that retries a Flask view on a mid-request DB disconnect.

    On each transient failure the current SQLAlchemy session is rolled back and
    removed so the next attempt gets a fresh connection from the pool.
    ``pool_pre_ping=True`` then validates the new connection before use.

    Non-transient ``OperationalError`` (constraint violations, programming
    errors, auth failures) is re-raised immediately without retrying.

    See module docstring for the two-layer retry architecture.

    Usage::

        @retry_on_db_disconnect()
        def my_view():
            ...
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            from app import db  # local import avoids circular imports at module load
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except (OperationalError, DisconnectionError) as exc:
                    if not _is_transient_db_error(exc):
                        raise
                    last_exc = exc
                    logger.warning(
                        "Transient DB disconnect on attempt %d/%d for %s: %s — retrying",
                        attempt, max_attempts, fn.__qualname__, exc,
                    )
                    try:
                        db.session.rollback()
                        db.session.remove()
                    except Exception:
                        pass
                    if attempt < max_attempts:
                        time.sleep(backoff_s * attempt)
            raise last_exc
        return wrapper
    return decorator
