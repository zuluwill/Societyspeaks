"""The emailed password-reset link must open the reset form and change the password."""
import re
from urllib.parse import urlsplit

from app.models import User
from app.resend_client import ResendEmailClient


def _create_user(db, email='reset@example.com'):
    user = User(username='reset_user', email=email, password='x', email_verified=True)
    user.set_password('old-password-123')
    db.session.add(user)
    db.session.commit()
    return user


def _capture_emails(monkeypatch):
    sent = []

    def _capture(self, email_data, use_rate_limit=True):
        sent.append(email_data)
        return True

    monkeypatch.setenv('RESEND_API_KEY', 'test-key')
    monkeypatch.setattr(ResendEmailClient, '_send_with_retry', _capture)
    return sent


def _reset_path(email_body: str) -> str:
    match = re.search(r'https?://[^\s"\'<>]*/auth/[^\s"\'<>]+', email_body)
    assert match, 'no reset link in the email body'
    return urlsplit(match.group(0)).path


def test_emailed_reset_link_resets_the_password(app, db, monkeypatch):
    user = _create_user(db)
    sent = _capture_emails(monkeypatch)
    client = app.test_client()

    response = client.post('/auth/password-reset', data={'email': user.email})
    assert response.status_code == 302
    assert len(sent) == 1, 'exactly one reset email should be sent'

    text_path = _reset_path(sent[0]['text'])
    html_path = _reset_path(sent[0]['html'])
    assert text_path == html_path, 'plaintext and HTML parts must carry the same link'

    form = client.get(text_path)
    assert form.status_code == 200, f'emailed link {text_path} did not open the reset form'
    assert b'new_password' in form.data

    done = client.post(text_path, data={'new_password': 'brand-new-password-456'})
    assert done.status_code == 302
    assert done.headers['Location'].endswith('/auth/login')

    db.session.expire_all()
    refreshed = db.session.get(User, user.id)
    assert refreshed.check_password('brand-new-password-456')
    assert not refreshed.check_password('old-password-123')


def test_reset_link_uses_the_configured_email_domain(app, db, monkeypatch):
    user = _create_user(db)
    sent = _capture_emails(monkeypatch)
    monkeypatch.setenv('BASE_URL', 'https://societyspeaks.example')

    assert ResendEmailClient().send_password_reset(user, 'tok') is True

    assert 'https://societyspeaks.example/auth/password-reset/tok' in sent[0]['text']
