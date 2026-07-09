"""
Session storage policy for server-side (Redis) sessions.

Flask-Session writes every non-empty session to Redis with
PERMANENT_SESSION_LIFETIME as the storage TTL. Because the base layout renders
a CSRF-protected form on every page, every first-time visitor — including
every crawler request, since bots do not return cookies — minted a session key
that lived 7 days. At ~40k new sessions/day that filled the 250MB Redis
instance and volatile-lru began evicting logged-in users' sessions.

Policy applied here:
  - Sessions with no authenticated principal get ANONYMOUS_SESSION_LIFETIME
    (default 48h) instead of PERMANENT_SESSION_LIFETIME (7 days).
  - Requests from known crawler user agents never persist an anonymous
    session at all (no Redis key, no Set-Cookie).
  - Authenticated sessions (Flask-Login user or partner portal) are
    unaffected: full PERMANENT_SESSION_LIFETIME.

One-off cleanup of pre-policy keys: scripts/purge_anonymous_sessions.py.
"""

from flask import current_app, has_request_context, request

from app.lib.resilient_session import ResilientRedisSessionInterface

# Shared with the vote endpoint (app/discussions/statements.py). Keep this
# list conservative: it also blocks voting for matching user agents.
BOT_UA_INDICATORS = ['bot', 'crawler', 'spider', 'preview', 'fetch', 'slurp', 'mediapartners']

# Broader list used only to decide whether a session is worth persisting —
# a false positive here just means a scripted client gets a fresh session
# per request, so it is safe to match aggressively.
SESSION_SKIP_UA_INDICATORS = BOT_UA_INDICATORS + [
    'python-requests', 'python-httpx', 'curl/', 'wget/', 'scrapy',
    'go-http-client', 'java/', 'libwww', 'okhttp', 'headlesschrome',
]

# Session keys that mark an authenticated principal. '_user_id' is set by
# Flask-Login; 'partner_portal_id' by the partner portal login.
AUTH_SESSION_KEYS = ('_user_id', 'partner_portal_id')


def user_agent_is_bot(user_agent, indicators=BOT_UA_INDICATORS):
    ua = (user_agent or '').lower()
    return any(indicator in ua for indicator in indicators)


def session_is_authenticated(session):
    return any(key in session for key in AUTH_SESSION_KEYS)


class PolicyRedisSessionInterface(ResilientRedisSessionInterface):
    """Resilient Redis session interface with anonymous/bot storage policy."""

    def should_set_storage(self, app, session):
        if not super().should_set_storage(app, session):
            return False
        if session_is_authenticated(session):
            return True
        if has_request_context() and user_agent_is_bot(
            request.headers.get('User-Agent'), SESSION_SKIP_UA_INDICATORS
        ):
            return False
        return True

    def _upsert_session(self, session_lifetime, session, store_id):
        if not session_is_authenticated(session):
            session_lifetime = current_app.config.get(
                'ANONYMOUS_SESSION_LIFETIME', session_lifetime
            )
        super()._upsert_session(session_lifetime, session, store_id)
