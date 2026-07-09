"""Tests for source discussion listing (Postgres DISTINCT + JSON columns)."""

from datetime import timedelta

from app import db
from app.lib.time import utcnow_naive
from app.models import Discussion, DiscussionSourceArticle, NewsArticle, NewsSource
from app.models._base import generate_slug
from app.sources.utils import get_source_discussions


def _make_source(name='Test Source', slug='test-source'):
    source = NewsSource(
        name=name,
        slug=slug,
        feed_url=f'https://example.com/{slug}.xml',
        is_active=True,
        source_category='newspaper',
        country='GB',
    )
    db.session.add(source)
    db.session.flush()
    return source


def _make_article(source, title='Article'):
    article = NewsArticle(
        source_id=source.id,
        title=title,
        url=f'https://example.com/{title.replace(" ", "-").lower()}',
        published_at=utcnow_naive(),
    )
    db.session.add(article)
    db.session.flush()
    return article


def _make_discussion(title, created_at=None, information_links=None):
    discussion = Discussion(
        title=title,
        slug=generate_slug(title),
        description='desc',
        has_native_statements=True,
        topic='Society',
        geographic_scope='global',
        partner_env='live',
        information_links=(
            information_links
            if information_links is not None
            else [{'url': 'https://example.com'}]
        ),
        created_at=created_at or utcnow_naive(),
    )
    db.session.add(discussion)
    db.session.flush()
    return discussion


def test_get_source_discussions_dedupes_and_handles_json(app, db):
    """A discussion linked via two articles must appear once; JSON cols must not break DISTINCT."""
    with app.app_context():
        db.create_all()
        source = _make_source()
        a1 = _make_article(source, 'One')
        a2 = _make_article(source, 'Two')
        older = _make_discussion(
            'Older Source Disc',
            created_at=utcnow_naive() - timedelta(days=2),
            information_links=[{'url': 'https://a.example'}],
        )
        newer = _make_discussion(
            'Newer Source Disc',
            created_at=utcnow_naive() - timedelta(days=1),
            information_links=[{'url': 'https://b.example'}, {'url': 'https://c.example'}],
        )
        db.session.add_all(
            [
                DiscussionSourceArticle(discussion_id=newer.id, article_id=a1.id),
                DiscussionSourceArticle(discussion_id=newer.id, article_id=a2.id),
                DiscussionSourceArticle(discussion_id=older.id, article_id=a1.id),
            ]
        )
        db.session.commit()

        page = get_source_discussions(source.id, page=1, per_page=12)
        titles = [d.title for d in page.items]
        assert titles == ['Newer Source Disc', 'Older Source Disc']
        assert page.total == 2


def test_get_source_discussions_excludes_test_partner_env(app, db):
    with app.app_context():
        db.create_all()
        source = _make_source(name='Other Source', slug='other-source')
        article = _make_article(source, 'Only')
        live = _make_discussion('Live Source Disc')
        test = _make_discussion('Test Source Disc')
        test.partner_env = 'test'
        db.session.add_all(
            [
                DiscussionSourceArticle(discussion_id=live.id, article_id=article.id),
                DiscussionSourceArticle(discussion_id=test.id, article_id=article.id),
            ]
        )
        db.session.commit()

        page = get_source_discussions(source.id)
        assert [d.title for d in page.items] == ['Live Source Disc']
