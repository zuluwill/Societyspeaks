"""
UTM capture and event attachment.

Stash UTM query params on key public-facing routes (landing, register, login,
/briefings/start), attach to identity/conversion events (user_signed_up via
``app.lib.identity_analytics``, paid_briefing_trial_*, paid_briefing_subscribed),
then clear on the conversion event so they don't leak onto later unrelated events.

Identity events always include ``signup_method`` so acquisition can break down
register vs trial_magic_link (and other) paths without losing campaign attribution.

``with_utm_params`` is the single writer for first-party email links so Daily
Brief / weekly digest traffic is not classified as Direct in PostHog.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from flask import request, session

# Standard UTM keys we capture. Keep narrow — don't blanket-stash arbitrary query params.
UTM_KEYS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term')

_SESSION_KEY = 'utm'

# Do not tag account-management or outbound links. Unsubscribe / preferences
# tokens and mailto: must stay query-stable (RFC 8058 one-click).
_SKIP_SCHEMES = ('mailto', 'tel')


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


def brief_email_utm_params(brief=None, *, source: str | None = None) -> dict[str, str]:
    """Canonical UTM trio for brief / digest email links.

    ``utm_campaign`` stays ``brief`` so PostHog aggregates across editions.
    Edition is already on the landing path (``/brief/2026-09-23``).
    """
    if source:
        utm_source = source
    elif brief is not None and getattr(brief, 'brief_type', 'daily') == 'weekly':
        utm_source = 'weekly_brief'
    else:
        utm_source = 'daily_brief'
    return {
        'utm_source': utm_source,
        'utm_medium': 'email',
        'utm_campaign': 'brief',
    }


def with_utm_params(
    url: str | None,
    params: dict[str, str] | None = None,
    *,
    content: str | None = None,
    **overrides: str,
) -> str:
    """Append UTM query params without clobbering existing ones or the fragment.

    Skips empty URLs, fragments, and non-http schemes. Existing ``utm_*`` keys
    win so a caller that already tagged the URL (Personal Briefs CTA) is left
    alone.
    """
    if not url or url.startswith('#'):
        return url or ''
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if parsed.scheme and parsed.scheme.lower() in _SKIP_SCHEMES:
        return url

    merged = dict(params or {})
    merged.update({k: v for k, v in overrides.items() if v})
    if content:
        merged.setdefault('utm_content', content)

    incoming = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in merged.items():
        if not value:
            continue
        incoming.setdefault(key, value)
    # Keep commas (question-id lists) and slashes readable; Flask still
    # decodes the percent-encoded form if a caller encoded them already.
    return urlunparse(parsed._replace(query=urlencode(incoming, safe=',/')))


def with_utm_filter(url, content=None, source=None, campaign=None):
    """Jinja filter: ``url|with_utm('methodology', email_utm_source)``."""
    params = brief_email_utm_params(source=source)
    if campaign:
        params['utm_campaign'] = campaign
    return with_utm_params(url, params, content=content)
