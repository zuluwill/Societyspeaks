"""
Counter utilities for low-contention observability metrics.

Uses atomic Redis increments when REDIS_URL is configured, with optional cache
fallback so metrics never block request paths.
"""

import os
import logging
from functools import lru_cache


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_redis_client():
    redis_url = (os.getenv('REDIS_URL') or '').strip()
    if not redis_url:
        return None
    try:
        import redis
        return redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2
        )
    except Exception as e:
        logger.debug(f"Counter Redis client unavailable: {e}")
        return None


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
