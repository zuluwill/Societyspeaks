"""Best-effort Redis cache for dynamically rendered OG PNGs."""

from __future__ import annotations

from flask import current_app


def og_cache_get(key: str) -> bytes | None:
    try:
        from app.lib.redis_client import get_client
        client = get_client(decode_responses=False)
        if client is None:
            return None
        return client.get(key)
    except Exception:  # noqa: BLE001
        current_app.logger.warning('og cache read failed', exc_info=True)
        return None


def og_cache_set(key: str, value: bytes, *, ttl_seconds: int = 86400) -> None:
    try:
        from app.lib.redis_client import get_client
        client = get_client(decode_responses=False)
        if client is None:
            return
        client.setex(key, ttl_seconds, value)
    except Exception:  # noqa: BLE001
        current_app.logger.warning('og cache write failed', exc_info=True)
