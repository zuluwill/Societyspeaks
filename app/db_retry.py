"""
Database retry utilities for handling transient connection errors.

Provides a decorator and helper for retrying database operations when
SSL connections are unexpectedly closed or other transient network
errors occur.

Architecture note
-----------------
Since config.py installs an engine-level ``creator`` function that already
retries transient errors (``network is unreachable``, timeouts) when
establishing *new* physical connections, this module covers a different
failure mode: errors that occur *mid-request*, after a connection has been
successfully checked out, such as:

- The database server closes an idle connection mid-query.
- An SSL session expires between the checkout and the first execute.
- A network blip kills an in-flight transaction.

``with_db_retry`` rolls back and discards the poisoned session so SQLAlchemy
will request a fresh connection on the next attempt.  It does NOT call
``db.engine.dispose()`` — that would nuke every connection in the shared
pool, punishing all concurrent requests for one failure.
"""

import logging
import time
import functools
from typing import TypeVar, Callable

from flask import current_app
from sqlalchemy.exc import OperationalError, DBAPIError
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Canonical set of substrings that identify a *transient* connection error
# (one that is safe to retry).  Keep in sync with app/lib/db_utils.py.
_TRANSIENT_INDICATORS = (
    'ssl connection has been closed',
    'ssl syscall',
    'eof detected',
    'connection reset',
    'connection refused',
    'connection timed out',
    'server closed the connection',
    'lost connection',
    'could not connect',
    'network error',
    'broken pipe',
    # DNS returned only IPv6 addresses in an IPv4-only deployment environment.
    # Added after Sentry issue #118342621 (Neon pooler + Replit).
    'network is unreachable',
)


def is_connection_error(exc: Exception) -> bool:
    """Return True when ``exc`` is a transient connection error worth retrying.

    Non-transient errors (IntegrityError, programming errors, auth failures)
    return False so they propagate immediately without burning retry budget.
    """
    return any(indicator in str(exc).lower() for indicator in _TRANSIENT_INDICATORS)


def with_db_retry(max_attempts: int = None, delay: float = None):
    """Decorator that retries a function on transient database connection errors.

    On each transient failure:
    1. Rolls back the failed transaction.
    2. Removes the poisoned session so SQLAlchemy issues a fresh checkout.
    3. Waits with linear backoff before retrying.

    The engine-level ``creator`` in config.py handles retry at the *connection
    establishment* layer; this decorator handles retry at the *query execution*
    layer.  They complement each other — do not duplicate by calling
    ``db.engine.dispose()`` here, which would drop all pool connections and
    degrade concurrent requests.

    Args:
        max_attempts: Maximum total attempts (default from ``DB_RETRY_ATTEMPTS``
                      config key, itself defaulting to 3).
        delay: Base delay in seconds between attempts (default from
               ``DB_RETRY_DELAY`` config key, itself defaulting to 1).

    Usage::

        @with_db_retry()
        def my_db_function():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            from app import db

            attempts = max_attempts or current_app.config.get('DB_RETRY_ATTEMPTS', 3)
            base_delay = delay or current_app.config.get('DB_RETRY_DELAY', 1)

            last_exception = None

            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)

                except (OperationalError, DBAPIError) as e:
                    last_exception = e

                    if not is_connection_error(e) or attempt == attempts:
                        logger.error(
                            "Database error in %s (attempt %d/%d): %s",
                            func.__name__, attempt, attempts, e,
                        )
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        raise

                    logger.warning(
                        "Transient DB error in %s (attempt %d/%d): %s — retrying in %.1fs",
                        func.__name__, attempt, attempts, e, base_delay * attempt,
                    )
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    try:
                        db.session.remove()
                    except Exception:
                        pass
                    # NOTE: db.engine.dispose() is intentionally NOT called here.
                    # Disposing the engine drops every connection in the shared pool
                    # and would cascade failures to all concurrent requests.
                    # The engine-level creator (config.py) retries new connections
                    # automatically; session.remove() is sufficient for mid-request drops.
                    time.sleep(base_delay * attempt)

                except HTTPException:
                    raise

                except Exception as e:
                    logger.error("Unexpected error in %s: %s", func.__name__, e)
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    raise

            # Only reached if attempts == 0 (shouldn't happen) or all retries
            # exhausted via the loop — last_exception is always set in that case.
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def cleanup_db_session():
    """Remove the SQLAlchemy session at the end of a background job.

    Call this in a ``finally`` block for scheduler jobs and worker functions
    to return the underlying connection to the pool and avoid session leaks
    between job executions.
    """
    from app import db
    try:
        db.session.remove()
    except Exception as e:
        logger.debug("Session cleanup error (safe to ignore): %s", e)
