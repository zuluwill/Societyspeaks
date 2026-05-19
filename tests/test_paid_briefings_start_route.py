"""
Route-level tests for the self-serve paid-briefings trial flow.

Covers:
  - GET  /briefings/start          flag off → redirects to landing
  - GET  /briefings/start          flag on, anonymous → renders template
  - GET  /briefings/start          flag on, authed + active sub → dashboard
  - GET  /briefings/start          flag on, authed + no sub → /complete
  - POST /briefings/start          happy path → magic-link sent, inbox page
  - POST /briefings/start          disposable email → generic block
  - POST /briefings/start          unknown template → flash + redirect
  - GET  /briefings/start/complete flag off → /briefings/
  - GET  /briefings/start/complete authed + valid template → creates trial + redirects
"""
from unittest.mock import patch

import pytest

from app.models import User
from app.models.billing import PricingPlan
from app.models.briefing import BriefTemplate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _seed_plan(db):
    plan = PricingPlan(
        code='starter', name='Personal',
        price_monthly=499, price_yearly=4900,
        currency='GBP', is_organisation=False, is_active=True,
    )
    db.session.add(plan)
    db.session.flush()
    return plan


def _seed_template(db, slug='technology-ai-regulation', name='AI & Technology', featured=True):
    tpl = BriefTemplate(
        slug=slug,
        name=name,
        description='AI & tech news from sources you trust',
        category='core_insight',
        audience_type='all',
        is_featured=featured,
        is_active=True,
        default_sources=[],
        default_cadence='daily',
        default_tone='balanced',
        custom_prompt_prefix='Focus on AI.',
        configurable_options={},
        guardrails={'max_items': 8},
    )
    db.session.add(tpl)
    db.session.flush()
    return tpl


def _seed_user(db, username='alice', email='alice@example.com'):
    user = User(
        username=username,
        email=email,
        password='hashed-placeholder',
        email_verified=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


@pytest.fixture
def trial_app(app):
    """app fixture with SELF_SERVE_TRIAL_ENABLED = True."""
    app.config['SELF_SERVE_TRIAL_ENABLED'] = True
    yield app
    app.config['SELF_SERVE_TRIAL_ENABLED'] = False


# ---------------------------------------------------------------------------
# GET /briefings/start
# ---------------------------------------------------------------------------

def test_get_start_flag_off_redirects_to_landing(app, db):
    app.config['SELF_SERVE_TRIAL_ENABLED'] = False
    client = app.test_client()
    resp = client.get('/briefings/start', follow_redirects=False)
    assert resp.status_code == 302
    assert '/briefings/landing' in resp.headers['Location']


def test_get_start_flag_on_renders_template_for_anonymous(trial_app, db):
    with trial_app.app_context():
        _seed_template(db)
        db.session.commit()

    client = trial_app.test_client()
    resp = client.get('/briefings/start', follow_redirects=False)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Form action points at the same route.
    assert '/briefings/start' in body
    # Template radio appears.
    assert 'technology-ai-regulation' in body
    # Email field present.
    assert 'name="email"' in body


def test_get_start_flag_on_authed_with_active_sub_goes_to_dashboard(trial_app, db):
    from app.models.billing import Subscription

    with trial_app.app_context():
        plan = _seed_plan(db)
        _seed_template(db)
        user = _seed_user(db)
        sub = Subscription(
            user_id=user.id, plan_id=plan.id,
            status='active', billing_interval='month',
            extra_data={'trial_source': 'stripe'},
        )
        db.session.add(sub)
        db.session.commit()
        user_id = user.id

    client = trial_app.test_client()
    _login(client, user_id)
    resp = client.get('/briefings/start', follow_redirects=False)
    assert resp.status_code == 302
    assert '/briefings/' in resp.headers['Location']


def test_get_start_flag_on_authed_no_sub_redirects_to_complete(trial_app, db):
    with trial_app.app_context():
        _seed_plan(db)
        _seed_template(db)
        user = _seed_user(db, username='no_sub', email='nosub@example.com')
        db.session.commit()
        user_id = user.id

    client = trial_app.test_client()
    _login(client, user_id)
    resp = client.get('/briefings/start?template=technology-ai-regulation',
                      follow_redirects=False)
    assert resp.status_code == 302
    assert '/briefings/start/complete' in resp.headers['Location']
    assert 'template=technology-ai-regulation' in resp.headers['Location']

    # And the trial-intent flag is set in session for the post-magic-link bypass.
    with client.session_transaction() as sess:
        assert sess.get('briefing_trial_intent') is True


# ---------------------------------------------------------------------------
# POST /briefings/start
# ---------------------------------------------------------------------------

def test_post_start_happy_path_sends_magic_link_and_renders_inbox(trial_app, db):
    with trial_app.app_context():
        _seed_plan(db)
        _seed_template(db)
        db.session.commit()

    client = trial_app.test_client()
    sent = []

    def _fake_send(user, magic_url):
        sent.append({'user_id': user.id, 'email': user.email, 'url': magic_url})
        return True

    with patch('app.briefing.routes.send_magic_login_email', _fake_send, create=True):
        # send_magic_login_email is imported inside the function — patch the
        # source so the late import resolves to our fake.
        with patch('app.resend_client.send_magic_login_email', _fake_send):
            resp = client.post(
                '/briefings/start',
                data={
                    'email': 'newperson@example.com',
                    'template': 'technology-ai-regulation',
                    'csrf_token': 'test',  # CSRF disabled in tests
                },
                follow_redirects=False,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Check your inbox' in body or 'check your inbox' in body.lower()
    assert 'newperson@example.com' in body
    assert len(sent) == 1
    assert sent[0]['email'] == 'newperson@example.com'

    with client.session_transaction() as sess:
        assert sess.get('briefing_trial_intent') is True
        assert sess.get('pending_post_auth_redirect', '').startswith('/briefings/start/complete')

    # And the User was created.
    with trial_app.app_context():
        created = User.query.filter_by(email='newperson@example.com').first()
        assert created is not None
        assert created.email_verified is False


def test_post_start_disposable_email_renders_generic_warning(trial_app, db):
    with trial_app.app_context():
        _seed_plan(db)
        _seed_template(db)
        db.session.commit()

    client = trial_app.test_client()
    resp = client.post(
        '/briefings/start',
        data={
            'email': 'throwaway@mailinator.com',
            'template': 'technology-ai-regulation',
            'csrf_token': 'test',
        },
        follow_redirects=False,
    )
    # Re-renders the start page; no User created, no magic-link sent.
    assert resp.status_code == 200
    with trial_app.app_context():
        assert User.query.filter_by(email='throwaway@mailinator.com').first() is None


def test_post_start_unknown_template_flashes_and_redirects(trial_app, db):
    with trial_app.app_context():
        _seed_plan(db)
        _seed_template(db)
        db.session.commit()

    client = trial_app.test_client()
    resp = client.post(
        '/briefings/start',
        data={
            'email': 'newuser@example.com',
            'template': 'no-such-slug',
            'csrf_token': 'test',
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert '/briefings/start' in resp.headers['Location']
    # No User created (we never reached the find-or-create step).
    with trial_app.app_context():
        assert User.query.filter_by(email='newuser@example.com').first() is None


# ---------------------------------------------------------------------------
# GET /briefings/start/complete
# ---------------------------------------------------------------------------

def test_get_complete_flag_off_redirects_to_briefings_list(app, db):
    app.config['SELF_SERVE_TRIAL_ENABLED'] = False
    with app.app_context():
        user = _seed_user(db, username='off_user', email='offuser@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/briefings/start/complete', follow_redirects=False)
    assert resp.status_code == 302
    assert '/briefings/' in resp.headers['Location']


def test_get_complete_authed_creates_trial_and_redirects_to_briefing(trial_app, db):
    from app.models.briefing import Briefing
    from app.models.billing import Subscription
    from app.briefing.first_brief import FirstBriefResult

    with trial_app.app_context():
        _seed_plan(db)
        _seed_template(db)
        user = _seed_user(db, username='complete_alice', email='completealice@example.com')
        db.session.commit()
        user_id = user.id

    client = trial_app.test_client()
    _login(client, user_id)

    # Mock the sync generator so the test doesn't hit the real LLM.
    fake_result = FirstBriefResult(status='ready', brief_run_id=42, elapsed_s=0.1)
    with patch('app.briefing.routes.generate_first_brief_sync', return_value=fake_result, create=True):
        with patch('app.briefing.first_brief.generate_first_brief_sync', return_value=fake_result):
            resp = client.get('/briefings/start/complete?template=technology-ai-regulation',
                              follow_redirects=False)

    assert resp.status_code == 302
    # Lands on the freshly-created briefing's detail page.
    assert '/briefings/' in resp.headers['Location']

    with trial_app.app_context():
        # Trial subscription created.
        sub = Subscription.query.filter_by(user_id=user_id).first()
        assert sub is not None
        assert sub.status == 'trialing'
        assert (sub.extra_data or {}).get('trial_source') == 'self_serve'
        # Briefing created.
        briefing = Briefing.query.filter_by(owner_type='user', owner_id=user_id).first()
        assert briefing is not None
        assert briefing.status == 'active'
