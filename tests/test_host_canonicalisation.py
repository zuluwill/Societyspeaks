"""Canonical-host redirect and production session-store policy.

The Render origin (*.onrender.com) is publicly reachable; requests there must
redirect to the canonical domain on every method — including POSTs, which
means the redirect has to outrank CSRF protection — while /health stays
answerable for Render's health checks.
"""
import os

import pytest


ONRENDER = 'https://societyspeaks-web.onrender.com'


def test_get_redirects_to_canonical_host(app):
    client = app.test_client()
    resp = client.get('/auth/login', base_url=ONRENDER)
    assert resp.status_code == 301
    assert resp.headers['Location'].startswith('https://societyspeaks.io/auth/login')


def test_query_string_survives_redirect(app):
    client = app.test_client()
    resp = client.get('/search?q=housing', base_url=ONRENDER)
    assert resp.status_code == 301
    assert resp.headers['Location'] == 'https://societyspeaks.io/search?q=housing'


def test_post_redirects_with_308_even_with_csrf_enabled(app):
    """The redirect must run before CSRF, or onrender POSTs 400 instead."""
    app.config['WTF_CSRF_ENABLED'] = True
    client = app.test_client()

    resp = client.post('/auth/login', base_url=ONRENDER, data={'email': 'x'})
    assert resp.status_code == 308
    assert resp.headers['Location'].startswith('https://societyspeaks.io/auth/login')

    # CSRF is genuinely active — the same POST on the canonical host is rejected.
    canonical = client.post(
        '/auth/login', base_url='https://societyspeaks.io', data={'email': 'x'}
    )
    assert canonical.status_code == 400


def test_health_is_exempt_for_render_checks(app):
    client = app.test_client()
    resp = client.get('/health', base_url=ONRENDER)
    assert resp.status_code == 200


def test_canonical_host_untouched(app):
    client = app.test_client()
    resp = client.get('/health', base_url='https://societyspeaks.io')
    assert resp.status_code == 200


def test_production_boot_fails_when_session_redis_unreachable(monkeypatch):
    """A Redis blip at boot must fail the boot in production, never silently
    pin the instance to ephemeral filesystem sessions."""
    from config import Config

    class _FailingRedis:
        def ping(self):
            raise ConnectionError('redis unreachable')

    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
    monkeypatch.setattr(Config, 'SQLALCHEMY_ENGINE_OPTIONS', {'pool_pre_ping': True})
    monkeypatch.setattr(Config, 'RATELIMIT_STORAGE_URL', 'memory://')
    monkeypatch.setattr(Config, 'SESSION_REDIS', _FailingRedis(), raising=False)
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('DEPLOYED_PRODUCTION', '1')
    monkeypatch.setenv('DISABLE_SCHEDULER', '1')

    from app import create_app

    with pytest.raises(RuntimeError, match='Redis session ping failed'):
        create_app()
