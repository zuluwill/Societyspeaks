"""
Periodic Stripe ↔ local reconciliation for Paid Briefings ``Subscription`` rows.

Webhooks are the primary source of truth; this job corrects drift after outages,
missed events, or partial failures. Designed for large tables: keyset pagination,
Redis cursor, bounded work per run, savepoint-per-row isolation.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import stripe

from app import db
from app.billing.service import _stripe_call, get_stripe, sync_subscription_from_stripe
from app.lib.time import utcnow_naive
from app.models import Subscription

logger = logging.getLogger(__name__)

REDIS_CURSOR_KEY = 'stripe:reconcile:briefing_subscription:last_pk'


def _production_requires_redis_cursor(cfg) -> bool:
    """Without Redis the reconciliation cursor cannot advance — unsafe at scale."""
    if cfg.get('TESTING'):
        return False
    env = str(cfg.get('FLASK_ENV') or os.getenv('FLASK_ENV') or '').strip().lower()
    return env == 'production'


def _redis_client_available() -> bool:
    try:
        from app.lib.redis_client import get_client

        return get_client(decode_responses=True) is not None
    except Exception:
        return False


def _redis_cursor_get() -> int:
    try:
        from app.lib.redis_client import get_client

        r = get_client(decode_responses=True)
        if not r:
            return 0
        raw = r.get(REDIS_CURSOR_KEY)
        return int(raw) if raw is not None else 0
    except Exception as exc:  # pragma: no cover - Redis optional in dev
        logger.warning('Briefing reconcile: Redis cursor unavailable (%s); using pk 0', exc)
        return 0


def _redis_cursor_set(pk: int) -> None:
    try:
        from app.lib.redis_client import get_client

        r = get_client(decode_responses=True)
        if r:
            r.set(REDIS_CURSOR_KEY, str(pk), ex=86400 * 14)
    except Exception as exc:  # pragma: no cover
        logger.warning('Briefing reconcile: could not persist cursor (%s)', exc)


def _subscription_missing(exc: stripe.error.InvalidRequestError) -> bool:
    code = getattr(exc, 'code', None)
    if code == 'resource_missing':
        return True
    msg = str(exc).lower()
    return 'no such subscription' in msg


def reconcile_briefing_subscriptions_batch() -> dict[str, Any]:
    """Sweep a slice of briefing subscriptions and refresh from Stripe.

    Returns a stats dict suitable for logging/monitoring.
    """
    from flask import current_app

    cfg = current_app.config

    if not cfg.get('STRIPE_BRIEFING_RECONCILE_ENABLED', True):
        return {'skipped': True, 'reason': 'disabled'}

    if not (cfg.get('STRIPE_SECRET_KEY') or '').strip():
        logger.warning('Briefing reconcile skipped: STRIPE_SECRET_KEY not set')
        return {'skipped': True, 'reason': 'no_stripe_key'}

    if (
        _production_requires_redis_cursor(cfg)
        and not cfg.get('STRIPE_BRIEFING_RECONCILE_ALLOW_NO_REDIS_CURSOR')
        and not _redis_client_available()
    ):
        logger.error(
            'Briefing reconcile aborted: Redis required in production to persist pagination cursor '
            '(set STRIPE_BRIEFING_RECONCILE_ALLOW_NO_REDIS_CURSOR=true only if you accept repeated scans)'
        )
        return {'skipped': True, 'reason': 'redis_required'}

    batch_size = max(1, int(cfg.get('STRIPE_BRIEFING_RECONCILE_BATCH_SIZE') or 200))
    max_per_run = max(batch_size, int(cfg.get('STRIPE_BRIEFING_RECONCILE_MAX_PER_RUN') or 5000))
    sleep_s = float(cfg.get('STRIPE_BRIEFING_RECONCILE_SLEEP_SECONDS') or 0)

    s = get_stripe()
    cursor = _redis_cursor_get()

    stats: dict[str, Any] = {
        'cursor_start': cursor,
        'examined': 0,
        'synced': 0,
        'marked_canceled': 0,
        'stripe_errors': 0,
        'sync_errors': 0,
        'wrapped_table': False,
        'cursor_end': cursor,
    }

    try:
        while stats['examined'] < max_per_run:
            rows = (
                Subscription.query.filter(
                    Subscription.stripe_subscription_id.isnot(None),
                    Subscription.id > cursor,
                )
                .order_by(Subscription.id.asc())
                .limit(batch_size)
                .all()
            )

            if not rows:
                cursor = 0
                _redis_cursor_set(cursor)
                stats['wrapped_table'] = True
                stats['cursor_end'] = cursor
                break

            last_processed_pk = cursor

            for row in rows:
                if stats['examined'] >= max_per_run:
                    break

                stats['examined'] += 1
                last_processed_pk = row.id
                sub_pk = row.id

                try:
                    with db.session.begin_nested():
                        stripe_sub = _stripe_call(s.Subscription.retrieve, row.stripe_subscription_id)
                        sync_subscription_from_stripe(
                            stripe_sub,
                            user_id=row.user_id,
                            org_id=row.org_id,
                            commit=False,
                        )
                    stats['synced'] += 1
                except stripe.error.InvalidRequestError as exc:
                    if _subscription_missing(exc):
                        try:
                            with db.session.begin_nested():
                                local = db.session.get(Subscription, sub_pk)
                                if local and local.stripe_subscription_id:
                                    local.status = 'canceled'
                                    if not local.canceled_at:
                                        local.canceled_at = utcnow_naive()
                                    db.session.flush()
                            stats['marked_canceled'] += 1
                        except Exception as mark_exc:
                            stats['stripe_errors'] += 1
                            logger.warning(
                                'Briefing reconcile: could not mark canceled local_id=%s: %s',
                                sub_pk,
                                mark_exc,
                            )
                    else:
                        stats['stripe_errors'] += 1
                        logger.warning(
                            'Briefing reconcile: Stripe InvalidRequest local_id=%s sub=%s: %s',
                            sub_pk,
                            row.stripe_subscription_id,
                            exc,
                        )
                except ValueError as exc:
                    stats['sync_errors'] += 1
                    logger.warning(
                        'Briefing reconcile: plan sync ValueError local_id=%s sub=%s: %s',
                        sub_pk,
                        row.stripe_subscription_id,
                        exc,
                    )
                except stripe.error.StripeError as exc:
                    stats['stripe_errors'] += 1
                    logger.warning(
                        'Briefing reconcile: Stripe error local_id=%s sub=%s: %s',
                        sub_pk,
                        row.stripe_subscription_id,
                        exc,
                    )

                if sleep_s > 0:
                    time.sleep(sleep_s)

            cursor = last_processed_pk
            _redis_cursor_set(cursor)
            stats['cursor_end'] = cursor

    finally:
        try:
            db.session.commit()
        except Exception as exc:
            logger.error('Briefing reconcile: outer commit failed: %s', exc, exc_info=True)
            db.session.rollback()

    return stats
