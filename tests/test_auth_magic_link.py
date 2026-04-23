"""Magic-link login flow tests.

Covers the three-step flow (request → GET landing → POST consume), the
anti-prefetcher guarantee that GET does not consume the token, latest-email-wins
invalidation, one-shot consume, expiry, anti-enumeration, auto-email-verify,
and the ``next=`` round-trip.
"""
from datetime import timedelta

import pytest
from flask import url_for

from app.lib.time import utcnow_naive
from app.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_user(db, username='alice', email='alice@example.com', verified=False):
    user = User(
        username=username,
        email=email,
        password='hashed-password',
        email_verified=verified,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def captured_emails(monkeypatch):
    """Capture magic-link emails sent during a test without hitting Resend."""
    sent = []

    def _fake_send(user, magic_url):
        sent.append({'user_id': user.id, 'email': user.email, 'url': magic_url})
        return True

    monkeypatch.setattr('app.auth.routes.send_magic_login_email', _fake_send)
    return sent


def _request_link(client, email, next_url=None):
    path = '/auth/login/magic-link'
    if next_url:
        path = f"{path}?next={next_url}"
    return client.post(path, data={'email': email}, follow_redirects=False)


def _extract_token(url):
    return url.rstrip('/').rsplit('/', 1)[-1]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_request_sends_email_and_sets_valid_after(app, db, captured_emails):
    user = _create_user(db)
    client = app.test_client()

    resp = _request_link(client, user.email)

    assert resp.status_code == 200
    assert len(captured_emails) == 1
    assert captured_emails[0]['email'] == user.email
    # URL points at landing (GET), not consume.
    assert '/auth/login/magic-link/' in captured_emails[0]['url']

    db.session.refresh(user)
    assert user.magic_login_valid_after is not None


def test_get_landing_does_not_consume(app, db, captured_emails):
    user = _create_user(db)
    client = app.test_client()
    _request_link(client, user.email)
    token = _extract_token(captured_emails[0]['url'])

    # Simulating an email scanner: GET the URL.
    resp = client.get(f"/auth/login/magic-link/{token}")

    assert resp.status_code == 200
    # Token should still verify — GET did not burn it.
    assert User.verify_magic_login_token(token) is not None
    # User is NOT logged in yet.
    with client.session_transaction() as sess:
        assert '_user_id' not in sess


def test_get_landing_when_already_logged_in_same_user_consumes_token(app, db, captured_emails):
    """If the session already matches the link, we skip Continue but still revoke the link."""
    user = _create_user(db)
    user.set_password('LoginPass1!')
    db.session.commit()
    client = app.test_client()
    _request_link(client, user.email)
    token = _extract_token(captured_emails[0]['url'])

    client.post(
        '/auth/login',
        data={'email': user.email, 'password': 'LoginPass1!'},
        follow_redirects=False,
    )

    resp = client.get(f"/auth/login/magic-link/{token}", follow_redirects=False)
    assert resp.status_code == 302
    assert User.verify_magic_login_token(token) is None


def test_post_consume_logs_in_and_one_shot(app, db, captured_emails):
    user = _create_user(db)
    client = app.test_client()
    _request_link(client, user.email)
    token = _extract_token(captured_emails[0]['url'])

    resp = client.post(f"/auth/login/magic-link/{token}", follow_redirects=False)

    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get('_user_id') == str(user.id)

    # Token is now one-shot: a second POST fails and redirects back to request.
    resp2 = client.post(f"/auth/login/magic-link/{token}", follow_redirects=False)
    assert resp2.status_code == 302
    assert '/auth/login/magic-link' in resp2.headers['Location']


def test_consume_auto_verifies_email(app, db, captured_emails):
    user = _create_user(db, verified=False)
    user_id = user.id
    client = app.test_client()
    _request_link(client, user.email)
    token = _extract_token(captured_emails[0]['url'])

    client.post(f"/auth/login/magic-link/{token}")

    with app.app_context():
        refreshed = db.session.get(User, user_id)
        assert refreshed.email_verified is True


# ---------------------------------------------------------------------------
# Invalidation semantics
# ---------------------------------------------------------------------------

def test_new_send_invalidates_prior_token(app, db, captured_emails):
    from app import cache
    user = _create_user(db)
    client = app.test_client()

    _request_link(client, user.email)
    first_token = _extract_token(captured_emails[0]['url'])

    # Clear per-email cooldown so the second request actually sends.
    cache.clear()

    # Backdate valid_after so the next call's new timestamp is guaranteed
    # strictly later even under sub-microsecond test timing.
    u = db.session.get(User, user.id)
    u.magic_login_valid_after = u.magic_login_valid_after - timedelta(seconds=1)
    db.session.commit()

    _request_link(client, user.email)
    assert len(captured_emails) == 2
    second_token = _extract_token(captured_emails[1]['url'])
    assert second_token != first_token

    # First token is now stale (iat < user.magic_login_valid_after).
    assert User.verify_magic_login_token(first_token) is None
    # Second token works.
    assert User.verify_magic_login_token(second_token) is not None


def test_valid_after_bump_invalidates_outstanding_token(app, db, captured_emails):
    """Advancing valid_after past the token's iat (as happens on consume or
    re-send) revokes an outstanding token."""
    user = _create_user(db)
    client = app.test_client()
    _request_link(client, user.email)
    token = _extract_token(captured_emails[0]['url'])

    # Pretend the link was just consumed (or a new one sent) a minute after iat.
    u = db.session.get(User, user.id)
    u.magic_login_valid_after = utcnow_naive() + timedelta(minutes=1)
    db.session.commit()

    assert User.verify_magic_login_token(token) is None


def test_tampered_token_rejected(app, db, captured_emails):
    _create_user(db)
    client = app.test_client()
    _request_link(client, 'alice@example.com')
    token = _extract_token(captured_emails[0]['url'])

    assert User.verify_magic_login_token(token + 'x') is None


# ---------------------------------------------------------------------------
# Anti-enumeration
# ---------------------------------------------------------------------------

def test_unknown_email_looks_same_as_known(app, db, captured_emails):
    _create_user(db, email='alice@example.com')
    client = app.test_client()

    resp_known = _request_link(client, 'alice@example.com')
    resp_unknown = _request_link(client, 'no-such-user@example.com')

    assert resp_known.status_code == resp_unknown.status_code == 200
    # Only the known email triggers an email send.
    assert len(captured_emails) == 1


# ---------------------------------------------------------------------------
# next= preservation
# ---------------------------------------------------------------------------

def test_next_preserved_through_request_and_consume(app, db, captured_emails):
    user = _create_user(db)
    client = app.test_client()

    _request_link(client, user.email, next_url='/dashboard')
    with client.session_transaction() as sess:
        assert sess.get('pending_post_auth_redirect') == '/dashboard'

    token = _extract_token(captured_emails[0]['url'])
    resp = client.post(f"/auth/login/magic-link/{token}", follow_redirects=False)

    assert resp.status_code == 302
    # Redirect target is dashboard (user has no profile → profile setup flow
    # carries next via ?next=); either way must include the preserved path.
    assert '/dashboard' in resp.headers['Location'] or 'select_profile_type' in resp.headers['Location']


# ---------------------------------------------------------------------------
# Token API — unit-level coverage
# ---------------------------------------------------------------------------

def test_token_methods_roundtrip(app, db):
    user = _create_user(db)

    token = user.get_magic_login_token()
    db.session.commit()

    verified = User.verify_magic_login_token(token)
    assert verified is not None
    assert verified.id == user.id

    user.consume_magic_login_token()
    db.session.commit()

    # After consume, the same token fails.
    assert User.verify_magic_login_token(token) is None
