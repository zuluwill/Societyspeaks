"""Sitemap URL helpers must work outside an HTTP request context."""

from app.seo import _external, generate_sitemap


def test_external_builds_urls_without_request_context(app):
    with app.app_context():
        url = _external('game.index')
    assert url.startswith('https://')
    assert url.endswith('/play/')


def test_generate_sitemap_without_request_context(app, db):
    with app.app_context():
        db.create_all()
        body = generate_sitemap()
    assert '<urlset' in body
    assert '/play/' in body
