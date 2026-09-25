"""Account signup stays pending until the confirmation link is opened."""
from urllib.parse import urlparse

from app.models import PendingRegistration, User


def _register(client, monkeypatch, **overrides):
    sent = {}

    def _capture_welcome(user, verification_url=None):
        sent['url'] = verification_url
        sent['email'] = user.email

    monkeypatch.setattr('app.auth.routes.send_welcome_email', _capture_welcome)
    with client.session_transaction() as sess:
        sess['captcha_expected'] = 7
    data = {
        'username': 'newperson',
        'email': 'newperson@example.com',
        'password': 'ValidPass123!',
        'verification': '7',
    }
    data.update(overrides)
    resp = client.post('/auth/register', data=data, follow_redirects=False)
    return resp, sent


def test_register_holds_account_until_email_is_confirmed(app, db, client, monkeypatch):
    resp, sent = _register(client, monkeypatch)
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/auth/check-email')
    assert User.query.filter_by(email='newperson@example.com').first() is None
    pending = PendingRegistration.query.filter_by(email='newperson@example.com').one()
    assert pending.username == 'newperson'

    page = client.get('/auth/check-email')
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'newperson@example.com' in body
    assert 'Check your email' in body

    landing = client.get(urlparse(sent['url']).path, follow_redirects=False)
    assert landing.status_code == 200
    assert b'Create my account' in landing.data
    assert User.query.filter_by(email='newperson@example.com').first() is None

    confirm = client.post(urlparse(sent['url']).path, follow_redirects=False)
    assert confirm.status_code == 302
    user = User.query.filter_by(email='newperson@example.com').one()
    assert user.email_verified is True
    assert PendingRegistration.query.filter_by(email='newperson@example.com').first() is None

    with client.session_transaction() as sess:
        assert sess.get('_user_id') == str(user.id)


def test_unconfirmed_signup_cannot_open_the_dashboard(app, db, client, monkeypatch):
    _register(client, monkeypatch)
    dash = client.get('/auth/dashboard', follow_redirects=False)
    assert dash.status_code in (302, 401)
    if dash.status_code == 302:
        assert '/auth/login' in dash.headers['Location'] or '/auth/check-email' in dash.headers['Location']
    assert User.query.filter_by(email='newperson@example.com').first() is None


def test_magic_link_and_password_reset_resend_confirmation_without_creating_account(app, db, client, monkeypatch):
    sent = {}

    def _capture_verify(user, verification_url):
        sent['url'] = verification_url

    monkeypatch.setattr('app.auth.routes.send_verification_email', _capture_verify)
    _register(client, monkeypatch)

    magic = client.post(
        '/auth/login/magic-link',
        data={'email': 'newperson@example.com'},
        follow_redirects=False,
    )
    assert magic.status_code == 302
    assert magic.headers['Location'].endswith('/auth/check-email')

    reset = client.post(
        '/auth/password-reset',
        data={'email': 'newperson@example.com'},
        follow_redirects=False,
    )
    assert reset.status_code == 302
    assert reset.headers['Location'].endswith('/auth/check-email')
    assert User.query.filter_by(email='newperson@example.com').first() is None
    assert sent.get('url')


def test_login_with_pending_signup_returns_to_check_email(app, db, client, monkeypatch):
    _register(client, monkeypatch)
    resp = client.post(
        '/auth/login',
        data={'email': 'newperson@example.com', 'password': 'ValidPass123!'},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/auth/check-email')
    assert User.query.filter_by(email='newperson@example.com').first() is None
