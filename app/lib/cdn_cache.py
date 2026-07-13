"""CDN / edge-cache helpers for static and discovery responses.

Flask-Session adds ``Vary: Cookie`` whenever a session is accessed. That header
fragments (and often bypasses) Cloudflare's cache for otherwise-public assets.
Static and discovery paths never personalise their bodies, so we:

  1. Skip session open/save on those paths (see ``session_policy``).
  2. Strip ``Cookie`` from ``Vary`` and set long-lived ``Cache-Control`` here.

HTML pages stay dynamic (sessions, CSRF, auth) — do not add them to these
prefixes.
"""

from __future__ import annotations

from typing import Iterable

# Paths that must never depend on cookies and should be edge-cacheable.
# Keep in sync with Cloudflare Cache Rule ``cache-static-assets`` in OPS.md.
_CDN_CACHEABLE_PREFIXES: tuple[str, ...] = (
    '/assets/',
    '/images/',
    '/css/',
    '/js/',
    '/fonts/',
    '/icons/',
    '/logos/',
    '/data/',
    '/dist/',
    '/profiles/assets/',
    '/profiles/get-image/',
)

_CDN_CACHEABLE_EXACT: frozenset[str] = frozenset({
    '/favicon.ico',
    '/favicon.png',
    '/favicon.svg',
    '/robots.txt',
    '/sitemap.xml',
    '/llms.txt',
})

# Repo static + object-storage marketing assets. Discovery endpoints set their
# own Cache-Control (s-maxage tuned for SEO freshness) — do not override them.
_STATIC_CACHE_CONTROL_PREFIXES: tuple[str, ...] = (
    '/assets/',
    '/images/',
    '/css/',
    '/js/',
    '/fonts/',
    '/icons/',
    '/logos/',
    '/data/',
    '/dist/',
    '/profiles/assets/',
    '/profiles/get-image/',
)

_STATIC_CACHE_CONTROL_EXACT: frozenset[str] = frozenset({
    '/favicon.ico',
    '/favicon.png',
    '/favicon.svg',
})

# Browser 1 day / edge 7 days. Purge Cloudflare after shipping changed assets
# that share a stable URL (hero, unversioned JS). Versioned CSS (?v=) is fine.
STATIC_ASSET_CACHE_CONTROL = 'public, max-age=86400, s-maxage=604800'


def _path_matches(path: str, prefixes: Iterable[str], exact: frozenset[str]) -> bool:
    if not path:
        return False
    if path in exact:
        return True
    return any(path.startswith(prefix) for prefix in prefixes)


def is_cdn_cacheable_path(path: str) -> bool:
    """True when the response body must not vary on cookies/session."""
    return _path_matches(path, _CDN_CACHEABLE_PREFIXES, _CDN_CACHEABLE_EXACT)


def should_set_static_cache_control(path: str) -> bool:
    """True when this module should own the Cache-Control header."""
    return _path_matches(path, _STATIC_CACHE_CONTROL_PREFIXES, _STATIC_CACHE_CONTROL_EXACT)


def strip_cookie_from_vary(response) -> None:
    """Remove Cookie from Vary so CDNs can share one cache entry per URL."""
    vary_header = response.headers.get('Vary')
    if not vary_header:
        return
    parts = [
        part.strip()
        for part in vary_header.split(',')
        if part.strip() and part.strip().lower() != 'cookie'
    ]
    if parts:
        response.headers['Vary'] = ', '.join(parts)
    else:
        response.headers.pop('Vary', None)


def strip_set_cookie(response) -> None:
    """Drop Set-Cookie so Cloudflare will store the response at the edge."""
    # Werkzeug's __delitem__ removes every Set-Cookie occurrence in one call.
    if response.headers.get('Set-Cookie') is not None:
        del response.headers['Set-Cookie']


def apply_cdn_cacheable_response_headers(path: str, response):
    """Strip session Vary/cookies and set Cache-Control on static responses."""
    if not is_cdn_cacheable_path(path):
        return response

    strip_cookie_from_vary(response)
    strip_set_cookie(response)

    if should_set_static_cache_control(path) and response.status_code == 200:
        response.headers['Cache-Control'] = STATIC_ASSET_CACHE_CONTROL

    return response


def wrap_session_interface_for_cdn(app) -> None:
    """Skip persisting sessions on CDN-cacheable paths.

    Flask calls ``save_session`` *after* ``after_request`` handlers. Skipping
    save means no ``Vary: Cookie`` / ``Set-Cookie`` from the session layer,
    which is required for edge HITs.

    Important: do **not** return Flask's ``NullSession`` here. Missing assets
    ``abort(404)`` into HTML error pages that call ``csrf_token()``, and
    ``generate_csrf`` writes ``session['csrf_token']``. NullSession raises
    RuntimeError("...no secret key was set") on any write — a misleading
    message that is really "session is read-only/null", and it turns asset
    404s into 500s in Sentry.
    """
    from flask import has_request_context, request

    iface = app.session_interface
    orig_open = iface.open_session
    orig_save = iface.save_session
    session_class = getattr(iface, 'session_class', None)

    def open_session(app_, req):
        if is_cdn_cacheable_path(req.path) and session_class is not None:
            # Transient empty writable session for this request only.
            # Never loaded from / saved to Redis (save_session is a no-op).
            try:
                return session_class(sid=None, permanent=False)
            except TypeError:
                # SecureCookieSession (cachelib fallback) takes no sid=.
                return session_class()
        return orig_open(app_, req)

    def save_session(app_, session, response):
        if has_request_context() and is_cdn_cacheable_path(request.path):
            return
        return orig_save(app_, session, response)

    iface.open_session = open_session  # type: ignore[method-assign]
    iface.save_session = save_session  # type: ignore[method-assign]
