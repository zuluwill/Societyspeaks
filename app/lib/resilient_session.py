"""
Resilient Redis session interface for Flask-Session.

Flask-Session's RedisSessionInterface lets Redis exceptions (TimeoutError,
ConnectionError, etc.) propagate uncaught through open_session / save_session,
which turns a transient Redis blip into a 500 for every concurrent user.

This module subclasses RedisSessionInterface and wraps the three internal
Redis I/O methods so that any exception:
  - is logged at WARNING level (with exc_info for full traceback in Sentry)
  - is silenced so the request continues with a degraded-but-functional session:
      * open_session  → empty session (user appears logged-out for this request)
      * save_session  → no-op (session changes are discarded)
      * delete (logout) → no-op (session data stays in Redis until TTL expires)

This is intentionally "fail-open": a transient Redis timeout should never
cause a 500 error on a public-facing page view.
"""

import logging
from typing import Optional

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from flask_session.redis import RedisSessionInterface

logger = logging.getLogger(__name__)

_REDIS_ERRORS = (RedisTimeoutError, RedisConnectionError, OSError, Exception)


class ResilientRedisSessionInterface(RedisSessionInterface):
    """
    Drop-in replacement for RedisSessionInterface that catches all Redis
    errors and degrades gracefully instead of raising a 500.
    """

    def _retrieve_session_data(self, store_id: str) -> Optional[dict]:
        try:
            return super()._retrieve_session_data(store_id)
        except Exception as exc:
            logger.warning(
                "Redis session read failed for store_id=%s — serving empty session: %s",
                store_id,
                exc,
                exc_info=True,
            )
            return None

    def _delete_session(self, store_id: str) -> None:
        try:
            super()._delete_session(store_id)
        except Exception as exc:
            logger.warning(
                "Redis session delete failed for store_id=%s — TTL expiry will clean up: %s",
                store_id,
                exc,
                exc_info=True,
            )

    def _upsert_session(self, session_lifetime, session, store_id: str) -> None:
        try:
            super()._upsert_session(session_lifetime, session, store_id)
        except Exception as exc:
            logger.warning(
                "Redis session save failed for store_id=%s — session changes discarded: %s",
                store_id,
                exc,
                exc_info=True,
            )
