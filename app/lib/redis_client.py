"""
Shared Redis connection pool.

All modules that need Redis should call ``get_client()`` from here instead
of calling ``redis.from_url()`` directly.  A persistent connection pool
means DNS is resolved only when a new connection is actually established
(first use or after a dead connection is replaced), not on every Redis
operation.  This eliminates the class of failure where a transient DNS
blip causes every Redis call to fail simultaneously.

Tunables (all overridable via env var)
--------------------------------------
- ``REDIS_SHARED_POOL_MAX_CONNECTIONS`` (default 50)
- ``REDIS_SHARED_POOL_CONNECT_TIMEOUT_SECONDS`` (default 3.0)
- ``REDIS_SHARED_POOL_OP_TIMEOUT_SECONDS``      (default 5.0)
- ``REDIS_SHARED_POOL_HEALTH_CHECK_SECONDS``    (default 30)
- ``REDIS_SHARED_POOL_RETRY_ATTEMPTS``          (default 3)
- ``REDIS_SHARED_POOL_RETRY_BACKOFF_BASE``      (default 0.1)
- ``REDIS_SHARED_POOL_RETRY_BACKOFF_CAP``       (default 1.0)

Sizing notes
------------
``max_connections`` is per-process.  With ``preload_app=True`` gunicorn
each worker inherits the pool object created in the master and resets it
in ``post_fork`` (see gunicorn_config.py), so the per-worker connection
budget is the same value.  The default 50 is right for typical traffic;
tune via env if you scale workers or worker_connections.
"""
import os
import logging
import threading

import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from redis.exceptions import ConnectionError, TimeoutError

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


_lock = threading.Lock()
_clients: dict = {}


def get_client(decode_responses: bool = True):
    """
    Return the shared Redis client backed by a persistent connection pool.

    The client (and its underlying pool) is created once per
    ``(REDIS_URL, decode_responses)`` combination and reused for the
    lifetime of the process.  Callers should not close or store the
    returned client across requests; just call ``get_client()`` again as
    needed — it returns the same cached instance via a single dict
    lookup once the pool is warm.

    Returns ``None`` if ``REDIS_URL`` is not configured or pool creation
    fails (e.g. invalid URL).  Callers MUST handle the ``None`` case.
    Failures are not cached, so a transient init error self-heals on the
    next call.
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
                max_connections=_env_int('REDIS_SHARED_POOL_MAX_CONNECTIONS', 50),
                socket_connect_timeout=_env_float('REDIS_SHARED_POOL_CONNECT_TIMEOUT_SECONDS', 3.0),
                socket_timeout=_env_float('REDIS_SHARED_POOL_OP_TIMEOUT_SECONDS', 5.0),
                socket_keepalive=True,
                health_check_interval=_env_int('REDIS_SHARED_POOL_HEALTH_CHECK_SECONDS', 30),
                retry_on_timeout=True,
            )
            client = redis.Redis(
                connection_pool=pool,
                retry=Retry(
                    ExponentialBackoff(
                        cap=_env_float('REDIS_SHARED_POOL_RETRY_BACKOFF_CAP', 1.0),
                        base=_env_float('REDIS_SHARED_POOL_RETRY_BACKOFF_BASE', 0.1),
                    ),
                    _env_int('REDIS_SHARED_POOL_RETRY_ATTEMPTS', 3),
                ),
                retry_on_error=[TimeoutError, ConnectionError],
            )
            _clients[key] = client
            logger.info(
                "Shared Redis pool initialised (decode_responses=%s, max_connections=%d)",
                decode_responses,
                pool.max_connections,
            )
            return client
        except Exception as exc:
            logger.warning("Failed to create Redis client pool: %s", exc)
            return None


def reset_clients():
    """Clear the cached client registry.

    Existing client objects continue to exist in caller variables, but
    the cache is empty so the next ``get_client()`` builds a fresh pool
    with freshly-resolved DNS.  Used by tests for a clean slate.
    """
    with _lock:
        _clients.clear()


def reset_pools_after_fork() -> int:
    """Disconnect every inherited socket and clear the cache after a fork.

    Called by gunicorn's ``post_fork`` hook so each worker opens its own
    sockets rather than sharing file descriptors with the master process
    or sibling workers (sharing those FDs corrupts the Redis protocol
    stream).  ``ConnectionPool.reset()`` closes every connection in the
    pool without waiting for in-flight commands; the next operation
    issued in this worker opens a fresh socket.

    Returns the number of pools reset (informational, for logging).
    """
    reset_count = 0
    with _lock:
        for client in _clients.values():
            pool = getattr(client, "connection_pool", None)
            if pool is None:
                continue
            try:
                pool.reset()
                reset_count += 1
            except Exception as exc:
                logger.warning("Failed to reset shared Redis pool after fork: %s", exc)
        _clients.clear()
    return reset_count
