"""Server-side PostHog identity resolution and request-context enrichment.

These lock in the fixes that let server events stitch to the JS SDK's person:
- logged-in events use plain str(user_id) (matches identify('<id>'))
- anonymous events reuse the browser's PostHog cookie distinct_id when present
- otherwise fall back to a durable id (fingerprint / email / session)
- request-context props (url, referrer, utm) are attached to captured events
"""

import json
import uuid
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from app.lib.posthog_utils import (
    email_subscriber_distinct_id,
    posthog_js_distinct_id,
    request_context_properties,
    resolve_request_distinct_id,
)
from app.daily.vote_analytics import (
    resolve_daily_participation_distinct_id,
    resolve_email_vote_distinct_id,
    subscriber_for_analytics,
    track_email_vote_confirm_viewed,
)

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


def test_email_vote_distinct_id_prefers_subscriber_over_cookie(app, db):
    from app.models import DailyBriefSubscriber

    app.config['POSTHOG_API_KEY'] = 'phc_test_key'
    cookie = {'HTTP_COOKIE': 'ph_phc_test_key_posthog=%7B%22distinct_id%22%3A%22019e8792-js-uuid%22%7D'}

    with app.app_context():
        db.create_all()
        sub = DailyBriefSubscriber(email='email-vote@example.com', status='active')
        db.session.add(sub)
        db.session.commit()
        expected = email_subscriber_distinct_id(sub.email)

        with app.test_request_context('/', environ_base=cookie):
            assert resolve_email_vote_distinct_id(sub) == expected
            assert resolve_email_vote_distinct_id(sub) != '019e8792-js-uuid'


def test_daily_participation_web_path_still_prefers_cookie(app, db):
    """Web/batch participation keeps cookie-first stitching; email funnel is separate."""
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


def test_email_vote_confirm_aliases_cookie_to_subscriber(app, db):
    import posthog
    from datetime import date

    from app.models import DailyBriefSubscriber, DailyQuestion

    app.config['POSTHOG_API_KEY'] = PH_KEY

    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=80,
            question_text='Alias stitch?',
            status='published',
            source_type='discussion',
        )
        sub = DailyBriefSubscriber(email='alias-stitch@example.com', status='active')
        db.session.add_all([q, sub])
        db.session.commit()

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            with patch('app.lib.posthog_utils.posthog_js_distinct_id', return_value='019e8792-js-uuid'):
                with patch.object(posthog, 'alias') as alias_mock:
                    with app.test_request_context('/', headers={'User-Agent': 'Mozilla/5.0 (iPhone)'}):
                        track_email_vote_confirm_viewed(
                            subscriber=sub,
                            question=q,
                            vote_choice='agree',
                            voter_channel='brief',
                            source='brief_email',
                        )

        alias_mock.assert_called_once_with(
            previous_id='019e8792-js-uuid',
            distinct_id=email_subscriber_distinct_id(sub.email),
        )
        capture = mock_ph.capture.call_args.kwargs
        assert capture['distinct_id'] == email_subscriber_distinct_id(sub.email)
        assert mock_ph.identify.call_args.kwargs['properties']['brief_subscriber_id'] == sub.id


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


def test_event_uuid_from_insert_id_is_stable_uuid5():
    from app.lib.posthog_utils import event_uuid_from_insert_id

    first = event_uuid_from_insert_id('dqr:42:email_vote_confirmed')
    second = event_uuid_from_insert_id('dqr:42:email_vote_confirmed')
    other = event_uuid_from_insert_id('dqr:43:email_vote_confirmed')
    assert first == second
    assert first != other
    uuid.UUID(first)


def test_safe_capture_passes_deterministic_uuid_for_insert_id(app):
    """posthog-python 7.x dedupes on capture(uuid=), not $insert_id in properties."""
    captured = []

    class _Client:
        project_api_key = 'phc_x'

        def capture(self, **kwargs):
            captured.append(kwargs)

    from app.lib.posthog_utils import event_uuid_from_insert_id, safe_posthog_capture

    with app.test_request_context('/', headers={'User-Agent': 'Mozilla/5.0'}):
        safe_posthog_capture(
            posthog_client=_Client(),
            distinct_id='subscriber:abc',
            event='email_vote_confirmed',
            insert_id='dqr:9:email_vote_confirmed',
        )
    assert len(captured) == 1
    assert captured[0]['properties']['$insert_id'] == 'dqr:9:email_vote_confirmed'
    assert captured[0]['uuid'] == event_uuid_from_insert_id('dqr:9:email_vote_confirmed')


def test_safe_system_capture_passes_deterministic_uuid_for_insert_id():
    import posthog as real_posthog

    captured = []

    from app.lib.posthog_utils import event_uuid_from_insert_id, safe_system_capture

    with patch('app.lib.posthog_utils._drain_posthog_client'):
        with patch.object(real_posthog, 'project_api_key', 'phc_x'):
            with patch.object(real_posthog, 'api_key', 'phc_x'):
                with patch.object(real_posthog, 'capture', side_effect=lambda **kw: captured.append(kw)):
                    safe_system_capture(
                        'daily_brief_sent',
                        properties={'cadence': 'daily'},
                        insert_id='daily_brief_sent:daily:42',
                    )
    assert len(captured) == 1
    assert captured[0]['distinct_id'] == 'system'
    assert captured[0]['properties']['$insert_id'] == 'daily_brief_sent:daily:42'
    assert captured[0]['uuid'] == event_uuid_from_insert_id('daily_brief_sent:daily:42')


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


def test_user_logged_in_includes_is_authenticated(app):
    from app.auth.routes import _finalize_login
    from app.models import User

    app.config['POSTHOG_API_KEY'] = PH_KEY

    with app.app_context():
        with patch('app.auth.routes._track_posthog') as track:
            with patch('app.auth.routes.login_user'):
                with patch('app.auth.routes.record_event'):
                    with patch('app.auth.routes.merge_anonymous_statement_votes_into_user'):
                        user = User(email='login@example.com', username='loginuser')
                        user.id = 99
                        with app.test_request_context('/login'):
                            _finalize_login(user, method='password')
                        track.assert_called_once()
                        props = track.call_args[0][2]
                        assert props['is_authenticated'] is True


def test_brief_reactivate_fires_daily_brief_subscribed(app, db):
    from app.brief.subscription import process_subscription
    from app.models import DailyBriefSubscriber

    app.config['POSTHOG_API_KEY'] = PH_KEY

    with app.app_context():
        db.create_all()
        sub = DailyBriefSubscriber(
            email='returning@example.com',
            status='unsubscribed',
            timezone='UTC',
            preferred_send_hour=18,
        )
        db.session.add(sub)
        db.session.commit()

        with patch('app.brief.subscription.ResendClient') as resend_cls:
            resend_cls.return_value.send_welcome.return_value = True
            with patch('app.lib.posthog_utils.safe_posthog_capture') as capture:
                with app.test_request_context('/brief/subscribe'):
                    result = process_subscription(
                        'returning@example.com',
                        track_posthog=True,
                        source='dashboard',
                    )
        assert result['status'] == 'reactivated'
        capture.assert_called_once()
        assert capture.call_args.kwargs['event'] == 'daily_brief_subscribed'
        assert capture.call_args.kwargs['durable'] is True
        assert capture.call_args.kwargs['insert_id'] == f'brief_sub:{sub.id}:reactivated'
        props = capture.call_args.kwargs['properties']
        assert props['subscription_status'] == 'reactivated'
        assert props['reactivation'] is True
        assert props['signup_channel'] == 'dashboard'
        assert 'email' not in props
        assert props['brief_subscriber_id'] is not None


def test_game_run_started_includes_brief_email_source(app):
    from app.game.analytics import track_game_event
    from app.lib.subscriber_identity import SUBSCRIBER_REF_COOKIE, set_subscriber_ref_cookie
    from app.models.game import GameRun
    from flask import Response

    run = GameRun(
        uuid='brief-src-uuid',
        scenario_slug='debt-inherited',
        mode='quick',
        session_fingerprint='fp-brief',
        turn_index=0,
        total_turns=10,
    )
    browser_ua = {'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36'}

    with app.test_request_context('/game/quick/debt-inherited', headers=browser_ua):
        resp = Response()
        set_subscriber_ref_cookie(resp, brief_subscriber_id=7)
        cookie_header = resp.headers.get('Set-Cookie', '')
        cookie_value = cookie_header.split(f'{SUBSCRIBER_REF_COOKIE}=', 1)[1].split(';', 1)[0]

    with patch('app.game.analytics.safe_posthog_capture') as capture:
        with app.test_request_context(
            '/game/quick/debt-inherited',
            headers={**browser_ua, 'Cookie': f'{SUBSCRIBER_REF_COOKIE}={cookie_value}'},
        ):
            track_game_event(run, 'game_run_started')
        props = capture.call_args.kwargs['properties']
        assert props['source'] == 'brief_email'


def test_journey_started_fires_without_posthog_cookie(app):
    """First-vote started must not require the JS cookie (July 2026 regression)."""
    from unittest.mock import MagicMock, patch

    from app.programmes.journey_analytics import capture_journey_started

    programme = MagicMock()
    programme.id = 9
    programme.slug = 'humanity-big-questions'
    programme.name = "Humanity's big questions"
    programme.geographic_scope = 'global'

    fake_ph = MagicMock()
    fake_ph.project_api_key = 'phc_x'
    browser_ua = {'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36'}

    with patch('app.programmes.journey_analytics._posthog', fake_ph):
        with patch('app.programmes.journey_analytics.safe_posthog_capture') as cap:
            with patch('app.programmes.journey_analytics.cache') as cache_mock:
                cache_mock.get.return_value = None
                with app.test_request_context('/discussions/x', headers=browser_ua):
                    capture_journey_started(programme, total_steps=8)
                cap.assert_called_once()
                assert cap.call_args.kwargs['event'] == 'journey_started'
                assert cap.call_args.kwargs['durable'] is True


def test_journey_vote_events_started_then_step_completed(app):
    from unittest.mock import MagicMock, patch

    from app.programmes.journey_analytics import capture_journey_vote_events

    programme = MagicMock()
    programme.id = 9
    programme.slug = 'humanity-big-questions'
    programme.name = "Humanity's big questions"
    programme.geographic_scope = 'global'

    discussion = MagicMock()
    discussion.programme_id = 9
    discussion.has_native_statements = True
    discussion.id = 42
    discussion.slug = 'theme-one'
    discussion.programme_theme = 'T1'
    discussion.programme = programme

    fake_ph = MagicMock()
    fake_ph.project_api_key = 'phc_x'

    with patch('app.programmes.journey_analytics._posthog', fake_ph):
        with patch(
            'app.programmes.journey.is_guided_journey_programme', return_value=True
        ):
            with patch(
                'app.programmes.journey.ordered_journey_discussions',
                return_value=[discussion],
            ):
                with patch(
                    'app.programmes.journey_analytics.capture_journey_started'
                ) as started:
                    with patch(
                        'app.programmes.journey_analytics.safe_posthog_capture'
                    ) as cap:
                        with patch(
                            'app.programmes.journey_analytics.cache'
                        ) as cache_mock:
                            cache_mock.get.return_value = None
                            with patch(
                                'app.programmes.journey.build_journey_progress',
                                return_value={'is_journey_complete': False},
                            ):
                                with app.test_request_context('/discussions/x'):
                                    with patch(
                                        'app.programmes.journey_analytics._theme_vote_progress',
                                        return_value=(1, 2),
                                    ):
                                        capture_journey_vote_events(discussion)
                                    started.assert_called_once()
                                    cap.assert_not_called()

                                    with patch(
                                        'app.programmes.journey_analytics._theme_vote_progress',
                                        return_value=(2, 2),
                                    ):
                                        capture_journey_vote_events(discussion)
                                    assert cap.call_count == 1
                                    assert cap.call_args.kwargs['event'] == 'journey_step_completed'
                                    assert cap.call_args.kwargs['durable'] is True


def test_journey_vote_events_fires_completed_when_all_themes_done(app):
    from unittest.mock import MagicMock, patch

    from app.programmes.journey_analytics import capture_journey_vote_events

    programme = MagicMock()
    programme.id = 9
    programme.slug = 'humanity-big-questions'
    programme.name = "Humanity's big questions"
    programme.geographic_scope = 'global'

    discussion = MagicMock()
    discussion.programme_id = 9
    discussion.has_native_statements = True
    discussion.id = 42
    discussion.slug = 'theme-one'
    discussion.programme_theme = 'T1'
    discussion.programme = programme

    fake_ph = MagicMock()
    fake_ph.project_api_key = 'phc_x'

    with patch('app.programmes.journey_analytics._posthog', fake_ph):
        with patch(
            'app.programmes.journey.is_guided_journey_programme', return_value=True
        ):
            with patch(
                'app.programmes.journey.ordered_journey_discussions',
                return_value=[discussion],
            ):
                with patch(
                    'app.programmes.journey_analytics.capture_journey_started'
                ):
                    with patch(
                        'app.programmes.journey_analytics.safe_posthog_capture',
                        return_value=True,
                    ) as cap:
                        with patch(
                            'app.programmes.journey_analytics.cache'
                        ) as cache_mock:
                            cache_mock.get.return_value = None
                            with patch(
                                'app.programmes.journey.build_journey_progress',
                                return_value={'is_journey_complete': True},
                            ):
                                with patch(
                                    'app.programmes.journey_analytics._theme_vote_progress',
                                    return_value=(2, 2),
                                ):
                                    with app.test_request_context('/discussions/x'):
                                        capture_journey_vote_events(discussion)
                            events = [c.kwargs['event'] for c in cap.call_args_list]
                            assert 'journey_step_completed' in events
                            assert 'journey_completed' in events


def test_journey_completed_skipped_unless_visitor_finished(app):
    """Recap GETs from crawlers must not count as completions."""
    from unittest.mock import MagicMock, patch

    from app.programmes.journey_analytics import capture_journey_completed

    programme = MagicMock()
    programme.id = 9
    programme.slug = 'humanity-big-questions'
    programme.name = "Humanity's big questions"
    programme.geographic_scope = 'global'

    fake_ph = MagicMock()
    fake_ph.project_api_key = 'phc_x'

    with patch('app.programmes.journey_analytics._posthog', fake_ph):
        with patch('app.programmes.journey_analytics.safe_posthog_capture') as cap:
            with patch('app.programmes.journey_analytics.cache') as cache_mock:
                cache_mock.get.return_value = None
                with app.test_request_context('/programmes/x/recap'):
                    capture_journey_completed(programme, is_complete=False, total_steps=8)
                    cap.assert_not_called()
                    capture_journey_completed(programme, is_complete=True, total_steps=8)
                    cap.assert_called_once()
                    assert cap.call_args.kwargs['event'] == 'journey_completed'
                    assert cap.call_args.kwargs['durable'] is True


def test_journey_completed_skipped_on_prefetch(app):
    from unittest.mock import MagicMock, patch

    from app.programmes.journey_analytics import capture_journey_completed

    programme = MagicMock()
    programme.id = 9
    programme.slug = 'humanity-big-questions'
    programme.name = "Humanity's big questions"
    programme.geographic_scope = 'global'

    fake_ph = MagicMock()
    fake_ph.project_api_key = 'phc_x'

    with patch('app.programmes.journey_analytics._posthog', fake_ph):
        with patch('app.programmes.journey_analytics.safe_posthog_capture') as cap:
            with app.test_request_context(
                '/programmes/x/recap',
                headers={'Sec-Purpose': 'prefetch'},
            ):
                capture_journey_completed(programme, is_complete=True, total_steps=8)
                cap.assert_not_called()


def test_game_run_completed_sends_insert_id_and_durable_flag(app):
    from unittest.mock import patch

    from app.game.analytics import track_game_event
    from app.models.game import GameRun

    run = GameRun(
        uuid='complete-uuid',
        scenario_slug='s',
        mode='daily',
        session_fingerprint='fp-1',
        turn_index=10,
        total_turns=10,
    )
    browser_ua = {'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36'}

    with patch('app.game.analytics.safe_posthog_capture') as capture:
        with app.test_request_context('/play/choice', headers=browser_ua):
            track_game_event(
                run,
                'game_run_completed',
                durable=True,
                insert_id='game_run_completed:complete-uuid',
            )
        assert capture.call_args.kwargs['durable'] is True
        assert capture.call_args.kwargs['insert_id'] == 'game_run_completed:complete-uuid'


def test_daily_run_persist_false_creates_no_row_or_event(app, db):
    from unittest.mock import patch

    from app.game.services.daily_service import scheduled_scenario_slug
    from app.game.services.run_service import get_or_start_daily_run
    from app.models.game import GameRun

    with app.app_context():
        db.create_all()
        before = GameRun.query.count()
        with patch('app.game.services.run_service.track_game_event') as track:
            run = get_or_start_daily_run(
                scenario_slug=scheduled_scenario_slug(),
                user_id=None,
                session_fingerprint='fp-crawler-daily',
                persist=False,
            )
            assert track.call_count == 0
        assert run.uuid
        assert GameRun.query.count() == before


def test_partner_embed_uses_visitor_identity_and_omits_ip(app):
    """Embed views must not collapse onto partner:<ref> or send client IPs."""
    captured = []

    def _capture(**kwargs):
        captured.append(kwargs)
        return True

    client_id = 'a' * 64
    app.config['POSTHOG_API_KEY'] = PH_KEY
    with patch('app.lib.posthog_utils.safe_posthog_capture', side_effect=_capture):
        with app.test_request_context(
            '/embed/1?ref=acme',
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                'X-Forwarded-For': '203.0.113.9',
                'Cookie': f'ss_voter_client_id={client_id}',
            },
        ):
            from app.api.utils import track_partner_event

            track_partner_event('partner_embed_loaded', {'discussion_id': 1})

    assert len(captured) == 1
    assert not str(captured[0]['distinct_id']).startswith('partner:')
    props = captured[0]['properties']
    assert 'ip_address' not in props
    assert '203.0.113.9' not in str(props)
    assert captured[0]['insert_id']
    assert captured[0]['insert_id'].startswith('partner_embed_loaded:acme:')


def test_partner_api_event_keeps_partner_ref_identity(app):
    captured = []

    def _capture(**kwargs):
        captured.append(kwargs)
        return True

    app.config['POSTHOG_API_KEY'] = PH_KEY
    with patch('app.lib.posthog_utils.safe_posthog_capture', side_effect=_capture):
        with app.test_request_context(
            '/api/v1/snapshot?ref=acme',
            headers={'User-Agent': 'partner-sdk/1.0'},
        ):
            from app.api.utils import track_partner_event

            track_partner_event('partner_api_snapshot')

    assert captured[0]['distinct_id'] == 'partner:acme'


def test_social_click_skips_when_identity_missing(app):
    from flask import request as flask_request
    import posthog as real_posthog

    with patch.object(real_posthog, 'project_api_key', 'phk_test'):
        with patch('app.lib.posthog_utils.resolve_request_distinct_id', return_value=None):
            with patch('app.lib.posthog_utils.safe_posthog_capture') as capture:
                with app.test_request_context(
                    '/discussions/1?utm_source=twitter',
                    headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Referer': 'https://twitter.com/x?token=secret',
                    },
                ):
                    from app.trending.conversion_tracking import track_social_click

                    track_social_click(flask_request, user_id=None)
    capture.assert_not_called()


def test_social_click_strips_referer_query_and_sets_insert_id(app):
    from flask import request as flask_request
    import posthog as real_posthog

    captured = []

    def _capture(**kwargs):
        captured.append(kwargs)
        return True

    with patch.object(real_posthog, 'project_api_key', 'phk_test'):
        with patch('app.lib.posthog_utils.resolve_request_distinct_id', return_value='anon-fp-1'):
            with patch('app.lib.posthog_utils.safe_posthog_capture', side_effect=_capture):
                with app.test_request_context(
                    '/discussions/1?utm_source=twitter&utm_campaign=civic',
                    headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Referer': 'https://twitter.com/x?token=secret',
                    },
                ):
                    from app.trending.conversion_tracking import track_social_click

                    track_social_click(flask_request, user_id=None)

    assert len(captured) == 1
    assert captured[0]['event'] == 'social_post_clicked'
    assert 'token=secret' not in (captured[0]['properties'] or {}).get('referer', '')
    assert captured[0]['insert_id']
    assert 'anon-fp-1' in captured[0]['insert_id']


def test_briefing_track_posthog_hashes_email_distinct_ids(app):
    from app.lib.posthog_utils import email_subscriber_distinct_id

    captured = []

    class _Client:
        project_api_key = 'phk_test'

        def capture(self, **kwargs):
            captured.append(kwargs)

        def identify(self, **kwargs):
            pass

    with patch('app.briefing.routes.posthog', _Client()):
        with app.test_request_context('/', headers={'User-Agent': 'Mozilla/5.0'}):
            from app.briefing.routes import _track_posthog

            _track_posthog(
                'briefing_recipient_unsubscribed',
                'person@example.com',
                {'recipient_id': 9},
                insert_id='briefing_recipient_unsubscribed:9',
            )

    assert len(captured) == 1
    assert captured[0]['distinct_id'] == email_subscriber_distinct_id('person@example.com')
    assert 'person@example.com' not in captured[0]['distinct_id']


def test_capture_statement_voted_email_source_insert_id(app, db):
    from app.discussions.statements import capture_statement_voted
    from app.models import Discussion, Statement

    with app.app_context():
        db.create_all()
        discussion = Discussion(
            title='Email sync vote',
            slug='email-sync-vote',
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.commit()
        statement = Statement(
            discussion_id=discussion.id,
            content='A claim long enough to store as a statement.',
            statement_type='claim',
        )
        db.session.add(statement)
        db.session.commit()

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'
        with patch('app.discussions.statements.posthog', mock_ph):
            with app.test_request_context('/', headers={'User-Agent': 'Mozilla/5.0'}):
                capture_statement_voted(
                    statement,
                    1,
                    distinct_id='subscriber:abc',
                    source='email_vote',
                )

        assert mock_ph.capture.call_args.kwargs['event'] == 'statement_voted'
        props = mock_ph.capture.call_args.kwargs['properties']
        assert props['source'] == 'email_vote'
        assert props['$insert_id'] == f'statement_voted:{statement.id}:subscriber:abc:1'
