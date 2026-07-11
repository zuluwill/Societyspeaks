"""Durable email-subscriber ↔ anonymous-visitor identity bridge.

Society Speaks is intentionally anonymous-first: most participants never
create an account — they click through from an email and vote. Before this
module, that journey was two unjoinable identities: a subscriber row (email)
and a session fingerprint (site), so "did Tuesday's email lead to any
participation?" was unanswerable (measured 2026-07: zero links existed).

Mechanism, deliberately unobtrusive:

1. Email click-through endpoints (which already HMAC-verify the subscriber)
   set a signed, long-lived, httponly first-party cookie (``ss_subref``).
2. Participation endpoints (votes, daily-question responses, game turns) call
   :func:`link_subscriber_identity_from_request`, which reads the cookie and
   upserts a ``subscriber_identity_link`` row joining the subscriber to the
   visitor's session fingerprint and PostHog distinct_id.

Nothing about the anonymous UX changes; the link is measurement-only. All
functions are best-effort and never raise into product flows.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from flask import current_app, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

logger = logging.getLogger(__name__)

SUBSCRIBER_REF_COOKIE = 'ss_subref'
_COOKIE_SALT = 'subscriber-identity-ref'
_COOKIE_MAX_AGE_SECONDS = 180 * 86400  # 180 days
# Accept slightly-older cookies on read than we set, so a cookie written just
# under the limit is not rejected mid-session.
_READ_MAX_AGE_SECONDS = 200 * 86400


def _serializer() -> Optional[URLSafeTimedSerializer]:
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        return None
    return URLSafeTimedSerializer(secret, salt=_COOKIE_SALT)


def set_subscriber_ref_cookie(
    response: Any,
    *,
    brief_subscriber_id: Optional[int] = None,
    question_subscriber_id: Optional[int] = None,
) -> Any:
    """Attach the signed subscriber-reference cookie to ``response``.

    Call from endpoints that have just HMAC-verified the subscriber (email
    click redirects, one-click vote). Overwrites any previous ref: the most
    recent email identity wins, which is correct for shared devices.
    """
    try:
        s = _serializer()
        if s is None or not (brief_subscriber_id or question_subscriber_id):
            return response
        payload = {}
        if brief_subscriber_id:
            payload['b'] = int(brief_subscriber_id)
        if question_subscriber_id:
            payload['q'] = int(question_subscriber_id)
        response.set_cookie(
            SUBSCRIBER_REF_COOKIE,
            s.dumps(payload),
            max_age=_COOKIE_MAX_AGE_SECONDS,
            httponly=True,
            samesite='Lax',
            secure=request.is_secure,
        )
    except Exception as exc:  # never break a redirect over analytics
        logger.warning("Failed to set subscriber ref cookie: %s", exc)
    return response


def read_subscriber_ref() -> Optional[dict]:
    """Return ``{'b': id}`` / ``{'q': id}`` from a valid cookie, else None."""
    try:
        raw = request.cookies.get(SUBSCRIBER_REF_COOKIE)
        if not raw:
            return None
        s = _serializer()
        if s is None:
            return None
        payload = s.loads(raw, max_age=_READ_MAX_AGE_SECONDS)
        if isinstance(payload, dict) and ('b' in payload or 'q' in payload):
            return payload
        return None
    except BadSignature:
        return None
    except Exception:
        return None


def record_identity_link(
    *,
    source: str,
    brief_subscriber_id: Optional[int] = None,
    question_subscriber_id: Optional[int] = None,
    user_id: Optional[int] = None,
    session_fingerprint: Optional[str] = None,
    posthog_distinct_id: Optional[str] = None,
    commit: bool = True,
) -> None:
    """Upsert one subscriber↔visitor link row; refresh ``last_seen_at`` on repeat.

    No-op unless we have a subscriber reference AND at least one visitor-side
    identity — a link with only one side joins nothing.
    """
    from app import db
    from app.lib.time import utcnow_naive
    from app.models.email import SubscriberIdentityLink

    if not (brief_subscriber_id or question_subscriber_id):
        return
    if not (session_fingerprint or posthog_distinct_id or user_id):
        return

    try:
        existing = SubscriberIdentityLink.query.filter_by(
            brief_subscriber_id=brief_subscriber_id,
            question_subscriber_id=question_subscriber_id,
            session_fingerprint=session_fingerprint,
            posthog_distinct_id=posthog_distinct_id,
        ).first()
        if existing:
            existing.last_seen_at = utcnow_naive()
            existing.user_id = existing.user_id or user_id
        else:
            db.session.add(
                SubscriberIdentityLink(
                    brief_subscriber_id=brief_subscriber_id,
                    question_subscriber_id=question_subscriber_id,
                    user_id=user_id,
                    session_fingerprint=session_fingerprint,
                    posthog_distinct_id=posthog_distinct_id,
                    source=source,
                )
            )
        if commit:
            db.session.commit()
    except Exception as exc:
        logger.warning("Failed to record subscriber identity link: %s", exc)
        try:
            from app import db as _db
            _db.session.rollback()
        except Exception:
            pass


def link_subscriber_identity_from_request(
    *,
    source: str,
    session_fingerprint: Optional[str] = None,
    user_id: Optional[int] = None,
    commit: bool = True,
) -> None:
    """Record a link for the current request if it carries a subscriber ref.

    Call from participation endpoints (vote, daily-question response, game
    turn). Reads the signed cookie and the PostHog JS cookie; silently no-ops
    for visitors who never arrived via an email link.
    """
    try:
        ref = read_subscriber_ref()
        if not ref:
            return
        from app.lib.posthog_utils import posthog_js_distinct_id

        record_identity_link(
            source=source,
            brief_subscriber_id=ref.get('b'),
            question_subscriber_id=ref.get('q'),
            user_id=user_id,
            session_fingerprint=session_fingerprint,
            posthog_distinct_id=posthog_js_distinct_id(),
            commit=commit,
        )
    except Exception as exc:
        logger.warning("Failed to link subscriber identity: %s", exc)
