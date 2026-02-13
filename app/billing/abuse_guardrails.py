"""
Lightweight abuse guardrails for cost protection.

These are NOT plan limits — they're safety controls to prevent runaway costs.
Plan limits (max_sources, max_briefs) are handled by enforcement.py.

Guardrails:
1. Per-user generation rate limits (X runs/hour, Y/day)
2. Upload caps (file size + total files per day)
3. Queue/concurrency limits per user
4. Token spend monitoring and alerts
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get('REDIS_URL')

RATE_LIMIT_PREFIX = 'abuse:'

GENERATION_LIMITS = {
    'per_hour': 5,
    'per_day': 20,
}

UPLOAD_LIMITS = {
    'max_file_size_mb': 10,
    'max_uploads_per_day': 20,
    'max_total_storage_mb_per_user': 500,
}

CONCURRENCY_LIMITS = {
    'max_concurrent_jobs': 2,
    'max_queued_jobs': 5,
}

TOKEN_SPEND_THRESHOLDS = {
    'warn_per_day_usd': 2.0,
    'block_per_day_usd': 10.0,
}


def _get_redis():
    """Get Redis client for rate limiting."""
    if not REDIS_URL:
        return None
    try:
        import redis
        return redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning(f"Redis unavailable for abuse guardrails: {e}")
        return None


def check_generation_rate_limit(user_id: int) -> Tuple[bool, Optional[str]]:
    """
    Check if user has exceeded generation rate limits.

    Returns:
        (allowed, error_message) - allowed=True if within limits
    """
    client = _get_redis()
    if not client:
        return True, None

    try:
        now = datetime.utcnow()
        hour_key = f"{RATE_LIMIT_PREFIX}gen:{user_id}:h:{now.strftime('%Y%m%d%H')}"
        day_key = f"{RATE_LIMIT_PREFIX}gen:{user_id}:d:{now.strftime('%Y%m%d')}"

        hourly_count = int(client.get(hour_key) or 0)
        daily_count = int(client.get(day_key) or 0)

        if hourly_count >= GENERATION_LIMITS['per_hour']:
            logger.warning(f"User {user_id} hit hourly generation limit ({hourly_count}/{GENERATION_LIMITS['per_hour']})")
            return False, f"You've generated {hourly_count} briefs this hour. Please wait a bit before generating more."

        if daily_count >= GENERATION_LIMITS['per_day']:
            logger.warning(f"User {user_id} hit daily generation limit ({daily_count}/{GENERATION_LIMITS['per_day']})")
            return False, f"You've reached the daily generation limit ({GENERATION_LIMITS['per_day']} briefs). Limits reset at midnight UTC."

        return True, None
    except Exception as e:
        logger.error(f"Error checking generation rate limit: {e}")
        return True, None


def record_generation(user_id: int):
    """Record a brief generation for rate limiting."""
    client = _get_redis()
    if not client:
        return

    try:
        now = datetime.utcnow()
        hour_key = f"{RATE_LIMIT_PREFIX}gen:{user_id}:h:{now.strftime('%Y%m%d%H')}"
        day_key = f"{RATE_LIMIT_PREFIX}gen:{user_id}:d:{now.strftime('%Y%m%d')}"

        pipe = client.pipeline()
        pipe.incr(hour_key)
        pipe.expire(hour_key, 3600)
        pipe.incr(day_key)
        pipe.expire(day_key, 86400)
        pipe.execute()
    except Exception as e:
        logger.error(f"Error recording generation: {e}")


def check_upload_rate_limit(user_id: int, file_size_bytes: int = 0) -> Tuple[bool, Optional[str]]:
    """
    Check if user has exceeded upload rate limits.

    Args:
        user_id: User ID
        file_size_bytes: Size of file being uploaded

    Returns:
        (allowed, error_message)
    """
    max_size = UPLOAD_LIMITS['max_file_size_mb'] * 1024 * 1024
    if file_size_bytes > max_size:
        return False, f"File too large. Maximum file size is {UPLOAD_LIMITS['max_file_size_mb']}MB."

    client = _get_redis()
    if not client:
        return True, None

    try:
        now = datetime.utcnow()
        day_key = f"{RATE_LIMIT_PREFIX}upload:{user_id}:d:{now.strftime('%Y%m%d')}"

        daily_count = int(client.get(day_key) or 0)
        if daily_count >= UPLOAD_LIMITS['max_uploads_per_day']:
            logger.warning(f"User {user_id} hit daily upload limit ({daily_count}/{UPLOAD_LIMITS['max_uploads_per_day']})")
            return False, f"You've uploaded {daily_count} files today. Limit resets at midnight UTC."

        return True, None
    except Exception as e:
        logger.error(f"Error checking upload rate limit: {e}")
        return True, None


def record_upload(user_id: int, file_size_bytes: int = 0):
    """Record a file upload for rate limiting."""
    client = _get_redis()
    if not client:
        return

    try:
        now = datetime.utcnow()
        day_key = f"{RATE_LIMIT_PREFIX}upload:{user_id}:d:{now.strftime('%Y%m%d')}"

        pipe = client.pipeline()
        pipe.incr(day_key)
        pipe.expire(day_key, 86400)
        pipe.execute()
    except Exception as e:
        logger.error(f"Error recording upload: {e}")


def check_user_concurrency(user_id: int) -> Tuple[bool, Optional[str]]:
    """
    Check if user has too many concurrent/queued generation jobs.

    Returns:
        (allowed, error_message)
    """
    client = _get_redis()
    if not client:
        return True, None

    try:
        active_key = f"{RATE_LIMIT_PREFIX}active:{user_id}"
        active_count = int(client.get(active_key) or 0)

        if active_count >= CONCURRENCY_LIMITS['max_concurrent_jobs']:
            logger.warning(f"User {user_id} has {active_count} active jobs (limit: {CONCURRENCY_LIMITS['max_concurrent_jobs']})")
            return False, "You already have briefs being generated. Please wait for them to finish before starting more."

        queued_key = f"{RATE_LIMIT_PREFIX}queued:{user_id}"
        queued_count = int(client.get(queued_key) or 0)

        if queued_count >= CONCURRENCY_LIMITS['max_queued_jobs']:
            logger.warning(f"User {user_id} has {queued_count} queued jobs (limit: {CONCURRENCY_LIMITS['max_queued_jobs']})")
            return False, "You have too many briefs queued. Please wait for some to complete."

        return True, None
    except Exception as e:
        logger.error(f"Error checking user concurrency: {e}")
        return True, None


def increment_user_jobs(user_id: int, job_type: str = 'queued'):
    """Increment user's active/queued job count."""
    client = _get_redis()
    if not client:
        return

    try:
        key = f"{RATE_LIMIT_PREFIX}{job_type}:{user_id}"
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 3600)
        pipe.execute()
    except Exception as e:
        logger.error(f"Error incrementing user jobs: {e}")


def decrement_user_jobs(user_id: int, job_type: str = 'queued'):
    """Decrement user's active/queued job count."""
    client = _get_redis()
    if not client:
        return

    try:
        key = f"{RATE_LIMIT_PREFIX}{job_type}:{user_id}"
        current = int(client.get(key) or 0)
        if current > 0:
            client.decr(key)
    except Exception as e:
        logger.error(f"Error decrementing user jobs: {e}")


def record_token_spend(user_id: int, tokens_used: int, cost_usd: float, model: str = 'unknown'):
    """
    Record token spend for monitoring and alerting.

    Args:
        user_id: User ID
        tokens_used: Total tokens (input + output)
        cost_usd: Estimated cost in USD
        model: Model name used
    """
    client = _get_redis()
    if not client:
        return

    try:
        now = datetime.utcnow()
        day_key = f"{RATE_LIMIT_PREFIX}spend:{user_id}:d:{now.strftime('%Y%m%d')}"

        pipe = client.pipeline()
        pipe.incrbyfloat(day_key, cost_usd)
        pipe.expire(day_key, 172800)
        pipe.execute()

        daily_spend = float(client.get(day_key) or 0)

        if daily_spend >= TOKEN_SPEND_THRESHOLDS['block_per_day_usd']:
            logger.error(
                f"ALERT: User {user_id} daily token spend ${daily_spend:.2f} EXCEEDS block threshold "
                f"(${TOKEN_SPEND_THRESHOLDS['block_per_day_usd']:.2f}). "
                f"Latest: {tokens_used} tokens, ${cost_usd:.4f}, model={model}"
            )
        elif daily_spend >= TOKEN_SPEND_THRESHOLDS['warn_per_day_usd']:
            logger.warning(
                f"ALERT: User {user_id} daily token spend ${daily_spend:.2f} exceeds warning threshold "
                f"(${TOKEN_SPEND_THRESHOLDS['warn_per_day_usd']:.2f}). "
                f"Latest: {tokens_used} tokens, ${cost_usd:.4f}, model={model}"
            )
    except Exception as e:
        logger.error(f"Error recording token spend: {e}")


def check_token_spend_limit(user_id: int) -> Tuple[bool, Optional[str]]:
    """
    Check if user has exceeded daily token spend threshold.

    Returns:
        (allowed, error_message)
    """
    client = _get_redis()
    if not client:
        return True, None

    try:
        now = datetime.utcnow()
        day_key = f"{RATE_LIMIT_PREFIX}spend:{user_id}:d:{now.strftime('%Y%m%d')}"

        daily_spend = float(client.get(day_key) or 0)

        if daily_spend >= TOKEN_SPEND_THRESHOLDS['block_per_day_usd']:
            logger.error(f"User {user_id} blocked: daily spend ${daily_spend:.2f} exceeds ${TOKEN_SPEND_THRESHOLDS['block_per_day_usd']:.2f}")
            return False, "Your account has reached the daily processing limit. This resets at midnight UTC. If you need more capacity, please contact support."

        return True, None
    except Exception as e:
        logger.error(f"Error checking token spend limit: {e}")
        return True, None


def get_user_abuse_stats(user_id: int) -> Dict[str, Any]:
    """
    Get current abuse guardrail stats for a user (for admin dashboard).

    Returns dict with current usage vs limits.
    """
    client = _get_redis()
    if not client:
        return {'redis_available': False}

    try:
        now = datetime.utcnow()
        hour_key = f"{RATE_LIMIT_PREFIX}gen:{user_id}:h:{now.strftime('%Y%m%d%H')}"
        day_gen_key = f"{RATE_LIMIT_PREFIX}gen:{user_id}:d:{now.strftime('%Y%m%d')}"
        day_upload_key = f"{RATE_LIMIT_PREFIX}upload:{user_id}:d:{now.strftime('%Y%m%d')}"
        active_key = f"{RATE_LIMIT_PREFIX}active:{user_id}"
        queued_key = f"{RATE_LIMIT_PREFIX}queued:{user_id}"
        spend_key = f"{RATE_LIMIT_PREFIX}spend:{user_id}:d:{now.strftime('%Y%m%d')}"

        return {
            'redis_available': True,
            'generation': {
                'hourly': int(client.get(hour_key) or 0),
                'hourly_limit': GENERATION_LIMITS['per_hour'],
                'daily': int(client.get(day_gen_key) or 0),
                'daily_limit': GENERATION_LIMITS['per_day'],
            },
            'uploads': {
                'daily': int(client.get(day_upload_key) or 0),
                'daily_limit': UPLOAD_LIMITS['max_uploads_per_day'],
            },
            'concurrency': {
                'active_jobs': int(client.get(active_key) or 0),
                'max_concurrent': CONCURRENCY_LIMITS['max_concurrent_jobs'],
                'queued_jobs': int(client.get(queued_key) or 0),
                'max_queued': CONCURRENCY_LIMITS['max_queued_jobs'],
            },
            'token_spend': {
                'daily_usd': float(client.get(spend_key) or 0),
                'warn_threshold_usd': TOKEN_SPEND_THRESHOLDS['warn_per_day_usd'],
                'block_threshold_usd': TOKEN_SPEND_THRESHOLDS['block_per_day_usd'],
            },
        }
    except Exception as e:
        logger.error(f"Error getting abuse stats: {e}")
        return {'redis_available': False, 'error': str(e)}
