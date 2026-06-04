"""Sitemap coverage, canonical URLs, and crawlability filters."""
import re
from xml.etree import ElementTree as ET

import pytest

from app.discussions.query_utils import crawlable_discussions_query
from app.models import (
    Briefing,
    DailyBrief,
    DailyQuestion,
    Discussion,
    NewsSource,
    Programme,
    Statement,
)
from app.seo import generate_sitemap


NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}


def _parse_sitemap(body: str) -> list[dict]:
    root = ET.fromstring(body)
    assert root.tag.endswith('urlset')
    out = []
    for url_el in root.findall('sm:url', NS):
        loc = url_el.find('sm:loc', NS)
        assert loc is not None and loc.text
        entry = {'loc': loc.text.strip()}
        lastmod = url_el.find('sm:lastmod', NS)
        if lastmod is not None and lastmod.text:
            entry['lastmod'] = lastmod.text.strip()
        out.append(entry)
    return out


def _locs(body: str) -> list[str]:
    return [e['loc'] for e in _parse_sitemap(body)]


@pytest.fixture
def sitemap_body(client, db):
    with client.application.app_context():
        db.create_all()
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/xml'
    return resp.data.decode('utf-8')


def test_sitemap_xml_well_formed(sitemap_body):
    entries = _parse_sitemap(sitemap_body)
    assert len(entries) >= 30
    assert len(entries) == len(set(e['loc'] for e in entries))


def test_sitemap_includes_core_product_hubs(sitemap_body):
    locs = _locs(sitemap_body)
    required = [
        '/',
        '/about',
        '/platform',
        '/discussions/search',
        '/discussions/news',
        '/daily',
        '/brief/today',
        '/brief/archive',
        '/brief/methodology',
        '/brief/weekly',
        '/news',
        '/programmes/',
        '/sources/',
        '/briefings/landing',
        '/for-publishers/',
        '/for-publishers/embed',
        '/help/',
        '/faq',
        '/donate',
    ]
    for path in required:
        assert any(loc.rstrip('/').endswith(path.rstrip('/')) or f'{path}' in loc for loc in locs), (
            f'missing sitemap path {path!r}'
        )


def test_sitemap_includes_play_when_game_enabled(app, client, db):
    with app.app_context():
        db.create_all()
        app.config['GAME_ENABLED'] = True
    body = client.get('/sitemap.xml').data.decode('utf-8')
    locs = _locs(body)
    assert any(loc.rstrip('/').endswith('/play') for loc in locs)
    assert any('/play/editorial-principles' in loc for loc in locs)
    assert any('/play/run/' in loc for loc in locs)
    assert any('/help/tradeoffs' in loc for loc in locs)


def test_sitemap_omits_play_when_game_disabled(app, client, db):
    with app.app_context():
        db.create_all()
        app.config['GAME_ENABLED'] = False
    body = client.get('/sitemap.xml').data.decode('utf-8')
    locs = _locs(body)
    assert not any(loc.endswith('/play') or '/play/' in loc for loc in locs)
    assert not any('/help/tradeoffs' in loc for loc in locs)


def test_sitemap_sample_brief_follows_self_serve_flag(app, client, db):
    with app.app_context():
        db.create_all()
        app.config['SELF_SERVE_TRIAL_ENABLED'] = True
    on = _locs(client.get('/sitemap.xml').data.decode('utf-8'))
    assert any('/briefings/sample' in loc for loc in on)

    with app.app_context():
        app.config['SELF_SERVE_TRIAL_ENABLED'] = False
    off = _locs(client.get('/sitemap.xml').data.decode('utf-8'))
    assert not any('/briefings/sample' in loc for loc in off)


def test_sitemap_discussion_urls_are_canonical(app, db):
    with app.app_context():
        db.create_all()
        # Isolate URL-shape assertions from the content floor.
        app.config['SITEMAP_MIN_STATEMENTS'] = 0
        discussion = Discussion(
            title='Climate resilience planning',
            slug='climate-resilience-planning',
            geographic_scope='global',
            partner_env='live',
            has_native_statements=True,
        )
        db.session.add(discussion)
        db.session.commit()

        body = generate_sitemap()
        assert f'/discussions/{discussion.id}/climate-resilience-planning' in body
        # Consensus pages gate anonymous crawlers into a thin, noindexed page;
        # they must never appear in the sitemap.
        assert f'/discussions/{discussion.id}/consensus' not in body
        assert f'/discussion/{discussion.id}' not in body


def _seed_statements(discussion_id, count):
    """Add `count` visible (published) statements to a discussion."""
    db_session = Statement.query.session
    for i in range(count):
        db_session.add(
            Statement(
                discussion_id=discussion_id,
                content=f'Seed statement number {i} with enough length to read.',
            )
        )
    db_session.commit()


def test_sitemap_includes_discussion_with_statements(app, db):
    with app.app_context():
        db.create_all()
        discussion = Discussion(
            title='Flood defence funding',
            slug='flood-defence-funding',
            geographic_scope='global',
            partner_env='live',
            has_native_statements=True,
        )
        db.session.add(discussion)
        db.session.flush()
        _seed_statements(discussion.id, 3)  # content, but zero participants

        body = generate_sitemap()
        assert f'/discussions/{discussion.id}/flood-defence-funding' in body
        # Consensus URL is omitted even for substantive discussions.
        assert f'/discussions/{discussion.id}/consensus' not in body


def test_sitemap_excludes_empty_native_discussions(app, db):
    with app.app_context():
        db.create_all()
        thin = Discussion(
            title='Untouched draft topic',
            slug='untouched-draft-topic',
            geographic_scope='global',
            partner_env='live',
            has_native_statements=True,
        )
        db.session.add(thin)
        db.session.flush()
        _seed_statements(thin.id, 2)  # below the default floor of 3

        body = generate_sitemap()
        assert 'untouched-draft-topic' not in body


def test_sitemap_includes_polis_embed_discussion(app, db):
    """Embed discussions hold statements externally; include them despite no native rows."""
    with app.app_context():
        db.create_all()
        embed = Discussion(
            title='Embedded polis topic',
            slug='embedded-polis-topic',
            geographic_scope='global',
            partner_env='live',
            has_native_statements=False,
            embed_code='<iframe src="https://pol.is/abc"></iframe>',
        )
        db.session.add(embed)
        db.session.commit()

        body = generate_sitemap()
        assert '/discussions/' in body
        assert 'embedded-polis-topic' in body


def test_sitemap_excludes_test_partner_discussions(app, db):
    with app.app_context():
        db.create_all()
        db.session.add(
            Discussion(
                title='Test embed discussion',
                slug='test-embed-discussion',
                geographic_scope='global',
                partner_env='test',
            )
        )
        db.session.commit()
        body = generate_sitemap()
        assert 'test-embed-discussion' not in body


def test_sitemap_excludes_private_programme_discussions(app, db):
    with app.app_context():
        db.create_all()
        programme = Programme(
            name='Private cohort',
            slug='private-cohort',
            status='active',
            visibility='private',
        )
        db.session.add(programme)
        db.session.flush()
        db.session.add(
            Discussion(
                title='Invite only topic',
                slug='invite-only-topic',
                geographic_scope='global',
                programme_id=programme.id,
                partner_env='live',
            )
        )
        db.session.commit()
        body = generate_sitemap()
        assert 'invite-only-topic' not in body
        assert 'private-cohort' not in body


def test_sitemap_includes_public_programme_and_source(app, db):
    with app.app_context():
        db.create_all()
        db.session.add(
            Programme(
                name='Big Questions UK',
                slug='humanity-big-questions',
                status='active',
                visibility='public',
            )
        )
        db.session.add(
            NewsSource(
                name='Example Tribune',
                feed_url='https://example.com/rss',
                slug='example-tribune',
                is_active=True,
            )
        )
        db.session.commit()
        body = generate_sitemap()
        assert '/programmes/humanity-big-questions' in body
        assert '/sources/example-tribune' in body


def test_sitemap_includes_published_brief_and_daily_question_dates(app, db):
    from datetime import date

    with app.app_context():
        db.create_all()
        db.session.add(
            DailyBrief(
                date=date(2026, 5, 1),
                status='published',
                brief_type='daily',
                title='May brief',
            )
        )
        db.session.add(
            DailyQuestion(
                question_date=date(2026, 5, 1),
                question_number=100,
                question_text='Should councils invest in flood defences?',
                status='published',
            )
        )
        db.session.commit()
        body = generate_sitemap()
        assert '/brief/2026-05-01' in body
        assert '/daily/2026-05-01' in body


def test_sitemap_includes_public_briefing_archive(app, db):
    with app.app_context():
        db.create_all()
        briefing = Briefing(
            name='Open civic digest',
            owner_type='user',
            owner_id=1,
            visibility='public',
        )
        db.session.add(briefing)
        db.session.commit()
        body = generate_sitemap()
        assert f'/briefings/public/{briefing.id}' in body


def test_crawlable_discussions_query_matches_search_semantics(app, db):
    with app.app_context():
        db.create_all()
        public_prog = Programme(
            name='Public prog',
            slug='public-prog',
            status='active',
            visibility='public',
        )
        private_prog = Programme(
            name='Hidden prog',
            slug='hidden-prog',
            status='active',
            visibility='private',
        )
        db.session.add_all([public_prog, private_prog])
        db.session.flush()
        visible = Discussion(
            title='On public programme',
            slug='on-public-programme',
            geographic_scope='global',
            programme_id=public_prog.id,
            partner_env='live',
        )
        hidden = Discussion(
            title='On private programme',
            slug='on-private-programme',
            geographic_scope='global',
            programme_id=private_prog.id,
            partner_env='live',
        )
        db.session.add_all([visible, hidden])
        db.session.commit()
        slugs = {d.slug for d in crawlable_discussions_query().all()}
        assert 'on-public-programme' in slugs
        assert 'on-private-programme' not in slugs


def test_consensus_gate_page_is_noindexed(app, client, db):
    """Anonymous crawlers hitting the participation gate must get noindex."""
    with app.app_context():
        db.create_all()
        discussion = Discussion(
            title='Gate noindex topic',
            slug='gate-noindex-topic',
            geographic_scope='global',
            partner_env='live',
        )
        db.session.add(discussion)
        db.session.commit()
        discussion_id = discussion.id

    resp = client.get(f'/discussions/{discussion_id}/consensus')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert re.search(r'name="robots"[^>]*content="[^"]*noindex', html), (
        'consensus gate must emit a noindex robots meta'
    )


def test_consensus_not_ready_page_is_noindexed(app, client, db):
    """Pre-analysis placeholder must also be noindex (same thin-page class as the gate)."""
    from app.models import User

    with app.app_context():
        db.create_all()
        creator = User(username='creator', email='creator@example.com', password='hashed')
        db.session.add(creator)
        db.session.flush()
        discussion = Discussion(
            title='Not ready noindex topic',
            slug='not-ready-noindex-topic',
            geographic_scope='global',
            partner_env='live',
            creator_id=creator.id,
            has_native_statements=True,
        )
        db.session.add(discussion)
        db.session.flush()
        _seed_statements(discussion.id, 10)
        db.session.commit()
        discussion_id = discussion.id
        creator_id = creator.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(creator_id)
        sess['_fresh'] = True

    resp = client.get(f'/discussions/{discussion_id}/consensus')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert re.search(r'name="robots"[^>]*content="[^"]*noindex', html)


def test_sitemap_escapes_xml_special_characters_in_loc(app, db):
    with app.app_context():
        db.create_all()
        db.session.add(
            NewsSource(
                name='Ampersand & Co',
                feed_url='https://example.com/rss',
                slug='a&b-source',
                is_active=True,
            )
        )
        db.session.commit()
        body = generate_sitemap()
        assert 'a&amp;b-source' in body
        assert re.search(r'<loc>[^<]*a&amp;b-source[^<]*</loc>', body)
