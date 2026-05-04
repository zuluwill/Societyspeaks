"""
Counter utilities for low-contention observability metrics.

Uses atomic Redis increments when REDIS_URL is configured, with optional cache
fallback so metrics never block request paths.
"""

import logging


logger = logging.getLogger(__name__)


def _get_redis_client():
    from app.lib.redis_client import get_client
    return get_client(decode_responses=True)


def increment_counter(key: str, ttl_seconds: int = 3600, fallback_cache=None):
    """
    Increment a counter and return the new integer value.

    - Primary path: Redis INCR + EXPIRE (atomic increment).
    - Fallback path: Flask cache get/set (best effort, non-atomic).
    """
    client = _get_redis_client()
    if client:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            if ttl_seconds and ttl_seconds > 0:
                pipe.expire(key, ttl_seconds)
            result = pipe.execute()
            return int(result[0])
        except Exception as e:
            logger.debug(f"Redis counter increment failed for key={key}: {e}")

    if fallback_cache is not None:
        try:
            next_value = int(fallback_cache.get(key) or 0) + 1
            fallback_cache.set(key, next_value, timeout=ttl_seconds)
            return next_value
        except Exception as e:
            logger.debug(f"Fallback cache increment failed for key={key}: {e}")
    return None
