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
        context={
            'days_remaining': 3,
            'manage_billing_url': 'https://example.com/billing/card-update',
            'pricing_url': 'https://example.com/pricing#plans',
        },
        client=client,
    )

    assert result is True
    assert len(render_calls) == 1
    template_name, kwargs = render_calls[0]
    assert template_name == 'emails/trial_ending.html'
    # Templates receive the friendly display name (derived via
    # app.lib.user_display.friendly_display_name), not the raw username —
    # 'alice@example.com' → 'Alice' so the greeting in trial emails is
    # title-cased even when the User row's username is lowercase.
    assert kwargs['username'] == 'Alice'
    assert kwargs['base_url'] == client.base_url
    assert kwargs['days_remaining'] == 3
    assert kwargs['manage_billing_url'] == 'https://example.com/billing/card-update'
    assert kwargs['pricing_url'] == 'https://example.com/pricing#plans'
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

    result = resend_client.send_trial_ending_email(user, days_remaining=5)

    assert result is True
    assert call_count['get_client'] == 1
    assert len(helper_calls) == 1
    _, template, subject, context, helper_client = helper_calls[0]
    assert template == 'emails/trial_ending.html'
    assert '5 days' in subject
    assert context['manage_billing_url'] == f'{client.base_url}/billing/card-update'
    assert context['pricing_url'] == f'{client.base_url}/briefings/landing#pricing'
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
    assert subject == "We've paused your briefings — come back any time"
    assert context['resubscribe_url'] == f'{client.base_url}/briefings/landing#pricing'
    assert context['briefing_count'] == 2
    assert helper_client is client


def test_resend_http_post_400_logs_error_for_transactional(monkeypatch):
    """Default path: systemic 400s must stay at ERROR (auth, password reset, etc.)."""
    response = SimpleNamespace(status_code=400, text='bad request')

    monkeypatch.setattr(resend_client.requests, 'post', lambda *a, **k: response)
    warnings = []
    errors = []
    monkeypatch.setattr(resend_client.logger, 'warning', lambda msg: warnings.append(msg))
    monkeypatch.setattr(resend_client.logger, 'error', lambda msg: errors.append(msg))

    _, err = resend_client._resend_http_post('key', {}, resend_client._RESEND_API_URL)

    assert err is not None
    assert errors
    assert not warnings


def test_resend_http_post_400_logs_warning_when_brief_scoped(monkeypatch):
    """Brief batch path opts in to WARNING for per-recipient 400/422 rejects."""
    response = SimpleNamespace(status_code=400, text='bad request')

    monkeypatch.setattr(resend_client.requests, 'post', lambda *a, **k: response)
    warnings = []
    errors = []
    monkeypatch.setattr(resend_client.logger, 'warning', lambda msg: warnings.append(msg))
    monkeypatch.setattr(resend_client.logger, 'error', lambda msg: errors.append(msg))

    _, err = resend_client._resend_http_post(
        'key',
        {},
        resend_client._RESEND_API_URL,
        warn_statuses=frozenset({400, 422}),
    )

    assert err is not None
    assert warnings
    assert not errors


def test_send_with_retry_skips_reserved_example_com_without_calling_resend(monkeypatch):
    client = resend_client.ResendEmailClient.__new__(resend_client.ResendEmailClient)
    client._disabled = False
    client.api_key = 'test-key'
    client.last_message_id = 'stale'
    client.last_send_error = 'stale'

    called = []
    monkeypatch.setattr(
        resend_client,
        'resend_post_with_retry',
        lambda *a, **k: called.append((a, k)) or (True, 'should-not-send'),
    )

    ok = client._send_with_retry(
        {'to': ['qa@example.com'], 'subject': 'Hi', 'html': '<p>x</p>'},
        use_rate_limit=False,
    )
    assert ok is True
    assert called == []
    assert client.last_message_id is None
    assert client.last_send_error is None


def test_resend_post_with_retry_skips_reserved_without_http(monkeypatch):
    posts = []
    monkeypatch.setattr(
        resend_client.requests,
        'post',
        lambda *a, **k: posts.append((a, k)) or SimpleNamespace(status_code=200, json=lambda: {'id': 'x'}),
    )
    ok, msg_id = resend_client.resend_post_with_retry(
        'key',
        {'from': 'a@x.io', 'to': ['qa@example.com'], 'subject': 'Hi'},
    )
    assert ok is True
    assert msg_id is None
    assert posts == []


def test_resend_post_with_retry_sends_after_stripping_reserved(monkeypatch):
    posts = []

    def _fake_post(url, json=None, headers=None, timeout=None):
        posts.append(json)
        return SimpleNamespace(status_code=200, json=lambda: {'id': 're_1'})

    monkeypatch.setattr(resend_client.requests, 'post', _fake_post)
    ok, msg_id = resend_client.resend_post_with_retry(
        'key',
        {'from': 'a@x.io', 'to': ['will@societyspeaks.io', 'qa@example.com'], 'subject': 'Hi'},
    )
    assert ok is True
    assert msg_id == 're_1'
    assert posts[0]['to'] == ['will@societyspeaks.io']
