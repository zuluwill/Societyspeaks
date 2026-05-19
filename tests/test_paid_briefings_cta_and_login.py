"""
Tests for Block A of the world-class paid briefings build.

Covers:
  - personal_briefs_cta_url helper (flag off vs on, with/without template)
  - authenticated GET /auth/login?checkout_plan=... resumes checkout
  - explicit ?next= still wins over checkout_plan
  - existing active subscription suppresses the checkout redirect
  - /billing/pending-checkout consumes session-stashed plan keys on entry

See docs/PAID_BRIEFINGS_WORLD_CLASS_BUILD.md.
"""
from unittest.mock import patch

from app.models import User


def _create_user(db, username='trial_user', email='trial@example.com'):
    user = User(
        username=username,
        email=email,
        password='hashed-password',
        email_verified=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


# ---------------------------------------------------------------------------
# personal_briefs_cta_url
# ---------------------------------------------------------------------------

def test_cta_url_flag_off_points_at_landing_with_utms(app):
    from app.lib.personal_briefs_cta import personal_briefs_cta_url
    app.config['SELF_SERVE_TRIAL_ENABLED'] = False
    with app.test_request_context():
        url = personal_briefs_cta_url(
            'https://example.com',
            utm_source='daily_brief',
            template_slug='technology-ai-regulation',
        )
    assert url.startswith('https://example.com/briefings/landing?')
    assert 'utm_source=daily_brief' in url
    assert 'utm_medium=email' in url
    assert 'utm_campaign=personal_briefs_cta' in url
    # template= must NOT appear when flag is off — landing page doesn't use it.
    assert 'template=' not in url


def test_cta_url_flag_on_points_at_start_with_template(app):
    from app.lib.personal_briefs_cta import personal_briefs_cta_url
    app.config['SELF_SERVE_TRIAL_ENABLED'] = True
    with app.test_request_context():
        url = personal_briefs_cta_url(
            'https://example.com',
            utm_source='daily_brief',
            template_slug='technology-ai-regulation',
        )
    assert url.startswith('https://example.com/briefings/start?')
    assert 'template=technology-ai-regulation' in url
    assert 'utm_source=daily_brief' in url


def test_cta_url_strips_trailing_slash_on_base(app):
    from app.lib.personal_briefs_cta import personal_briefs_cta_url
    app.config['SELF_SERVE_TRIAL_ENABLED'] = False
    with app.test_request_context():
        url = personal_briefs_cta_url('https://example.com/', utm_source='x')
    assert '//briefings' not in url
    assert url.startswith('https://example.com/briefings/')


# ---------------------------------------------------------------------------
# Authenticated login auth-resume
# ---------------------------------------------------------------------------

def test_login_authenticated_with_checkout_plan_redirects_to_pending_checkout(app, db):
    with app.app_context():
        user = _create_user(db)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)

    # No active subscription, so pending_checkout should win.
    with patch('app.auth.routes.get_active_subscription', return_value=None):
        resp = client.get('/auth/login?checkout_plan=starter&checkout_interval=month',
                          follow_redirects=False)

    assert resp.status_code == 302
    assert '/billing/pending-checkout' in resp.headers['Location']
    assert 'plan=starter' in resp.headers['Location']
    assert 'interval=month' in resp.headers['Location']


def test_login_authenticated_with_next_param_beats_checkout_plan(app, db):
    with app.app_context():
        user = _create_user(db, username='nextuser', email='next@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)

    with patch('app.auth.routes.get_active_subscription', return_value=None):
        resp = client.get('/auth/login?checkout_plan=starter&next=/briefings/',
                          follow_redirects=False)

    assert resp.status_code == 302
    # next= should win — no pending_checkout redirect.
    assert '/billing/pending-checkout' not in resp.headers['Location']


def test_login_authenticated_with_active_sub_does_not_redirect_to_checkout(app, db):
    with app.app_context():
        user = _create_user(db, username='paiduser', email='paid@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)

    # Active subscription suppresses the checkout redirect even with checkout_plan param.
    fake_sub = object()
    with patch('app.auth.routes.get_active_subscription', return_value=fake_sub):
        resp = client.get('/auth/login?checkout_plan=starter',
                          follow_redirects=False)

    assert resp.status_code == 302
    assert '/billing/pending-checkout' not in resp.headers['Location']


# ---------------------------------------------------------------------------
# pending_checkout consumes session-stashed plan keys
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Locale-aware default template selection (PostHog-driven routing)
# ---------------------------------------------------------------------------

def test_resolve_default_template_us_locale_returns_ai_tech(app):
    from app.briefing.routes import _resolve_default_template_slug
    with app.test_request_context(headers={'Accept-Language': 'en-US,en;q=0.9'}):
        assert _resolve_default_template_slug() == 'technology-ai-regulation'


def test_resolve_default_template_uk_locale_returns_ai_tech(app):
    from app.briefing.routes import _resolve_default_template_slug
    with app.test_request_context(headers={'Accept-Language': 'en-GB,en;q=0.9'}):
        assert _resolve_default_template_slug() == 'technology-ai-regulation'


def test_resolve_default_template_german_locale_returns_world_affairs(app):
    from app.briefing.routes import _resolve_default_template_slug
    with app.test_request_context(headers={'Accept-Language': 'de-DE,de;q=0.9'}):
        assert _resolve_default_template_slug() == 'world-affairs'


def test_resolve_default_template_dutch_locale_returns_world_affairs(app):
    from app.briefing.routes import _resolve_default_template_slug
    with app.test_request_context(headers={'Accept-Language': 'nl-NL,nl;q=0.9'}):
        assert _resolve_default_template_slug() == 'world-affairs'


def test_resolve_default_template_french_locale_returns_world_affairs(app):
    from app.briefing.routes import _resolve_default_template_slug
    with app.test_request_context(headers={'Accept-Language': 'fr-FR,fr;q=0.9'}):
        assert _resolve_default_template_slug() == 'world-affairs'


def test_resolve_default_template_no_locale_falls_back_to_ai_tech(app):
    from app.briefing.routes import _resolve_default_template_slug
    with app.test_request_context():  # no Accept-Language header
        assert _resolve_default_template_slug() == 'technology-ai-regulation'


def test_resolve_default_template_unknown_locale_falls_back_to_ai_tech(app):
    """A locale we don't have an override for must fall back, not 404."""
    from app.briefing.routes import _resolve_default_template_slug
    with app.test_request_context(headers={'Accept-Language': 'xx-YY'}):
        assert _resolve_default_template_slug() == 'technology-ai-regulation'


def test_pending_checkout_entry_pops_session_checkout_intent(app, db):
    """Even when pending_checkout fails downstream, it should clear the session
    intent on entry — the URL params are the authoritative source."""
    with app.app_context():
        user = _create_user(db, username='checkout_user', email='co@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)

    # Seed the session with stale checkout intent.
    with client.session_transaction() as sess:
        sess['pending_checkout_plan'] = 'starter'
        sess['pending_checkout_interval'] = 'month'

    # Hit pending_checkout with an invalid plan param so it fails fast.
    # The session keys should still be cleared on entry.
    client.get('/billing/pending-checkout?plan=nonexistent_plan_xyz',
               follow_redirects=False)

    with client.session_transaction() as sess:
        assert 'pending_checkout_plan' not in sess
        assert 'pending_checkout_interval' not in sess
