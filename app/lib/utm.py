"""
UTM capture and event attachment.

Stash UTM query params on key public-facing routes (landing, register, login),
attach to identity/conversion events (user_signed_up, paid_briefing_trial_started,
paid_briefing_subscribed), then clear so they don't leak onto later unrelated events.

See docs/PAID_BRIEFINGS_WORLD_CLASS_BUILD.md.
"""
from __future__ import annotations

from flask import request, session

# Standard UTM keys we capture. Keep narrow — don't blanket-stash arbitrary query params.
UTM_KEYS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term')

_SESSION_KEY = 'utm'


def stash_utms_from_querystring() -> None:
    """Capture UTM params from the current request and stash in session.

    Idempotent: only writes when at least one UTM is present in the URL, so
    internal navigation doesn't clobber a previously-stashed campaign attribution.
    """
    found = {k: request.args.get(k) for k in UTM_KEYS if request.args.get(k)}
    if found:
        session[_SESSION_KEY] = found


def peek_utms() -> dict[str, str]:
    """Return a copy of the stashed UTMs without clearing."""
    return dict(session.get(_SESSION_KEY) or {})


def pop_utms_for_event() -> dict[str, str]:
    """Return stashed UTMs and clear them.

    Use when firing the *conversion* event the UTM was meant to attribute
    (user_signed_up, paid_briefing_trial_started). Subsequent unrelated events
    won't pick up the same UTMs.
    """
    return dict(session.pop(_SESSION_KEY, None) or {})
