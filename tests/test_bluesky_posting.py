"""Tests for Bluesky posting (post_to_bluesky) with atproto + network mocked.

Guards the path that regressed before: the link-card embed must carry a real
thumbnail from the per-content OG card, the post URL rides in the embed (not the
text), and posting is skipped cleanly when the app password is absent.
"""

import types

import pytest


def _install_fake_atproto(monkeypatch):
    """Insert a minimal fake `atproto` module and return the Client class."""
    sent = []
    uploaded = []

    class FakeBlobResponse:
        blob = 'BLOB_REF'

    class FakeClient:
        def login(self, handle, password):
            self.login_args = (handle, password)

        def upload_blob(self, data):
            uploaded.append(data)
            return FakeBlobResponse()

        def send_post(self, text=None, embed=None):
            sent.append({'text': text, 'embed': embed})
            return types.SimpleNamespace(uri='at://did:plc:test/app.bsky.feed.post/abc')

    class _External:
        def __init__(self, *, uri, title, description, thumb):
            self.uri, self.title, self.description, self.thumb = uri, title, description, thumb

    class _Main:
        def __init__(self, *, external):
            self.external = external

    class _TextBuilder:  # only used on the embed-failure fallback path
        def text(self, *a, **k):
            return self

        def link(self, *a, **k):
            return self

    atproto = types.ModuleType('atproto')
    atproto.Client = FakeClient
    atproto.models = types.SimpleNamespace(
        AppBskyEmbedExternal=types.SimpleNamespace(External=_External, Main=_Main)
    )
    atproto.client_utils = types.SimpleNamespace(TextBuilder=_TextBuilder)
    monkeypatch.setitem(__import__('sys').modules, 'atproto', atproto)
    return sent, uploaded


def _patch_post_side_effects(monkeypatch):
    monkeypatch.setattr('app.trending.engagement_tracker.record_post', lambda **k: None)
    monkeypatch.setattr('app.lib.posthog_utils.safe_system_capture', lambda *a, **k: None)


def test_og_png_url_for_page():
    from app.trending.social_poster import og_png_url_for_page

    assert og_png_url_for_page('https://societyspeaks.io/daily/2026-07-21') == (
        'https://societyspeaks.io/daily/2026-07-21/og.png'
    )
    assert og_png_url_for_page('https://societyspeaks.io/brief/2026-07-21/') == (
        'https://societyspeaks.io/brief/2026-07-21/og.png'
    )


def test_post_to_bluesky_uses_direct_og_image_in_embed(monkeypatch):
    from app.trending import social_poster

    monkeypatch.setenv('BLUESKY_APP_PASSWORD', 'test-pw')
    sent, uploaded = _install_fake_atproto(monkeypatch)
    _patch_post_side_effects(monkeypatch)

    # The HTML scrape returns no image; the direct og_image_url must supply it.
    monkeypatch.setattr(
        social_poster, '_fetch_link_card_metadata',
        lambda url: {'uri': url, 'title': 'Daily Question', 'description': 'd', 'image_url': None},
    )

    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return types.SimpleNamespace(status_code=200, content=b'\x89PNG\r\n\x1a\nfake')

    monkeypatch.setattr('requests.get', fake_get)

    page = 'https://societyspeaks.io/daily/2026-07-21'
    og = social_poster.og_png_url_for_page(page)
    uri = social_poster.post_to_bluesky(
        title='Should the strikes continue?',
        topic='Geopolitics',
        discussion_url=page,
        discussion=None,
        custom_text='What do you think?',
        og_image_url=og,
    )

    assert uri == 'at://did:plc:test/app.bsky.feed.post/abc'
    assert og in requested
    assert len(uploaded) == 1
    assert len(sent) == 1
    embed = sent[0]['embed']
    assert embed is not None and embed.external.thumb == 'BLOB_REF'
    assert embed.external.uri == page
    assert page not in (sent[0]['text'] or '')


def test_post_to_bluesky_uses_discussion_og_when_object_passed(monkeypatch, app):
    from app.trending import social_poster

    monkeypatch.setenv('BLUESKY_APP_PASSWORD', 'test-pw')
    sent, uploaded = _install_fake_atproto(monkeypatch)
    _patch_post_side_effects(monkeypatch)
    monkeypatch.setattr(
        social_poster, '_fetch_link_card_metadata',
        lambda url: {'uri': url, 'title': 'Debate', 'description': '', 'image_url': None},
    )
    monkeypatch.setattr(
        social_poster, 'get_base_url', lambda: 'https://societyspeaks.io',
    )

    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return types.SimpleNamespace(status_code=200, content=b'\x89PNG\r\n\x1a\ndisc')

    monkeypatch.setattr('requests.get', fake_get)

    discussion = types.SimpleNamespace(id=4242, title='Test debate', topic='Politics')
    page = 'https://societyspeaks.io/discussions/4242/slug'
    uri = social_poster.post_to_bluesky(
        title=discussion.title,
        topic=discussion.topic,
        discussion_url=page,
        discussion=discussion,
    )

    assert uri is not None
    assert 'https://societyspeaks.io/discussions/4242/og.png' in requested
    assert sent[0]['embed'].external.thumb == 'BLOB_REF'


def test_post_to_bluesky_skips_without_password(monkeypatch):
    from app.trending import social_poster

    monkeypatch.delenv('BLUESKY_APP_PASSWORD', raising=False)
    assert social_poster.post_to_bluesky(
        title='x', topic='y', discussion_url='https://societyspeaks.io/daily/2026-07-21',
    ) is None


def test_bluesky_direct_post_idempotency(monkeypatch):
    from app.trending import social_poster

    store = {}

    class FakeRedis:
        def get(self, key):
            return store.get(key)

        def setex(self, key, ttl, value):
            store[key] = value

    monkeypatch.setattr(
        'app.lib.redis_client.get_client',
        lambda decode_responses=True: FakeRedis(),
    )

    assert social_poster.bluesky_direct_post_already_sent('daily-brief', '2026-07-21') is False
    social_poster.mark_bluesky_direct_post_sent(
        'daily-brief', '2026-07-21', 'at://did:plc:test/app.bsky.feed.post/xyz',
    )
    assert social_poster.bluesky_direct_post_already_sent('daily-brief', '2026-07-21') is True
    assert store['bluesky:direct:daily-brief:2026-07-21'] == 'at://did:plc:test/app.bsky.feed.post/xyz'

