"""
Trial-signup abuse controls.

Three layers, cheapest first:
  1. Disposable email domain block (static list, ~30 common providers).
  2. Per-IP rate limit (Redis-backed; soft no-op if Redis unavailable).
  3. One-trial-per-normalized-email (DB lookup against existing
     Subscription rows tagged with trial_source='self_serve').

The order matters: the cheapest checks fail fast on bot bursts; only
"real-looking" emails reach the DB query.

See docs/PAID_BRIEFINGS_WORLD_CLASS_BUILD.md.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from app.lib.email_normalize import normalize_trial_email

# Static list — small enough to maintain inline, large enough to catch
# the obvious abuse patterns. Expand if signal shows new providers.
_DISPOSABLE_DOMAINS = frozenset({
    '10minutemail.com', '20minutemail.com', 'guerrillamail.com', 'guerrillamail.net',
    'guerrillamail.org', 'mailinator.com', 'mailinator.net', 'maildrop.cc',
    'sharklasers.com', 'temp-mail.org', 'tempmail.com', 'throwaway.email',
    'getnada.com', 'tempr.email', 'yopmail.com', 'fakeinbox.com',
    'trashmail.com', 'trashmail.net', 'dispostable.com', 'mintemail.com',
    'mohmal.com', 'mytemp.email', 'temp-mail.io', 'tempmailaddress.com',
    'tempmailo.com', 'emailondeck.com', 'mailpoof.com', 'mvrht.net',
    'spambog.com', 'spamgourmet.com',
})

# Per-IP cap for trial starts within the rolling window.
_IP_RATE_LIMIT_COUNT = 5
_IP_RATE_LIMIT_WINDOW = timedelta(hours=24)


def can_start_trial(email: Optional[str], ip: Optional[str]) -> tuple[bool, Optional[str]]:
    """Return ``(ok, reason)`` for whether this (email, IP) pair may start a trial.

    The reason string is for logging — UIs should show a single generic
    message regardless of which check failed, to avoid revealing which
    addresses or IPs are already on file.

    Reasons used:
      - ``'invalid_email'`` — empty or malformed
      - ``'disposable_domain'`` — domain on the blocklist
      - ``'ip_rate_limit'`` — too many starts from this IP in the window
      - ``'email_already_used'`` — prior self-serve trial for this canonical address
    """
    normalized = normalize_trial_email(email)
    if not normalized:
        return False, 'invalid_email'

    domain = normalized.rpartition('@')[2]
    if domain in _DISPOSABLE_DOMAINS:
        return False, 'disposable_domain'

    if ip and not _check_ip_rate_limit(ip):
        return False, 'ip_rate_limit'

    if _email_already_used_for_trial(normalized):
        return False, 'email_already_used'

    return True, None


def record_trial_start(ip: Optional[str]) -> None:
    """Bump the per-IP counter after a successful trial creation.

    Best-effort: if Redis is unavailable the limit silently degrades to off.
    Call this from the trial-create service after the DB transaction commits.
    """
    if not ip:
        return
    try:
        from app.lib.redis_client import get_client as _get_redis
        client = _get_redis(decode_responses=True)
    except Exception:
        return
    if not client:
        return
    try:
        key = f'trial_start_ip:{ip}'
        new_count = client.incr(key)
        if new_count == 1:
            client.expire(key, int(_IP_RATE_LIMIT_WINDOW.total_seconds()))
    except Exception:
        pass


def _check_ip_rate_limit(ip: str) -> bool:
    """Return True if the IP is still under the rate limit."""
    try:
        from app.lib.redis_client import get_client as _get_redis
        client = _get_redis(decode_responses=True)
    except Exception:
        # Redis down — fail open so legitimate users aren't blocked.
        return True
    if not client:
        return True
    try:
        key = f'trial_start_ip:{ip}'
        raw = client.get(key)
        count = int(raw) if raw else 0
        return count < _IP_RATE_LIMIT_COUNT
    except Exception:
        return True


def _user_ids_with_canonical_email(normalized_email: str) -> set[int]:
    """User ids whose stored email normalizes to ``normalized_email``."""
    from sqlalchemy import func, or_

    from app.models import User

    domain = normalized_email.rpartition('@')[2]
    if domain == 'gmail.com':
        # Gmail alias rules only apply on Google domains — scan that cohort,
        # not the full users table.
        candidates = (
            User.query.filter(
                or_(
                    func.lower(User.email).like('%@gmail.com'),
                    func.lower(User.email).like('%@googlemail.com'),
                )
            )
            .with_entities(User.id, User.email)
            .all()
        )
    else:
        candidates = (
            User.query.filter(func.lower(User.email) == normalized_email)
            .with_entities(User.id, User.email)
            .all()
        )

    return {
        uid
        for (uid, email) in candidates
        if normalize_trial_email(email) == normalized_email
    }


def find_user_by_canonical_email(email: Optional[str]):
    """Return the earliest-created :class:`User` whose stored email normalizes
    to the same canonical form as ``email`` — or ``None`` if no match.

    Use this from the self-serve trial route before creating a new User, so
    a Gmail-alias second visit reuses the existing account instead of
    silently creating a sibling.
    """
    normalized = normalize_trial_email(email)
    if not normalized:
        return None
    ids = _user_ids_with_canonical_email(normalized)
    if not ids:
        return None
    from app.models import User
    return User.query.filter(User.id.in_(ids)).order_by(User.id.asc()).first()


def _email_already_used_for_trial(normalized_email: str) -> bool:
    """Return True if a self-serve trial subscription already exists for this
    canonical email address.

    Compares against the User's stored email after normalizing — so users who
    signed up as ``foo+a@gmail.com`` and later try ``foo+b@gmail.com`` are
    correctly recognized as the same person.
    """
    from app.models.billing import Subscription

    matching_ids = _user_ids_with_canonical_email(normalized_email)
    if not matching_ids:
        return False

    for sub in Subscription.query.filter(Subscription.user_id.in_(matching_ids)):
        if (sub.extra_data or {}).get('trial_source') == 'self_serve':
            return True
    return False
