"""
URL builder for the Personal Briefs paid-trial CTA.

Single source of truth for where various surfaces (Daily Brief email footer,
activation nudge emails, in-app banners) link to when promoting the paid
Personal Briefs trial. Branches on the SELF_SERVE_TRIAL_ENABLED feature flag.

See docs/PAID_BRIEFINGS_WORLD_CLASS_BUILD.md.
"""
from __future__ import annotations

from urllib.parse import urlencode

from flask import current_app

# Default template slug for the global trial flow. Lives here (rather than
# in briefing/routes.py) so the same value drives:
#   - the route's _resolve_default_template_slug fallback
#   - the Daily Brief email footer CTA
#   - the scheduler activation-nudge email link
# Keeps the three call sites from drifting if we ever change the global default.
DEFAULT_TRIAL_TEMPLATE_SLUG = 'technology-ai-regulation'


def personal_briefs_cta_url(
    base_url: str,
    *,
    utm_source: str,
    utm_medium: str = 'email',
    utm_campaign: str = 'personal_briefs_cta',
    template_slug: str | None = None,
) -> str:
    """Return the URL the "Create your own brief" CTA should point at.

    When SELF_SERVE_TRIAL_ENABLED is on, points at the new /briefings/start
    magic-link trial flow. Otherwise falls back to /briefings/landing.
    """
    self_serve_on = bool(current_app.config.get('SELF_SERVE_TRIAL_ENABLED'))
    path = '/briefings/start' if self_serve_on else '/briefings/landing'

    params = {
        'utm_source': utm_source,
        'utm_medium': utm_medium,
        'utm_campaign': utm_campaign,
    }
    if self_serve_on and template_slug:
        params['template'] = template_slug

    return f"{base_url.rstrip('/')}{path}?{urlencode(params)}"
