"""Identity / acquisition analytics — path-agnostic signup + verify events."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.lib.identity_analytics import (
    SIGNUP_METHOD_REGISTER,
    SIGNUP_METHOD_TRIAL_MAGIC_LINK,
    VERIFICATION_METHOD_EMAIL_LINK,
    VERIFICATION_METHOD_MAGIC_LINK,
    track_email_verified,
    track_user_signed_up,
)


def _user(**kwargs):
    defaults = dict(
        id=42,
        username='deepak',
        email='deepakcdo@gmail.com',
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_track_user_signed_up_fires_posthog_and_account_created():
    user = _user()
    ph = MagicMock()
    ph.project_api_key = 'phc_test'

    with patch('app.lib.identity_analytics.record_event') as record:
        with patch('app.lib.identity_analytics.safe_posthog_capture') as capture:
            track_user_signed_up(
                user,
                signup_method=SIGNUP_METHOD_TRIAL_MAGIC_LINK,
                properties={'template_slug': 'technology-ai-regulation', 'utm_source': 'x'},
                source='briefing_trial',
                posthog_client=ph,
            )

    record.assert_called_once()
    assert record.call_args.kwargs['user_id'] == 42
    assert record.call_args.kwargs['source'] == 'briefing_trial'
    assert record.call_args.kwargs['event_metadata']['signup_method'] == SIGNUP_METHOD_TRIAL_MAGIC_LINK

    capture.assert_called_once()
    kwargs = capture.call_args.kwargs
    assert kwargs['event'] == 'user_signed_up'
    assert kwargs['distinct_id'] == '42'
    assert kwargs['properties']['signup_method'] == SIGNUP_METHOD_TRIAL_MAGIC_LINK
    assert kwargs['properties']['template_slug'] == 'technology-ai-regulation'
    assert kwargs['properties']['utm_source'] == 'x'
    assert kwargs['identify_properties']['email'] == 'deepakcdo@gmail.com'
    assert kwargs['identify_properties']['signup_method'] == SIGNUP_METHOD_TRIAL_MAGIC_LINK


def test_track_user_signed_up_skips_internal_when_disabled():
    user = _user()
    with patch('app.lib.identity_analytics.record_event') as record:
        with patch('app.lib.identity_analytics.safe_posthog_capture') as capture:
            track_user_signed_up(
                user,
                signup_method=SIGNUP_METHOD_REGISTER,
                record_internal=False,
                posthog_client=MagicMock(project_api_key='x'),
            )
    record.assert_not_called()
    capture.assert_called_once()


def test_track_user_signed_up_noop_without_user():
    with patch('app.lib.identity_analytics.safe_posthog_capture') as capture:
        track_user_signed_up(None, signup_method=SIGNUP_METHOD_REGISTER)
        track_user_signed_up(SimpleNamespace(id=None), signup_method=SIGNUP_METHOD_REGISTER)
    capture.assert_not_called()


def test_track_email_verified_includes_method():
    user = _user()
    with patch('app.lib.identity_analytics.safe_posthog_capture') as capture:
        track_email_verified(
            user,
            verification_method=VERIFICATION_METHOD_MAGIC_LINK,
            posthog_client=MagicMock(project_api_key='x'),
        )
    kwargs = capture.call_args.kwargs
    assert kwargs['event'] == 'email_verified'
    assert kwargs['properties']['verification_method'] == VERIFICATION_METHOD_MAGIC_LINK
    assert kwargs['properties']['user_id'] == 42


def test_verification_method_vocab_stable():
    # Locked for PostHog insights — rename only with a coordinated dashboard update.
    assert VERIFICATION_METHOD_EMAIL_LINK == 'email_link'
    assert VERIFICATION_METHOD_MAGIC_LINK == 'magic_link'
    assert SIGNUP_METHOD_REGISTER == 'register'
    assert SIGNUP_METHOD_TRIAL_MAGIC_LINK == 'trial_magic_link'


def test_register_fires_user_signed_up_with_signup_method(app, db, monkeypatch):
    """Classic /auth/register must emit the path-agnostic identity event."""
    from app.models import User

    captured = []

    def _fake_capture(*, posthog_client, distinct_id, event, properties=None, identify_properties=None):
        captured.append({
            'event': event,
            'distinct_id': distinct_id,
            'properties': dict(properties or {}),
            'identify_properties': dict(identify_properties or {}),
        })

    monkeypatch.setattr('app.lib.identity_analytics.safe_posthog_capture', _fake_capture)
    monkeypatch.setattr('app.auth.routes.send_welcome_email', lambda *a, **k: None)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['captcha_expected'] = 7
        sess['utm'] = {'utm_source': 'newsletter', 'utm_medium': 'email'}

    resp = client.post(
        '/auth/register',
        data={
            'username': 'classicuser',
            'email': 'classicuser@example.com',
            'password': 'ValidPass123!',
            'verification': '7',
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)

    with app.app_context():
        created = User.query.filter_by(email='classicuser@example.com').first()
        assert created is not None
        created_id = created.id

    signup_events = [e for e in captured if e['event'] == 'user_signed_up']
    assert len(signup_events) == 1
    assert signup_events[0]['distinct_id'] == str(created_id)
    assert signup_events[0]['properties']['signup_method'] == 'register'
    assert signup_events[0]['properties']['utm_source'] == 'newsletter'
    assert signup_events[0]['identify_properties']['signup_method'] == 'register'
    assert signup_events[0]['identify_properties']['email'] == 'classicuser@example.com'
