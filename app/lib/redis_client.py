"""
Shared Redis connection pool.

All modules that need Redis should call get_client() from here instead of
calling redis.from_url() directly.  A persistent connection pool means DNS
is resolved only when a new connection is actually established (i.e. on first
use or after a dead connection is replaced), not on every single Redis
operation.  This eliminates the class of errors where a transient DNS blip
causes every Redis call to fail simultaneously.
"""
import os
import logging
import threading

import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from redis.exceptions import ConnectionError, TimeoutError

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_clients: dict = {}


def get_client(decode_responses: bool = True):
    """
    Return the shared Redis client backed by a persistent connection pool.

    The client (and its underlying pool) is created once per
    (REDIS_URL, decode_responses) combination and reused for the lifetime
    of the process.  Callers should not close or store the returned client
    across requests; just call get_client() again as needed — it returns
    the same cached instance instantly.

    Returns None if REDIS_URL is not configured.

    Args:
        decode_responses: When True (default) responses are decoded to str.
                          When False responses are returned as bytes (use for
                          call sites that already do their own .decode()).
    """
    url = (os.environ.get('REDIS_URL') or '').strip()
    if not url:
        return None

    key = (url, decode_responses)
    client = _clients.get(key)
    if client is not None:
        return client

    with _lock:
        client = _clients.get(key)
        if client is not None:
            return client
        try:
            pool = redis.ConnectionPool.from_url(
                url,
                decode_responses=decode_responses,
                max_connections=50,
                socket_connect_timeout=3.0,
                socket_timeout=5.0,
                socket_keepalive=True,
                health_check_interval=30,
                retry_on_timeout=True,
            )
            client = redis.Redis(
                connection_pool=pool,
                retry=Retry(ExponentialBackoff(cap=1.0, base=0.1), 3),
                retry_on_error=[TimeoutError, ConnectionError],
            )
            _clients[key] = client
            logger.debug("Redis connection pool created (decode_responses=%s)", decode_responses)
            return client
        except Exception as exc:
            logger.warning("Failed to create Redis client pool: %s", exc)
            return None


def reset_clients():
    """Reset all cached clients.  Intended for use in tests only."""
    with _lock:
        _clients.clear()
