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
    email_subscriber_distinct_id,
    posthog_js_distinct_id,
    request_context_properties,
    resolve_request_distinct_id,
)
from app.daily.vote_analytics import resolve_daily_participation_distinct_id, subscriber_for_analytics

PH_KEY = 'phc_test_key'


def _ph_cookie_header(distinct_id):
    blob = quote(json.dumps({'distinct_id': distinct_id}))
    return {'HTTP_COOKIE': f'ph_{PH_KEY}_posthog={blob}'}


def test_subscriber_for_analytics_reads_ss_subref_cookie(app, db):
    from app.lib.subscriber_identity import SUBSCRIBER_REF_COOKIE, set_subscriber_ref_cookie
    from app.models import DailyBriefSubscriber
    from flask import Response

    with app.app_context():
        db.create_all()
        sub = DailyBriefSubscriber(email='cookie-ref@example.com', status='active')
        db.session.add(sub)
        db.session.commit()

        with app.test_request_context('/'):
            resp = Response()
            set_subscriber_ref_cookie(resp, brief_subscriber_id=sub.id)
            cookie_header = resp.headers.get('Set-Cookie', '')
        cookie_value = cookie_header.split(f'{SUBSCRIBER_REF_COOKIE}=', 1)[1].split(';', 1)[0]

        with app.test_request_context(
            '/',
            environ_base={'HTTP_COOKIE': f'{SUBSCRIBER_REF_COOKIE}={cookie_value}'},
        ):
            resolved = subscriber_for_analytics()
            assert resolved is not None
            assert resolved.id == sub.id
            expected = email_subscriber_distinct_id(sub.email)
            assert resolve_daily_participation_distinct_id() == expected


def test_stitch_posthog_on_user_login_aliases_and_identifies(app):
    from unittest.mock import MagicMock, patch

    import posthog

    from app.lib.posthog_utils import stitch_posthog_on_user_login

    app.config['POSTHOG_API_KEY'] = PH_KEY
    posthog.project_api_key = 'phk_test'

    user = MagicMock()
    user.id = 42
    user.email = 'member@example.com'
    user.username = 'member'

    with patch('app.lib.posthog_utils.posthog_js_distinct_id', return_value='019e8792-anon-uuid'):
        with patch('app.lib.posthog_utils.safe_posthog_capture') as capture:
            with patch.object(posthog, 'alias') as alias_mock:
                with app.test_request_context('/'):
                    stitch_posthog_on_user_login(
                        user,
                        subscriber_email='member@example.com',
                        properties={'method': 'magic_link', 'source': 'one_click_vote'},
                    )

    alias_mock.assert_any_call(
        previous_id='019e8792-anon-uuid',
        distinct_id='42',
    )
    capture.assert_called_once()
    assert capture.call_args.kwargs['distinct_id'] == '42'
    assert capture.call_args.kwargs['event'] == 'user_logged_in'


def test_daily_participation_resolver_prefers_cookie_then_subscriber(app, db):
    from app.models import DailyBriefSubscriber

    app.config['POSTHOG_API_KEY'] = PH_KEY
    cookie = _ph_cookie_header('019e8792-js-uuid')

    with app.app_context():
        db.create_all()
        sub = DailyBriefSubscriber(email='resolver@example.com', status='active')
        db.session.add(sub)
        db.session.commit()

        with app.test_request_context('/', environ_base=cookie):
            assert resolve_daily_participation_distinct_id(subscriber=sub) == '019e8792-js-uuid'

        with app.test_request_context('/'):
            from flask import session

            session['brief_subscriber_id'] = sub.id
            expected = email_subscriber_distinct_id(sub.email)
            assert resolve_daily_participation_distinct_id() == expected


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


def test_safe_capture_skips_when_distinct_id_missing(app, caplog):
    """A None/empty distinct_id must not create a 'None' person and should log."""
    captured = []

    class _Client:
        project_api_key = 'phc_x'

        def capture(self, **kwargs):
            captured.append(kwargs)

    from app.lib.posthog_utils import safe_posthog_capture

    with app.test_request_context('/'):
        with caplog.at_level('WARNING'):
            safe_posthog_capture(posthog_client=_Client(), distinct_id=None, event='x')
            safe_posthog_capture(posthog_client=_Client(), distinct_id='', event='x')
    assert captured == []
    assert any('no distinct_id' in r.message for r in caplog.records)


def test_email_subscriber_id_is_pseudonymous_and_stable():
    """Email-only subscribers get one stable, PII-free id so subscribe ->
    digest_sent -> vote -> unsubscribe all stitch (and raw email never leaks)."""
    a = email_subscriber_distinct_id('Person@Example.com')
    b = email_subscriber_distinct_id('  person@example.com ')  # case/space-insensitive
    assert a == b                       # consistent across events / casing
    assert a.startswith('subscriber:')
    assert 'person@example.com' not in a and 'Person@Example.com' not in a
    assert email_subscriber_distinct_id('') is None
    assert email_subscriber_distinct_id(None) is None


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


def test_scripted_clients_are_detected_and_browsers_are_not(app):
    """UA gate: scripted clients (python-requests, curl, declared bots) are
    detected; ordinary browsers and no-request contexts are not."""
    from app.lib.posthog_utils import request_is_scripted_client

    with app.test_request_context('/', headers={'User-Agent': 'python-requests/2.32.4'}):
        assert request_is_scripted_client() is True
    with app.test_request_context('/', headers={'User-Agent': 'Googlebot/2.1'}):
        assert request_is_scripted_client() is True
    with app.test_request_context(
        '/', headers={'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36'}
    ):
        assert request_is_scripted_client() is False
    # Outside a request (cron/scheduler captures) nothing is blocked.
    assert request_is_scripted_client() is False


def test_browser_evidence_requires_posthog_cookie(app):
    """Page-load-triggered events must only fire for visitors who demonstrably
    executed the JS snippet (the ph cookie). Browser-UA crawlers never carry it
    — that's what made journey_started 99.9% bots."""
    from app.lib.posthog_utils import request_has_browser_evidence

    app.config['POSTHOG_API_KEY'] = PH_KEY
    browser_ua = {'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36'}
    cookie = _ph_cookie_header('019e8792-visitor')

    # Browser UA but no cookie (crawler or first-ever render): no evidence.
    with app.test_request_context('/', headers=browser_ua):
        assert request_has_browser_evidence() is False
    # Cookie + browser UA: evidence.
    with app.test_request_context('/', headers=browser_ua, environ_base=cookie):
        assert request_has_browser_evidence() is True
    # Cookie forged by a scripted client: still blocked.
    with app.test_request_context(
        '/', headers={'User-Agent': 'python-requests/2.32.4'}, environ_base=cookie
    ):
        assert request_has_browser_evidence() is False


def test_safe_capture_drops_scripted_client_requests(app):
    """safe_posthog_capture silently drops events fired by scripted-client UAs
    so scanner noise can never re-enter analytics from any call site."""
    captured = []

    class _Client:
        project_api_key = 'phc_x'

        def capture(self, **kwargs):
            captured.append(kwargs)

    from app.lib.posthog_utils import safe_posthog_capture

    with app.test_request_context('/', headers={'User-Agent': 'python-requests/2.32.4'}):
        safe_posthog_capture(posthog_client=_Client(), distinct_id='fp-1', event='x')
    assert captured == []

    with app.test_request_context(
        '/', headers={'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36'}
    ):
        safe_posthog_capture(posthog_client=_Client(), distinct_id='fp-1', event='x')
    assert len(captured) == 1


def test_game_run_started_fires_without_posthog_cookie(app):
    """game_run_started must not require the PostHog JS cookie on the GET request.

    The cookie is set after JS runs, so a server-side gate on it dropped every
    first-page load (regression from Jul 2026 browser-evidence gate).
    """
    from unittest.mock import patch

    from app.game.analytics import track_game_event
    from app.models.game import GameRun

    run = GameRun(
        uuid='test-uuid', scenario_slug='s', mode='quick',
        session_fingerprint='fp-1', turn_index=0, total_turns=10,
    )
    browser_ua = {'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36'}

    with patch('app.game.analytics.safe_posthog_capture') as capture:
        with app.test_request_context('/run/s', headers=browser_ua):
            track_game_event(run, 'game_run_started')
            assert capture.call_count == 1
            props = capture.call_args.kwargs['properties']
            assert 'is_authenticated' in props
