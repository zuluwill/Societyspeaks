import time
import logging
import functools
from sqlalchemy.exc import OperationalError, DisconnectionError

logger = logging.getLogger(__name__)

_TRANSIENT_PHRASES = (
    'server closed the connection',
    'connection was closed',
    'lost connection',
    'SSL connection has been closed',
    'could not connect to server',
    'connection timed out',
    'connection reset by peer',
    'terminating connection due to administrator command',
)


def _is_transient_db_error(exc: Exception) -> bool:
    """Return True when the exception looks like a recoverable connection drop."""
    msg = str(exc).lower()
    return any(phrase in msg for phrase in _TRANSIENT_PHRASES)


def retry_on_db_disconnect(max_attempts: int = 2, backoff_s: float = 0.2):
    """
    Decorator that retries a Flask view (or any callable) when a transient
    database disconnect is detected mid-query.

    On each transient failure the current SQLAlchemy session is rolled back and
    removed so the next attempt gets a fresh connection from the pool.
    `pool_pre_ping=True` then validates the new connection before use.

    Usage::

        @retry_on_db_disconnect()
        def my_view():
            ...

    A non-transient OperationalError (e.g. constraint violation) is re-raised
    immediately without retrying.
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
