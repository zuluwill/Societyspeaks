"""CDN cache headers and session-skip for static / discovery paths."""

from unittest.mock import Mock, patch

import pytest
from redis import Redis

from app.lib.cdn_cache import (
    STATIC_ASSET_CACHE_CONTROL,
    apply_cdn_cacheable_response_headers,
    is_cdn_cacheable_path,
    should_set_static_cache_control,
    strip_cookie_from_vary,
    strip_set_cookie,
)
from app.lib.session_policy import PolicyRedisSessionInterface


@pytest.mark.parametrize('path, expected', [
    ('/css/output.css', True),
    ('/js/toast.js', True),
    ('/assets/images/hero-optimized.jpg', True),
    ('/favicon.ico', True),
    ('/robots.txt', True),
    ('/sitemap.xml', True),
    ('/llms.txt', True),
    ('/', False),
    ('/discussions/foo', False),
    ('/auth/login', False),
])
def test_is_cdn_cacheable_path(path, expected):
    assert is_cdn_cacheable_path(path) is expected


@pytest.mark.parametrize('path, expected', [
    ('/css/output.css', True),
    ('/assets/images/hero-optimized.jpg', True),
    ('/favicon.ico', True),
    ('/robots.txt', False),  # discovery owns its own Cache-Control
    ('/sitemap.xml', False),
    ('/', False),
])
def test_should_set_static_cache_control(path, expected):
    assert should_set_static_cache_control(path) is expected


def test_strip_cookie_from_vary_keeps_accept_encoding(app):
    response = app.response_class(b'ok')
    response.headers['Vary'] = 'Accept-Encoding, Cookie'
    strip_cookie_from_vary(response)
    assert response.headers.get('Vary') == 'Accept-Encoding'


def test_strip_set_cookie(app):
    response = app.response_class(b'ok')
    response.headers.add('Set-Cookie', 'session=abc; Path=/')
    response.headers.add('Set-Cookie', 'other=1; Path=/')
    strip_set_cookie(response)
    assert response.headers.get('Set-Cookie') is None


def test_apply_headers_sets_cache_control_on_static(app):
    response = app.response_class(b'.toast{}')
    response.status_code = 200
    response.headers['Vary'] = 'Cookie'
    response.headers.add('Set-Cookie', 'session=abc; Path=/')
    apply_cdn_cacheable_response_headers('/css/output.css', response)
    assert response.headers['Cache-Control'] == STATIC_ASSET_CACHE_CONTROL
    assert 'Cookie' not in (response.headers.get('Vary') or '')
    assert response.headers.get('Set-Cookie') is None


def test_apply_headers_preserves_discovery_cache_control(app):
    response = app.response_class(b'User-agent: *')
    response.status_code = 200
    response.headers['Cache-Control'] = 'public, max-age=3600, s-maxage=86400'
    response.headers['Vary'] = 'Accept-Encoding, Cookie'
    apply_cdn_cacheable_response_headers('/robots.txt', response)
    assert response.headers['Cache-Control'] == 'public, max-age=3600, s-maxage=86400'
    assert response.headers.get('Vary') == 'Accept-Encoding'


def test_css_response_is_edge_cacheable(client):
    response = client.get('/css/output.css')
    assert response.status_code == 200
    cache_control = response.headers.get('Cache-Control', '')
    assert 'public' in cache_control
    assert 's-maxage=604800' in cache_control
    vary = response.headers.get('Vary', '')
    assert 'Cookie' not in vary
    assert 'Set-Cookie' not in response.headers


def test_js_response_is_edge_cacheable(client):
    response = client.get('/js/toast.js')
    assert response.status_code == 200
    assert 's-maxage=604800' in response.headers.get('Cache-Control', '')
    assert 'Cookie' not in response.headers.get('Vary', '')


def test_favicon_is_edge_cacheable(client):
    response = client.get('/favicon.ico')
    assert response.status_code == 200
    assert 's-maxage=604800' in response.headers.get('Cache-Control', '')
    assert 'Cookie' not in response.headers.get('Vary', '')


def test_asset_response_is_edge_cacheable(client):
    fake = b'\xff\xd8\xff'  # minimal JPEG-ish bytes
    with patch(
        'app.routes.download_bytes_from_object_storage',
        return_value=fake,
    ):
        response = client.get('/assets/images/hero-optimized.jpg')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == STATIC_ASSET_CACHE_CONTROL
    assert 'Cookie' not in response.headers.get('Vary', '')
    assert 'Set-Cookie' not in response.headers


def test_discovery_endpoints_strip_cookie_vary(client):
    response = client.get('/robots.txt')
    assert response.status_code == 200
    assert 'Cookie' not in response.headers.get('Vary', '')
    assert 's-maxage=86400' in response.headers.get('Cache-Control', '')


def test_html_does_not_get_static_s_maxage(client, db):
    response = client.get('/')
    assert response.status_code == 200
    assert 's-maxage=604800' not in response.headers.get('Cache-Control', '')


def test_policy_interface_skips_storage_on_static(app):
    redis_client = Mock(spec=Redis)
    iface = PolicyRedisSessionInterface(
        app=app, client=redis_client, key_prefix='session:',
        use_signer=False, permanent=True, sid_length=32,
    )
    session = iface.session_class({'csrf_token': 'x'}, sid='testsid123')
    session.modified = True
    with app.test_request_context('/css/output.css'):
        assert iface.should_set_storage(app, session) is False


def test_missing_static_image_returns_404_not_500(client):
    """Regression: NullSession + csrf_token() on HTML 404 turned misses into 500s.

    Sentry: RuntimeError 'session is unavailable because no secret key was set'
    on main:serve_static_image — misleading; real cause was writing CSRF into
    a NullSession after abort(404) on a CDN-cacheable path.
    """
    with patch(
        'app.routes.download_bytes_from_object_storage',
        side_effect=FileNotFoundError('NoSuchKey'),
    ):
        response = client.get('/images/definitely-missing-asset.jpg')
    assert response.status_code == 404
    assert 'Set-Cookie' not in response.headers
    assert b'secret key' not in response.data.lower()


def test_cdn_path_session_is_writable_for_csrf(app):
    """CDN open_session must allow CSRF writes (error pages / edge cases)."""
    from flask import session
    from flask_wtf.csrf import generate_csrf

    with app.test_request_context('/css/output.css'):
        token = generate_csrf()
        assert token
        assert 'csrf_token' in session


def test_homepage_preloads_hero(client, db):
    response = client.get('/')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'rel="preload"' in html
    assert 'images/hero-optimized.jpg' in html
    assert 'fetchpriority="high"' in html
