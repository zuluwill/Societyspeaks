"""Resend HTTP retry policy: Cloudflare 52x, compact errors, Retry-After.

Regression for PYTHON-FLASK-DX/JE/JF: api.resend.com returned a Cloudflare
520 HTML page. The client treated 520 as a non-retryable API error, dumped
the HTML into Sentry, and waited ~40 minutes for hourly catch-up.
"""

from types import SimpleNamespace

import pytest

import app.resend_client as resend_client


def _resp(status, text='', headers=None, json_data=None):
    ns = SimpleNamespace(status_code=status, text=text, headers=headers or {})
    if json_data is not None:
        ns.json = lambda: json_data
    else:
        def _not_json():
            raise ValueError('not json')
        ns.json = _not_json
    return ns


_CF_520_HTML = (
    '<!DOCTYPE html><html><head>'
    '<title>resend.com | 520: Web server is returning an unknown error</title>'
    '</head><body>'
    '<span>Cloudflare Ray ID: <strong>a32d9ff5589a5010</strong></span>'
    '</body></html>'
)


@pytest.mark.parametrize("code,expected", [
    (408, True),
    (429, True),
    (500, True),
    (502, True),
    (503, True),
    (504, True),
    (520, True),
    (521, True),
    (522, True),
    (524, True),
    (529, True),
    (530, True),
    (400, False),
    (401, False),
    (403, False),
    (409, False),
    (422, False),
    (501, False),
    (505, False),
])
def test_is_retryable_http_status(code, expected):
    assert resend_client.is_retryable_http_status(code) is expected


def test_compact_cloudflare_html_extracts_title_and_ray():
    body = resend_client.compact_resend_error_body(
        _resp(520, _CF_520_HTML, headers={'cf-ray': 'a32d9ff5589a5010-FRA'})
    )
    assert '<!DOCTYPE' not in body
    assert '<html' not in body
    assert '520' in body
    assert 'cf-ray=a32d9ff5589a5010-FRA' in body


def test_compact_prefers_json_name_and_message():
    body = resend_client.compact_resend_error_body(
        _resp(
            422,
            '{"name":"validation_error"}',
            json_data={'name': 'validation_error', 'message': 'Invalid `to` field'},
        )
    )
    assert body == 'validation_error — Invalid `to` field'


def test_resend_http_post_retries_520_then_succeeds(monkeypatch):
    calls = {'n': 0}
    sleeps = []

    def _fake_post(*_a, **_k):
        calls['n'] += 1
        if calls['n'] == 1:
            return _resp(520, _CF_520_HTML, headers={'cf-ray': 'abc'})
        return _resp(200, '{"id":"re_ok"}', json_data={'id': 're_ok'})

    monkeypatch.setattr(resend_client.requests, 'post', _fake_post)
    monkeypatch.setattr(resend_client.time, 'sleep', lambda s: sleeps.append(s))
    monkeypatch.setattr(resend_client.random, 'random', lambda: 0.0)

    response, err = resend_client._resend_http_post(
        'key', {}, resend_client._RESEND_API_URL,
    )
    assert err is None
    assert response.status_code == 200
    assert calls['n'] == 2
    assert sleeps == [2.0]


def test_resend_http_post_520_exhausts_with_compact_error(monkeypatch):
    posts = []
    errors = []
    warnings = []

    monkeypatch.setattr(
        resend_client.requests,
        'post',
        lambda *_a, **_k: posts.append(1) or _resp(520, _CF_520_HTML),
    )
    monkeypatch.setattr(resend_client.time, 'sleep', lambda _s: None)
    monkeypatch.setattr(resend_client.random, 'random', lambda: 0.0)
    monkeypatch.setattr(resend_client.logger, 'error', lambda msg: errors.append(msg))
    monkeypatch.setattr(resend_client.logger, 'warning', lambda msg: warnings.append(msg))

    response, err = resend_client._resend_http_post(
        'key', {}, resend_client._RESEND_API_URL, max_retries=3,
    )
    assert response is None
    assert err == 'Transient 520 after 3 attempts'
    assert '<!DOCTYPE' not in err
    assert len(posts) == 3
    assert errors
    assert all('<!DOCTYPE' not in e for e in errors)
    assert len(warnings) == 2  # two retries, then ERROR on exhaustion


def test_resend_http_post_520_warn_on_retryable_does_not_error(monkeypatch):
    """Daily-brief path: exhausted 52x is WARNING because catch-up retries."""
    errors = []
    warnings = []
    monkeypatch.setattr(
        resend_client.requests,
        'post',
        lambda *_a, **_k: _resp(520, _CF_520_HTML),
    )
    monkeypatch.setattr(resend_client.time, 'sleep', lambda _s: None)
    monkeypatch.setattr(resend_client.random, 'random', lambda: 0.0)
    monkeypatch.setattr(resend_client.logger, 'error', lambda msg: errors.append(msg))
    monkeypatch.setattr(resend_client.logger, 'warning', lambda msg: warnings.append(msg))

    _, err = resend_client._resend_http_post(
        'key', {}, resend_client._RESEND_API_URL,
        warn_on_retryable=True,
    )
    assert err == 'Transient 520 after 3 attempts'
    assert not errors
    assert any('Transient 520' in w for w in warnings)


def test_resend_http_post_400_html_is_compact_and_not_retried(monkeypatch):
    posts = []
    html = '<!DOCTYPE html><html><head><title>400 Bad Request</title></head></html>'
    monkeypatch.setattr(
        resend_client.requests,
        'post',
        lambda *_a, **_k: posts.append(1) or _resp(400, html),
    )
    monkeypatch.setattr(resend_client.time, 'sleep', lambda _s: pytest.fail('must not retry 400'))

    _, err = resend_client._resend_http_post('key', {}, resend_client._RESEND_API_URL)
    assert len(posts) == 1
    assert err is not None
    assert err.startswith('API error: 400')
    assert '<!DOCTYPE' not in err
    assert '400 Bad Request' in err


def test_resend_http_post_honors_retry_after(monkeypatch):
    sleeps = []
    calls = {'n': 0}

    def _fake_post(*_a, **_k):
        calls['n'] += 1
        if calls['n'] == 1:
            return _resp(429, 'slow down', headers={'Retry-After': '7'})
        return _resp(200, '{}', json_data={'id': 'ok'})

    monkeypatch.setattr(resend_client.requests, 'post', _fake_post)
    monkeypatch.setattr(resend_client.time, 'sleep', lambda s: sleeps.append(s))

    response, err = resend_client._resend_http_post(
        'key', {}, resend_client._RESEND_API_URL,
    )
    assert err is None
    assert response.status_code == 200
    assert sleeps == [7.0]


def test_retry_after_is_capped(monkeypatch):
    wait = resend_client._retry_wait_seconds(
        _resp(429, '', headers={'Retry-After': '999'}),
        attempt=0,
        retry_delay=2.0,
    )
    assert wait == resend_client._MAX_RETRY_WAIT_SECONDS


def test_resend_http_post_does_not_retry_501(monkeypatch):
    posts = []
    monkeypatch.setattr(
        resend_client.requests,
        'post',
        lambda *_a, **_k: posts.append(1) or _resp(501, 'not implemented'),
    )
    monkeypatch.setattr(resend_client.time, 'sleep', lambda _s: pytest.fail('must not retry 501'))

    _, err = resend_client._resend_http_post('key', {}, resend_client._RESEND_API_URL)
    assert len(posts) == 1
    assert '501' in (err or '')
