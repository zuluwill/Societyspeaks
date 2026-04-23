"""Deliverability smoke tests for transactional emails.

Asserts the Resend payloads built by ``ResendEmailClient`` include the signals
that drive Gmail + Outlook spam classification:

    * ``text`` plaintext alternative alongside ``html``
    * ``reply_to`` when ``RESEND_REPLY_TO`` is configured
    * ``X-Entity-Ref-ID`` header for ESP-side dedup of retries
    * transactional-specific From address when
      ``RESEND_TRANSACTIONAL_FROM_EMAIL`` is set (defaults to the shared
      ``from_email`` otherwise)

These are shape tests — they don't hit the Resend API.
"""
import pytest

from app.models import User
from app.resend_client import ResendEmailClient


def _make_user(db, email='alice@example.com', username='alice'):
    user = User(
        username=username,
        email=email,
        password='hashed-password',
        email_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def captured_payload(monkeypatch):
    """Patch the client's send-with-retry and capture the payload it receives."""
    holder = {}

    def _capture(self, email_data, use_rate_limit=True):
        holder['payload'] = email_data
        return True

    monkeypatch.setattr(ResendEmailClient, '_send_with_retry', _capture)
    return holder


def _client(monkeypatch, **env):
    """Build a ResendEmailClient with specific env vars set."""
    monkeypatch.setenv('RESEND_API_KEY', 'test-key')
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return ResendEmailClient()


def test_password_reset_payload_has_html_and_text(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(monkeypatch)

    assert client.send_password_reset(user, 'reset-token-abcdef') is True

    payload = captured_payload['payload']
    assert payload['html'], 'html body missing'
    assert payload['text'], 'plaintext body missing — Gmail penalises HTML-only mail'
    assert 'reset-token-abcdef' in payload['text'], 'plaintext should include the reset URL'


def test_magic_login_payload_has_html_and_text(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(monkeypatch)

    magic_url = 'https://societyspeaks.io/auth/login/magic-link/signed-token-xyz'
    assert client.send_magic_login_link(user, magic_url) is True

    payload = captured_payload['payload']
    assert payload['html']
    assert payload['text']
    assert magic_url in payload['text']


def test_verification_payload_has_html_and_text(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(monkeypatch)

    verify_url = 'https://societyspeaks.io/auth/verify-email/verify-token-123'
    assert client.send_verification_email(user, verify_url) is True

    payload = captured_payload['payload']
    assert payload['html']
    assert payload['text']
    assert verify_url in payload['text']


def test_welcome_payload_has_html_and_text(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(monkeypatch)

    assert client.send_welcome_email(user, verification_url=None) is True

    payload = captured_payload['payload']
    assert payload['html']
    assert payload['text']
    assert 'Society Speaks' in payload['text']


def test_account_activation_payload_has_html_and_text(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(monkeypatch)

    assert client.send_account_activation(user, 'activation-token-abcdef') is True

    payload = captured_payload['payload']
    assert payload['html']
    assert payload['text']
    assert 'activation-token-abcdef' in payload['text']


def test_reply_to_included_when_configured(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(monkeypatch, RESEND_REPLY_TO='hello@societyspeaks.io')

    client.send_password_reset(user, 'tok')

    assert captured_payload['payload']['reply_to'] == 'hello@societyspeaks.io'


def test_reply_to_absent_when_not_configured(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(monkeypatch, RESEND_REPLY_TO=None)

    client.send_password_reset(user, 'tok')

    assert 'reply_to' not in captured_payload['payload']


def test_transactional_from_defaults_to_resend_from(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(
        monkeypatch,
        RESEND_FROM_EMAIL='Society Speaks <hello@brief.societyspeaks.io>',
        RESEND_TRANSACTIONAL_FROM_EMAIL=None,
    )

    client.send_password_reset(user, 'tok')

    assert captured_payload['payload']['from'] == 'Society Speaks <hello@brief.societyspeaks.io>'


def test_transactional_from_overrides_when_set(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(
        monkeypatch,
        RESEND_FROM_EMAIL='Society Speaks <hello@brief.societyspeaks.io>',
        RESEND_TRANSACTIONAL_FROM_EMAIL='Society Speaks <hello@societyspeaks.io>',
    )

    client.send_password_reset(user, 'tok')

    # Transactional override wins — aligns sender domain with the link domain.
    assert captured_payload['payload']['from'] == 'Society Speaks <hello@societyspeaks.io>'


def test_entity_ref_id_header_attached(app, db, monkeypatch, captured_payload):
    user = _make_user(db)
    client = _client(monkeypatch)

    client.send_password_reset(user, 'abcdefghijklmnop1234567890')

    headers = captured_payload['payload'].get('headers', {})
    assert 'X-Entity-Ref-ID' in headers
    assert str(user.id) in headers['X-Entity-Ref-ID']


def test_entity_ref_id_stable_across_retries_of_same_send(app, db, monkeypatch, captured_payload):
    """Same (user, token) produces the same Ref-ID on retry — lets ESPs dedup."""
    user = _make_user(db)
    client = _client(monkeypatch)

    token = 'stable-token-value-0987654321'

    client.send_password_reset(user, token)
    ref_1 = captured_payload['payload']['headers']['X-Entity-Ref-ID']

    client.send_password_reset(user, token)
    ref_2 = captured_payload['payload']['headers']['X-Entity-Ref-ID']

    assert ref_1 == ref_2
