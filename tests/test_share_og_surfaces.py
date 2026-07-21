"""Tests for brief and profile OG images."""

from types import SimpleNamespace

import pytest


def test_render_brief_png():
    from app.brief import og_image_service

    if not og_image_service.is_available():
        pytest.skip('Pillow native module unavailable; cannot render real PNG')

    png = og_image_service.render_brief_png(
        title='Daily Brief — July 21',
        story_count=4,
        brief_type='daily',
        badge_label='Daily Brief',
    )
    assert png is not None
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


def test_render_profile_png():
    from app.profiles import og_image_service

    if not og_image_service.is_available():
        pytest.skip('Pillow native module unavailable; cannot render real PNG')

    png = og_image_service.render_profile_png(
        name='Ada Lovelace',
        is_company=False,
        badge_label='Community voice',
    )
    assert png is not None
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


def test_brief_og_png_route(app, client, monkeypatch):
    class _FakeBriefItemQuery:
        def filter_by(self, **kwargs):
            return self

        def count(self):
            return 3

    monkeypatch.setattr(
        'app.brief.routes.DailyBrief.get_by_date',
        lambda brief_date, brief_type='daily', published_only=False: SimpleNamespace(
            id=7,
            title='Morning civic intelligence',
            brief_type=brief_type,
        ),
    )
    monkeypatch.setattr('app.brief.routes.BriefItem', SimpleNamespace(query=_FakeBriefItemQuery()))
    monkeypatch.setattr('app.brief.og_image_service.is_available', lambda: True)
    monkeypatch.setattr(
        'app.brief.og_image_service.render_brief_png',
        lambda **kwargs: b'\x89PNG\r\n\x1a\n' + b'brief',
    )
    monkeypatch.setattr('app.lib.og_cache.og_cache_get', lambda key: None)
    monkeypatch.setattr('app.lib.og_cache.og_cache_set', lambda *args, **kwargs: None)

    response = client.get('/brief/2099-01-01/og.png')
    assert response.status_code == 200
    assert response.content_type == 'image/png'


def test_profile_og_png_route(app, client, monkeypatch):
    from app.models import IndividualProfile

    fake_profile = SimpleNamespace(id=1, full_name='Ada Lovelace', slug='ada')

    class _FakeProfileQuery:
        def filter_by(self, **kwargs):
            return self

        def first_or_404(self):
            return fake_profile

    monkeypatch.setattr('app.profiles.routes.IndividualProfile', type('IP', (), {'query': _FakeProfileQuery()}))
    monkeypatch.setattr('app.profiles.og_image_service.is_available', lambda: True)
    monkeypatch.setattr(
        'app.profiles.og_image_service.render_profile_png',
        lambda **kwargs: b'\x89PNG\r\n\x1a\n' + b'profile',
    )
    monkeypatch.setattr('app.lib.og_cache.og_cache_get', lambda key: None)
    monkeypatch.setattr('app.lib.og_cache.og_cache_set', lambda *args, **kwargs: None)

    response = client.get('/profiles/profile/individual/ada/og.png')
    assert response.status_code == 200
    assert response.content_type == 'image/png'


def test_discussion_og_image_url_uses_direct_route(app):
    from app.trending.social_poster import _discussion_og_image_url

    discussion = SimpleNamespace(id=4242)
    with app.app_context():
        url = _discussion_og_image_url(discussion)
    assert url is not None
    assert url.endswith('/discussions/4242/og.png')
