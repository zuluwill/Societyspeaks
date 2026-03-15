from types import SimpleNamespace

import app.resend_client as resend_client


class _FakeClient:
    def __init__(self):
        self.base_url = 'https://societyspeaks.example'
        self.from_email = 'noreply@societyspeaks.example'
        self.sent = []

    def _send_with_retry(self, email_data, use_rate_limit=False):  # noqa: ARG002
        self.sent.append(email_data)
        return True


def test_send_user_transactional_email_returns_false_without_email(monkeypatch):
    user = SimpleNamespace(username='alice')
    client = _FakeClient()

    logged_errors = []

    monkeypatch.setattr(resend_client.logger, 'error', lambda msg: logged_errors.append(msg))
    monkeypatch.setattr(
        resend_client,
        'get_resend_client',
        lambda: (_ for _ in ()).throw(AssertionError('get_resend_client should not be called')),
    )

    result = resend_client._send_user_transactional_email(
        user=user,
        template='emails/trial_ending.html',
        subject='Test subject',
        context={},
        client=client,
    )

    assert result is False
    assert logged_errors
    assert 'user has no email' in logged_errors[0]
    assert client.sent == []


def test_send_user_transactional_email_uses_given_client_and_renders(monkeypatch):
    user = SimpleNamespace(username='alice', email='alice@example.com')
    client = _FakeClient()

    render_calls = []

    def _fake_render(template, **kwargs):
        render_calls.append((template, kwargs))
        return '<html>ok</html>'

    monkeypatch.setattr(resend_client, 'render_template', _fake_render)
    monkeypatch.setattr(
        resend_client,
        'get_resend_client',
        lambda: (_ for _ in ()).throw(AssertionError('get_resend_client should not be called')),
    )

    result = resend_client._send_user_transactional_email(
        user=user,
        template='emails/trial_ending.html',
        subject='Your subject',
        context={'days_remaining': 3, 'upgrade_url': 'https://example.com/upgrade'},
        client=client,
    )

    assert result is True
    assert len(render_calls) == 1
    template_name, kwargs = render_calls[0]
    assert template_name == 'emails/trial_ending.html'
    assert kwargs['username'] == 'alice'
    assert kwargs['base_url'] == client.base_url
    assert kwargs['days_remaining'] == 3
    assert kwargs['upgrade_url'] == 'https://example.com/upgrade'
    assert len(client.sent) == 1
    assert client.sent[0]['to'] == ['alice@example.com']
    assert client.sent[0]['subject'] == 'Your subject'


def test_send_trial_ending_email_reuses_client_for_fallback_url(monkeypatch):
    user = SimpleNamespace(username='alice', email='alice@example.com')
    client = _FakeClient()
    call_count = {'get_client': 0}
    helper_calls = []

    def _fake_get_client():
        call_count['get_client'] += 1
        return client

    def _fake_helper(user, template, subject, context, client=None):  # noqa: A002
        helper_calls.append((user, template, subject, context, client))
        return True

    monkeypatch.setattr(resend_client, 'get_resend_client', _fake_get_client)
    monkeypatch.setattr(resend_client, '_send_user_transactional_email', _fake_helper)

    result = resend_client.send_trial_ending_email(user, days_remaining=5, upgrade_url=None)

    assert result is True
    assert call_count['get_client'] == 1
    assert len(helper_calls) == 1
    _, template, subject, context, helper_client = helper_calls[0]
    assert template == 'emails/trial_ending.html'
    assert '5 days' in subject
    assert context['upgrade_url'] == f'{client.base_url}/briefings/landing'
    assert context['days_remaining'] == 5
    assert helper_client is client


def test_send_subscription_cancelled_email_reuses_client_for_fallback_url(monkeypatch):
    user = SimpleNamespace(username='alice', email='alice@example.com')
    client = _FakeClient()
    call_count = {'get_client': 0}
    helper_calls = []

    def _fake_get_client():
        call_count['get_client'] += 1
        return client

    def _fake_helper(user, template, subject, context, client=None):  # noqa: A002
        helper_calls.append((user, template, subject, context, client))
        return True

    monkeypatch.setattr(resend_client, 'get_resend_client', _fake_get_client)
    monkeypatch.setattr(resend_client, '_send_user_transactional_email', _fake_helper)

    result = resend_client.send_subscription_cancelled_email(user, resubscribe_url=None, briefing_count=2)

    assert result is True
    assert call_count['get_client'] == 1
    assert len(helper_calls) == 1
    _, template, subject, context, helper_client = helper_calls[0]
    assert template == 'emails/subscription_cancelled.html'
    assert subject == 'Your Society Speaks subscription has ended'
    assert context['resubscribe_url'] == f'{client.base_url}/briefings/landing'
    assert context['briefing_count'] == 2
    assert helper_client is client
