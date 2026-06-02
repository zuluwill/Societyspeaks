"""Server-side PostHog identity resolution and request-context enrichment.

These lock in the fixes that let server events stitch to the JS SDK's person:
- logged-in events use plain str(user_id) (matches identify('<id>'))
- anonymous events reuse the browser's PostHog cookie distinct_id when present
- otherwise fall back to a durable id (fingerprint / email / session)
- request-context props (url, referrer, utm) are attached to captured events
"""

import json
from urllib.parse import quote

from app.lib.posthog_utils import (
    posthog_js_distinct_id,
    request_context_properties,
    resolve_request_distinct_id,
)

PH_KEY = 'phc_test_key'


def _ph_cookie_header(distinct_id):
    blob = quote(json.dumps({'distinct_id': distinct_id}))
    return {'HTTP_COOKIE': f'ph_{PH_KEY}_posthog={blob}'}


def test_logged_in_resolves_to_plain_user_id(app):
    with app.test_request_context('/'):
        assert resolve_request_distinct_id(user_id=14) == '14'
        # Logged-in id wins even if an anon fallback is supplied.
        assert resolve_request_distinct_id(user_id=14, anon_fallback='fp') == '14'


def test_anonymous_prefers_posthog_cookie_then_fallback(app):
    app.config['POSTHOG_API_KEY'] = PH_KEY
    cookie = _ph_cookie_header('019e8792-js-uuid')

    with app.test_request_context('/', environ_base=cookie):
        assert posthog_js_distinct_id() == '019e8792-js-uuid'
        # Cookie id beats the fallback so server events join the JS person.
        assert resolve_request_distinct_id(anon_fallback='fp-hash') == '019e8792-js-uuid'

    # No cookie -> durable fallback (never a prefixed/invented id).
    with app.test_request_context('/'):
        assert resolve_request_distinct_id(anon_fallback='fp-hash') == 'fp-hash'


def test_anonymous_without_cookie_or_fallback_returns_none(app):
    with app.test_request_context('/'):
        assert resolve_request_distinct_id() is None


def test_request_context_properties_decompose_url_and_utms(app):
    with app.test_request_context(
        '/play/daily?utm_source=newsletter&utm_medium=email&utm_campaign=launch',
        headers={'Referer': 'https://example.org/landing'},
    ):
        props = request_context_properties()
    assert props['$pathname'] == '/play/daily'
    assert props['$referring_domain'] == 'example.org'
    assert props['$utm_source'] == 'newsletter'
    assert props['$utm_medium'] == 'email'
    assert props['$utm_campaign'] == 'launch'


def test_url_redacts_secret_path_tokens_and_query(app):
    """Events fire on token-bearing routes (magic-link / unsubscribe). The token
    must never reach analytics in $current_url / $pathname, and query strings are
    dropped entirely (campaign data survives via explicit $utm_* keys)."""
    secret = 'sekret-magic-token-abc123'
    with app.test_request_context(f'/daily/unsubscribe/{secret}?utm_source=email&foo=bar'):
        props = request_context_properties()
    assert secret not in props['$current_url']
    assert secret not in props['$pathname']
    assert '<token>' in props['$pathname']
    assert '?' not in props['$current_url']      # query stripped
    assert 'foo' not in props['$current_url']
    assert props['$utm_source'] == 'email'       # campaign preserved


def test_safe_capture_skips_when_distinct_id_missing(app):
    """A None/empty distinct_id must not create a 'None' person."""
    captured = []

    class _Client:
        project_api_key = 'phc_x'

        def capture(self, **kwargs):
            captured.append(kwargs)

    from app.lib.posthog_utils import safe_posthog_capture

    with app.test_request_context('/'):
        safe_posthog_capture(posthog_client=_Client(), distinct_id=None, event='x')
        safe_posthog_capture(posthog_client=_Client(), distinct_id='', event='x')
    assert captured == []


def test_journey_events_share_one_anonymous_identity(app):
    """All journey events must resolve the *same* anonymous distinct_id so the
    started -> step -> completed funnel connects (the civic-guide fix)."""
    from app.programmes.routes import _journey_distinct_id

    app.config['POSTHOG_API_KEY'] = PH_KEY
    cookie = _ph_cookie_header('019e8792-visitor')
    with app.test_request_context('/programmes/x', environ_base=cookie):
        first = _journey_distinct_id()
        second = _journey_distinct_id()
    assert first == second == '019e8792-visitor'
