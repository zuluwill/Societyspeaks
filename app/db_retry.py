"""
Database retry utilities for handling transient connection errors.

Provides a decorator and context manager for retrying database operations
when SSL connections are unexpectedly closed or other transient errors occur.
"""

import logging
import time
import functools
from typing import TypeVar, Callable, Any

from flask import current_app
from sqlalchemy.exc import OperationalError, DBAPIError

logger = logging.getLogger(__name__)

T = TypeVar('T')


def is_connection_error(exc: Exception) -> bool:
    """Check if exception is a transient connection error worth retrying."""
    error_msg = str(exc).lower()
    connection_indicators = [
        'ssl connection has been closed',
        'connection reset',
        'connection refused',
        'connection timed out',
        'server closed the connection',
        'lost connection',
        'could not connect',
        'network error',
        'broken pipe',
    ]
    return any(indicator in error_msg for indicator in connection_indicators)


def with_db_retry(max_attempts: int = None, delay: float = None):
    """
    Decorator for retrying database operations on transient connection errors.
    
    Handles SSL connection drops and other transient database errors by:
    1. Rolling back the failed transaction
    2. Removing the poisoned session from the thread-local
    3. Disposing the engine connection pool to force fresh connections
    4. Retrying the operation with exponential backoff
    
    Args:
        max_attempts: Maximum retry attempts (default from config)
        delay: Base delay between retries in seconds (default from config)
    
    Usage:
        @with_db_retry()
        def my_database_function():
            # database operations here
            pass
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
                    result = func(*args, **kwargs)
                    return result
                    
                except (OperationalError, DBAPIError) as e:
                    last_exception = e
                    
                    if not is_connection_error(e) or attempt == attempts:
                        logger.error(
                            f"Database error in {func.__name__} (attempt {attempt}/{attempts}): {e}"
                        )
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        raise
                    
                    logger.warning(
                        f"Transient DB error in {func.__name__} (attempt {attempt}/{attempts}): {e}. "
                        f"Retrying in {base_delay * attempt}s..."
                    )
                    
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    
                    try:
                        db.session.remove()
                    except Exception:
                        pass
                    
                    try:
                        db.engine.dispose()
                    except Exception:
                        pass
                    
                    time.sleep(base_delay * attempt)
                    
                except Exception as e:
                    logger.error(f"Unexpected error in {func.__name__}: {e}")
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    raise
                    
                finally:
                    try:
                        db.session.remove()
                    except Exception:
                        pass
            
            if last_exception:
                raise last_exception
                
        return wrapper
    return decorator


def cleanup_db_session():
    """
    Clean up database session after background job completes.
    
    Call this in a finally block for all scheduler jobs to ensure
    the session is removed and connections are returned to the pool.
    """
    from app import db
    try:
        db.session.remove()
    except Exception as e:
        logger.debug(f"Session cleanup error (safe to ignore): {e}")
