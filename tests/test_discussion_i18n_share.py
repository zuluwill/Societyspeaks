"""Regression tests for discussion i18n in Python-built share/SEO copy."""

from pathlib import Path

from app.lib.translation import (
    discussion_display_description,
    discussion_display_title,
)
from app.models import Discussion, DiscussionTranslation, generate_slug


ROUTES_PATH = Path(__file__).resolve().parents[1] / 'app' / 'discussions' / 'routes.py'


def test_discussion_display_title_uses_cache_dict_keys():
    discussion = Discussion(title='English title', slug='english-title')
    assert discussion_display_title(discussion, {'title': 'Hindi title', 'description': ''}) == 'Hindi title'
    assert discussion_display_title(discussion, None) == 'English title'


def test_discussion_display_description_falls_back_to_english_when_cache_empty():
    discussion = Discussion(
        title='English title',
        slug='english-title',
        description='English description',
    )
    assert discussion_display_description(
        discussion,
        {'title': 'Hindi title', 'description': ''},
    ) == 'English description'
    assert discussion_display_description(
        discussion,
        {'title': 'Hindi title', 'description': 'Hindi description'},
    ) == 'Hindi description'
    assert discussion_display_description(discussion, None) == 'English description'


def test_view_discussion_with_cached_translation_renders(app, db):
    """Reproduces Sentry PYTHON-FLASK-HB: share copy must not AttributeError on dict cache."""
    with app.app_context():
        discussion = Discussion(
            title='War crimes allegations',
            slug=generate_slug('War crimes allegations'),
            has_native_statements=False,
            embed_code='<div>embed</div>',
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()
        db.session.add(
            DiscussionTranslation(
                discussion_id=discussion.id,
                language_code='hi',
                title='युद्ध अपराध के आरोप',
                description='विवरण',
            )
        )
        db.session.commit()
        discussion_id = discussion.id
        discussion_slug = discussion.slug

    response = app.test_client().get(f'/discussions/{discussion_id}/{discussion_slug}?lang=hi')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'युद्ध अपराध के आरोप' in html
    assert f'/discussions/{discussion_id}/og.png?lang=hi' in html


def test_discussion_og_png_uses_translated_title(app, db, monkeypatch):
    from app.discussions import og_image_service

    with app.app_context():
        discussion = Discussion(
            title='English OG title',
            slug=generate_slug('English OG title'),
            has_native_statements=False,
            embed_code='<div>embed</div>',
            topic='Society',
            geographic_scope='global',
            partner_env='live',
        )
        db.session.add(discussion)
        db.session.flush()
        db.session.add(
            DiscussionTranslation(
                discussion_id=discussion.id,
                language_code='hi',
                title='हिंदी OG शीर्षक',
                description='',
            )
        )
        db.session.commit()
        discussion_id = discussion.id

    captured = {}

    def _fake_render(**kwargs):
        captured.update(kwargs)
        return b'\x89PNG\r\n\x1a\n' + b'discussion'

    monkeypatch.setattr(og_image_service, 'is_available', lambda: True)
    monkeypatch.setattr(og_image_service, 'render_discussion_png', _fake_render)
    monkeypatch.setattr('app.discussions.routes.get_discussion_participant_count', lambda *a, **k: 0)
    monkeypatch.setattr('app.lib.og_cache.og_cache_get', lambda key: None)
    monkeypatch.setattr('app.lib.og_cache.og_cache_set', lambda *args, **kwargs: None)

    response = app.test_client().get(f'/discussions/{discussion_id}/og.png?lang=hi')
    assert response.status_code == 200
    assert captured.get('title') == 'हिंदी OG शीर्षक'


def test_view_discussion_route_uses_display_title_helper():
    source = ROUTES_PATH.read_text(encoding='utf-8')
    assert 'discussion_display_title(' in source
    assert 'view_discussion_translation.title' not in source
    assert "view_discussion_translation['title']" not in source
    assert 'discussion_display_title(discussion, view_discussion_translation)' in source
    assert "og_png_kwargs['lang'] = view_lang" in source
