"""Telemetry and ops paging when unsolicited content is blocked."""
from __future__ import annotations

import logging

from flask import current_app, has_request_context, request

logger = logging.getLogger(__name__)

_REDIS_WINDOW_KEY = 'content_spam_blocks:15m'
_REDIS_WINDOW_SECONDS = 15 * 60


def record_content_spam_block(
    *,
    context: str,
    score: int,
    reasons: tuple[str, ...] | list[str],
    discussion_id: int | None = None,
) -> None:
    """Log, analytics, PostHog, and page ops if blocks spike. Never raises."""
    try:
        _record_content_spam_block_inner(
            context=context,
            score=score,
            reasons=reasons,
            discussion_id=discussion_id,
        )
    except Exception:
        logger.warning('content_spam telemetry failed', exc_info=True)


def _record_content_spam_block_inner(*, context, score, reasons, discussion_id):
    reason_list = list(reasons)
    logger.warning(
        'content_spam_blocked context=%s score=%s reasons=%s discussion_id=%s',
        context,
        score,
        ','.join(reason_list),
        discussion_id,
    )

    try:
        from app.analytics.events import record_event
        record_event(
            'content_spam_blocked',
            commit=True,
            discussion_id=discussion_id,
            source=context,
            event_metadata={'score': score, 'reasons': reason_list},
        )
    except Exception:
        logger.warning('content_spam_blocked analytics write failed', exc_info=True)

    try:
        import posthog
        from app.lib.posthog_utils import resolve_request_distinct_id, safe_posthog_capture
        if posthog and getattr(posthog, 'project_api_key', None):
            distinct_id = resolve_request_distinct_id(anon_fallback='content-spam')
            safe_posthog_capture(
                posthog_client=posthog,
                distinct_id=distinct_id,
                event='content_spam_blocked',
                properties={
                    'context': context,
                    'score': score,
                    'reasons': reason_list,
                    'discussion_id': discussion_id,
                },
            )
    except Exception:
        logger.warning('content_spam_blocked PostHog capture failed', exc_info=True)

    count = _increment_block_window()
    threshold = _alert_threshold()
    if count is not None and count >= threshold:
        _page_ops_on_spike(count, threshold, context)


def _alert_threshold() -> int:
    try:
        return max(1, int(current_app.config.get('CONTENT_SPAM_ALERT_THRESHOLD', 8)))
    except (TypeError, ValueError, RuntimeError):
        return 8


def _increment_block_window() -> int | None:
    try:
        from app.lib.redis_client import get_client
        client = get_client(decode_responses=True)
        if client is None:
            return None
        count = int(client.incr(_REDIS_WINDOW_KEY))
        if count == 1:
            client.expire(_REDIS_WINDOW_KEY, _REDIS_WINDOW_SECONDS)
        return count
    except Exception:
        return None


def _page_ops_on_spike(count: int, threshold: int, context: str) -> None:
    ip = None
    if has_request_context():
        ip = request.remote_addr
    message = (
        f"Content spam blocks spiked: {count} in 15 minutes "
        f"(threshold {threshold}). Latest context={context} ip={ip or 'n/a'}."
    )
    try:
        from app.scheduler import _send_ops_alert
        _send_ops_alert(message)
    except Exception:
        logger.warning('content_spam ops alert failed', exc_info=True)
