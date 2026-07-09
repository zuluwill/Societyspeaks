"""Render checks for About/FAQ/Help SEO output (titles, meta, JSON-LD, canonical)."""
import json
import re


def _get(client, db, path):
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    return resp.get_data(as_text=True)


def test_help_pages_emit_title_meta_canonical(client, db):
    cases = {
        '/help/': 'Help Centre — Society Speaks',
        '/help/daily-brief': 'Daily Brief — Help | Society Speaks',
        '/help/civic-infrastructure': 'Civic infrastructure',
        '/help/tradeoffs': 'Tradeoffs — Help | Society Speaks',
        '/help/personal-briefs': 'Personal Briefs — Help | Society Speaks',
        '/help/programmes': 'Programmes',
        '/help/managing-discussions': 'Managing Discussions',
        '/help/news-feed': 'news feed works',
        '/help/getting-started': 'Getting Started',
        '/help/native-system': 'Native Debate System',
        '/help/creating-discussions': 'Creating Discussions',
        '/help/polis-algorithms': 'Pol.is algorithms',
    }
    for path, expected_title in cases.items():
        html = _get(client, db, path)
        m = re.search(r'<title>(.*?)</title>', html, re.S)
        assert m and expected_title in m.group(1), f"{path}: title missing/wrong -> {m and m.group(1)!r}"
        assert 'name="description"' in html
        # default layout title must NOT be the one rendered
        assert 'Society Speaks.io - Join the Conversation' not in m.group(1)
        # canonical present and page-specific (not the bare base_url default duplicated)
        assert html.count('rel="canonical"') == 1, f"{path}: expected exactly one canonical"


def test_help_hub_emits_faqpage_jsonld(client, db):
    html = _get(client, db, '/help/')
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    parsed = [json.loads(b) for b in blocks]
    assert any(p.get('@type') == 'FAQPage' for p in parsed), "FAQPage JSON-LD not rendered on help hub"


def test_about_emits_org_website_breadcrumb(client, db):
    html = _get(client, db, '/about')
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    types = {json.loads(b).get('@type') for b in blocks}
    assert {'Organization', 'WebSite', 'BreadcrumbList'} <= types, f"about JSON-LD types: {types}"
    assert html.count('rel="canonical"') == 1


def test_no_help_template_uses_undefined_head_block():
    """Regression: {% block head %} is silently dropped by layout.html."""
    from pathlib import Path

    help_dir = Path(__file__).resolve().parents[1] / 'app' / 'templates' / 'help'
    offenders = []
    for path in help_dir.glob('*.html'):
        text = path.read_text(encoding='utf-8')
        if '{% block head %}' in text or '{%- block head %}' in text:
            offenders.append(path.name)
    assert not offenders, f"help templates still use block head: {offenders}"


def test_no_template_anywhere_uses_undefined_head_block():
    """Repo-wide guard: layout.html defines no `head` block, so any
    `{% block head %}` silently drops its title/meta/canonical/JSON-LD.
    """
    import re
    from pathlib import Path

    templates = Path(__file__).resolve().parents[1] / 'app' / 'templates'
    pat = re.compile(r'{%-?\s*block\s+head\s*%}')
    offenders = [
        str(p.relative_to(templates))
        for p in templates.rglob('*.html')
        if pat.search(p.read_text(encoding='utf-8'))
    ]
    assert not offenders, f"templates still use the undefined `head` block: {offenders}"


def test_converted_pages_emit_seo(client, db):
    """The repo-wide block-head conversions now reach the rendered <head>."""
    cases = {
        '/briefings/landing': 'Personal Briefs',
        '/sources/': 'News Sources',
        '/discussions/news': 'News Discussions',
        '/discussions/search': 'Explore Discussions',
    }
    for path, expected_title in cases.items():
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} -> {resp.status_code}"
        html = resp.get_data(as_text=True)
        m = re.search(r'<title>(.*?)</title>', html, re.S)
        assert m and expected_title in m.group(1), f"{path}: title -> {m and m.group(1)!r}"
        assert 'Society Speaks.io - Join the Conversation' not in m.group(1)
        assert html.count('rel="canonical"') == 1, f"{path}: expected exactly one canonical"


def test_briefing_landing_emits_product_jsonld(client, db):
    html = client.get('/briefings/landing').get_data(as_text=True)
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    types = {json.loads(b).get('@type') for b in blocks}
    assert 'SoftwareApplication' in types, f"briefing landing JSON-LD types: {types}"


def test_faq_jsonld_valid_and_matches_visibility(client, db):
    html = _get(client, db, '/faq')
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    faq = next(json.loads(b) for b in blocks if json.loads(b).get('@type') == 'FAQPage')
    json.dumps(faq)  # already parsed, sanity
    names = [q['name'] for q in faq['mainEntity']]
    tradeoffs_in_ld = any('Tradeoffs' in n for n in names)
    tradeoffs_visible = 'What is Tradeoffs on Society Speaks?' in html
    assert tradeoffs_in_ld == tradeoffs_visible, "FAQ Tradeoffs JSON-LD must match visible content"


def test_donate_page_renders_funding_story_and_seo(client, db):
    html = _get(client, db, '/donate')
    assert 'Donate to Society Speaks' in html
    assert html.count('<h1') == 1
    assert 'Why donate?' in html
    assert 'How we sustain the platform' in html
    assert 'Personal Briefs' in html
    assert 'Publisher partners' in html
    assert 'Donate securely with Stripe' in html
    assert html.count('rel="canonical"') == 1
    assert 'property="og:title"' in html
    assert 'name="twitter:title"' in html
    assert 'name="description"' in html
    assert 'open source' in html.lower()
    assert '/donate/checkout' in html


def test_faq_funding_jsonld_matches_visible(client, db):
    """Funding Q&A in JSON-LD must also appear in visible FAQ content (Google policy)."""
    html = _get(client, db, '/faq')
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    faq = next(json.loads(b) for b in blocks if json.loads(b).get('@type') == 'FAQPage')
    names = [q['name'] for q in faq['mainEntity']]
    json_ld_funding = (
        'How is Society Speaks funded?',
        'What do publishers pay for embeds and the Partner API?',
    )
    for n in json_ld_funding:
        assert n in names, f"missing from JSON-LD: {n}"
        assert n in html, f"in JSON-LD but not visible: {n}"
    # Visible funding section (not all duplicated in JSON-LD — that is allowed)
    visible_funding = (
        'How we are funded',
        'Why donate if the platform is already free?',
        'Where can I donate?',
        'How much do publisher embeds cost?',
    )
    for n in visible_funding:
        assert n in html, f"missing visible funding copy: {n}"
    # Pricing claims in visible copy must match configured partner tiers
    assert '£49/month' in html
    assert '£249/month' in html
    assert '£4.99/month' in html


def test_core_marketing_pages_emit_single_explicit_canonical(client, db):
    """High-traffic hubs must declare one stable canonical URL each."""
    cases = {
        '/': 'main.index',
        '/platform': 'main.platform',
        '/consultations': 'main.consultations',
        '/security': 'main.security',
        '/accessibility': 'main.accessibility',
        '/news': 'news.dashboard',
        '/for-publishers/': 'partner.hub',
        '/privacy-policy': 'main.privacy_policy',
        '/terms-and-conditions': 'main.terms_and_conditions',
        '/content-policy': 'main.content_policy',
        '/brief/methodology': 'brief.methodology',
    }
    for path in cases:
        html = _get(client, db, path)
        assert html.count('rel="canonical"') == 1, f"{path}: expected exactly one canonical"


def test_consultations_page_seo_and_pricing(client, db):
    """Civic offer page: SEO blocks, locked pricing ladder, FAQ JSON-LD, free-for-citizens line."""
    html = _get(client, db, '/consultations')
    m = re.search(r'<title>(.*?)</title>', html, re.S)
    assert m and 'Run a Consultation' in m.group(1)
    assert html.count('rel="canonical"') == 1
    # Locked civic ladder (8 Jul 2026) — one set of numbers everywhere
    assert '£2,500' in html
    assert '£5,000' in html
    assert '£6,000' in html
    # Boundary + mission framing
    assert 'free for citizens' in html.lower()
    # Structured data
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    types = {json.loads(b).get('@type') for b in blocks}
    assert {'FAQPage', 'Service', 'BreadcrumbList'} <= types, f"consultations JSON-LD types: {types}"


def test_security_page_residency_and_subprocessors(client, db):
    """Trust page: UK residency claims and the subprocessor list stay in step
    with the privacy policy (procurement teams cross-check both)."""
    html = _get(client, db, '/security')
    assert 'United Kingdom' in html
    assert html.count('rel="canonical"') == 1
    # Full subprocessor list — additions/removals must update this page AND
    # the privacy policy together.
    for provider in ('Neon', 'Render', 'Amazon Web Services', 'Redis Cloud',
                     'Stripe', 'Resend', 'PostHog', 'Sentry', 'Anthropic'):
        assert provider in html, f"subprocessor {provider} missing from /security"
    # No stale hosting claims may ever reappear
    assert 'Replit' not in html


def test_security_txt_rfc9116(client, db):
    resp_body = _get(client, db, '/.well-known/security.txt')
    assert 'Contact: mailto:security@societyspeaks.io' in resp_body
    assert 'Expires:' in resp_body


def test_accessibility_statement_renders(client, db):
    html = _get(client, db, '/accessibility')
    assert 'WCAG' in html
    assert html.count('rel="canonical"') == 1


def test_og_url_matches_canonical_on_marketing_pages(client, db):
    for path in ('/', '/about', '/platform', '/consultations', '/faq', '/donate'):
        html = _get(client, db, path)
        canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        og_url = re.search(r'property="og:url" content="([^"]+)"', html)
        assert canonical and og_url, f"{path}: missing canonical or og:url"
        assert canonical.group(1) == og_url.group(1), f"{path}: og:url must match canonical"


def test_daily_and_brief_today_redirect_to_dated_permalinks(app, client, db):
    from datetime import date

    from app.models import DailyBrief, DailyQuestion

    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=1,
            question_text='Should councils invest in flood defences?',
            status='published',
        )
        b = DailyBrief(
            date=date.today(),
            status='published',
            brief_type='daily',
            title='Today brief',
        )
        db.session.add_all([q, b])
        db.session.commit()

    for alias in ('/daily', '/brief', '/brief/today'):
        resp = client.get(alias, follow_redirects=False)
        assert resp.status_code == 301, alias
        assert date.today().isoformat() in resp.headers['Location']

    weekly = DailyBrief(
        date=date(2026, 6, 8),
        status='published',
        brief_type='weekly',
        title='Weekly brief',
    )
    with app.app_context():
        db.session.add(weekly)
        db.session.commit()

    resp = client.get('/brief/weekly', follow_redirects=False)
    assert resp.status_code == 301
    assert '2026-06-08' in resp.headers['Location']
    assert '/brief/weekly/' in resp.headers['Location']


def test_brief_reader_is_noindexed_with_canonical_to_main_brief(app, client, db):
    from datetime import date

    from app.models import DailyBrief

    with app.app_context():
        db.create_all()
        brief = DailyBrief(
            date=date(2026, 6, 1),
            status='published',
            brief_type='daily',
            title='June brief',
        )
        db.session.add(brief)
        db.session.commit()

    html = _get(client, db, '/brief/2026-06-01/reader')
    assert re.search(r'name="robots"[^>]*content="[^"]*noindex', html)
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    assert canonical and canonical.group(1).endswith('/brief/2026-06-01')
    og_url = re.search(r'property="og:url" content="([^"]+)"', html)
    assert og_url and og_url.group(1) == canonical.group(1)


def test_consensus_gate_has_single_canonical(client, db):
    from app.models import Discussion

    with client.application.app_context():
        db.create_all()
        discussion = Discussion(
            title='Canonical consensus topic',
            slug='canonical-consensus-topic',
            geographic_scope='global',
            partner_env='live',
        )
        db.session.add(discussion)
        db.session.commit()
        discussion_id = discussion.id

    html = client.get(f'/discussions/{discussion_id}/consensus').get_data(as_text=True)
    assert html.count('rel="canonical"') == 1
    assert re.search(r'name="robots"[^>]*content="[^"]*noindex', html)


def test_play_hub_is_indexable_game_sessions_are_not(client, db):
    resp = client.get('/play/', follow_redirects=True)
    assert resp.status_code == 200
    hub = resp.get_data(as_text=True)
    robots = re.search(r'name="robots"[^>]*content="([^"]+)"', hub)
    assert robots is None or 'noindex' not in robots.group(1)
    assert hub.count('rel="canonical"') == 1

    turn = client.get('/play/daily', follow_redirects=False)
    if turn.status_code == 200:
        html = turn.get_data(as_text=True)
        assert re.search(r'name="robots"[^>]*content="[^"]*noindex', html)


def test_auth_login_emits_single_noindex_robots_tag(client, db):
    html = client.get('/auth/login').get_data(as_text=True)
    robots_tags = re.findall(r'name="robots"[^>]*content="([^"]+)"', html, re.S)
    assert len(robots_tags) == 1
    assert 'noindex' in robots_tags[0]


def test_search_with_query_is_noindexed(client, db):
    html = client.get('/discussions/search?q=climate').get_data(as_text=True)
    assert re.search(r'name="robots"[^>]*content="[^"]*noindex', html)
    assert html.count('rel="canonical"') == 1


def test_search_hub_without_filters_is_indexable(client, db):
    html = _get(client, db, '/discussions/search')
    robots = re.search(r'name="robots"[^>]*content="([^"]+)"', html)
    assert robots and 'noindex' not in robots.group(1)


def test_sitemap_static_hubs_have_canonical_matching_og_url(client, db):
    """Every major sitemap hub must emit exactly one canonical == og:url."""
    paths = [
        '/',
        '/about',
        '/platform',
        '/faq',
        '/donate',
        '/discussions/search',
        '/news',
        '/brief/archive',
        '/brief/methodology',
        '/programmes/',
        '/sources/',
        '/for-publishers/',
        '/help/',
    ]
    for path in paths:
        resp = client.get(path, follow_redirects=True)
        assert resp.status_code == 200, path
        html = resp.get_data(as_text=True)
        assert html.count('rel="canonical"') == 1, path
        canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        og_url = re.search(r'property="og:url" content="([^"]+)"', html)
        assert canonical and og_url, path
        assert canonical.group(1) == og_url.group(1), path


def test_index_emits_hreflang_for_supported_locales(client, db):
    from app.lib.locale_utils import SUPPORTED_LANGUAGES

    html = _get(client, db, '/')
    assert 'hreflang="x-default"' in html
    for code in SUPPORTED_LANGUAGES:
        assert f'hreflang="{code}"' in html, code
    # One alternate per locale plus x-default (not duplicated per page).
    assert html.count('rel="alternate" hreflang=') == len(SUPPORTED_LANGUAGES) + 1


def test_no_layout_template_uses_raw_robots_meta_in_extra_head():
    """Raw <meta name="robots"> in extra_head duplicates layout's robots block."""
    import re
    from pathlib import Path

    templates = Path(__file__).resolve().parents[1] / 'app' / 'templates'
    pat = re.compile(r'block\s+extra_head[\s\S]*?<meta\s+name="robots"', re.I)
    offenders = [
        str(p.relative_to(templates))
        for p in templates.rglob('*.html')
        if pat.search(p.read_text(encoding='utf-8'))
    ]
    assert not offenders, f"use {{% block meta_robots %}} instead: {offenders}"


def test_no_indexable_template_defines_hreflang_inside_conditional_block():
    """Jinja registers {% block %} at compile time — hreflang must use layout default."""
    from pathlib import Path

    templates = Path(__file__).resolve().parents[1] / 'app' / 'templates'
    offenders = []
    for path in templates.rglob('*.html'):
        text = path.read_text(encoding='utf-8')
        if 'hreflang=' in text and 'block hreflang' not in text and path.name != 'layout.html':
            # Allow reader.html (standalone) and embed templates
            if 'extends' not in text or 'embed' in path.name:
                continue
            if 'rel="alternate" hreflang=' in text:
                offenders.append(str(path.relative_to(templates)))
    assert not offenders, (
        'page-level hreflang duplicates layout; remove manual tags from: '
        + ', '.join(offenders)
    )


def test_no_game_template_uses_raw_description_or_og_in_game_head():
    """Tradeoffs pages must use layout SEO blocks, not duplicate tags in game_head."""
    import re
    from pathlib import Path

    game_dir = Path(__file__).resolve().parents[1] / 'app' / 'templates' / 'game'
    pat = re.compile(
        r'block\s+game_head[\s\S]*?<meta\s+(?:name="description"|property="og:|name="twitter:)',
        re.I,
    )
    offenders = [
        str(p.relative_to(game_dir.parent))
        for p in game_dir.glob('*.html')
        if pat.search(p.read_text(encoding='utf-8'))
    ]
    assert not offenders, offenders


def test_programme_pages_use_programme_specific_meta_description(client, db):
    generic = 'sense-making system that turns disagreement into understanding'
    html = _get(client, db, '/programmes/')
    assert generic not in re.search(r'name="description"[^>]*content="([^"]+)"', html, re.S).group(1)


def test_play_hub_has_single_meta_description(client, db):
    resp = client.get('/play/', follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert html.count('name="description"') == 1


def test_brief_archive_page_two_is_noindexed(client, db):
    html = client.get('/brief/archive?page=2').get_data(as_text=True)
    assert re.search(r'name="robots"[^>]*content="[^"]*noindex', html, re.S)


def test_sources_filtered_view_is_noindexed(client, db):
    html = client.get('/sources/?q=bbc').get_data(as_text=True)
    assert re.search(r'name="robots"[^>]*content="[^"]*noindex', html, re.S)


def test_source_profile_page_two_is_noindexed(client, db):
    from app.models import NewsSource

    with client.application.app_context():
        db.create_all()
        source = NewsSource(
            name='Test Source SEO',
            slug='test-source-seo',
            feed_url='https://example.com/rss',
            is_active=True,
        )
        db.session.add(source)
        db.session.commit()
        slug = source.slug

    html = client.get(f'/sources/{slug}?page=2').get_data(as_text=True)
    assert re.search(r'name="robots"[^>]*content="[^"]*noindex', html, re.S)
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    assert canonical and canonical.group(1).endswith(f'/sources/{slug}')


def test_underreported_has_page_specific_meta_and_social(client, db):
    html = _get(client, db, '/brief/underreported')
    generic = 'sense-making system that turns disagreement into understanding'
    desc = re.search(r'name="description"[^>]*content="([^"]+)"', html, re.S)
    og_desc = re.search(r'property="og:description"[^>]*content="([^"]+)"', html, re.S)
    assert desc and generic not in desc.group(1)
    assert og_desc and 'underreported' in og_desc.group(1).lower() or 'blindspot' in og_desc.group(1).lower()
    assert html.count('rel="canonical"') == 1


def test_llms_txt_uses_canonical_url_patterns(client, db):
    text = client.get('/llms.txt').get_data(as_text=True)
    assert 'https://societyspeaks.io/brief/today' not in text
    assert 'https://societyspeaks.io/daily\n' not in text
    assert '/daily/YYYY-MM-DD' in text
    assert '/brief/YYYY-MM-DD' in text
    assert '/brief/archive' in text
    assert '/brief/underreported' in text
    assert 'Canonical URL patterns' in text


def test_indexable_templates_with_canonical_define_social_blocks():
    """Public templates must not fall back to generic layout OG/Twitter defaults."""
    import re
    from pathlib import Path

    templates = Path(__file__).resolve().parents[1] / 'app' / 'templates'
    skip = {
        'layout.html',
        'macros.html',
        'game/base.html',
    }
    skip_prefixes = ('auth/', 'admin/', 'errors/', 'settings/', 'partner/portal/', 'trending/')
    pat_noindex = re.compile(
        r'block meta_robots\s*%}\s*noindex',
        re.I,
    )
    offenders = []
    for path in templates.rglob('*.html'):
        rel = str(path.relative_to(templates))
        if path.name in skip or any(rel.startswith(p) for p in skip_prefixes):
            continue
        text = path.read_text(encoding='utf-8')
        if 'extends' not in text or 'layout.html' not in text:
            continue
        if 'block canonical' not in text:
            continue
        if pat_noindex.search(text):
            continue
        for block in ('og_title', 'og_description', 'twitter_title', 'twitter_description'):
            if f'block {block}' not in text:
                offenders.append(f'{rel} missing {block}')
                break
    assert not offenders, 'Indexable templates missing social blocks:\n' + '\n'.join(offenders[:20])


def test_help_hub_og_description_is_page_specific(client, db):
    html = _get(client, db, '/help/')
    generic = 'Discover where society agrees, where it divides'
    og_desc = re.search(r'property="og:description"[^>]*content="([^"]+)"', html, re.S)
    assert og_desc and generic not in og_desc.group(1)
    assert 'Help' in og_desc.group(1) or 'help' in og_desc.group(1).lower()


def test_every_template_compiles(client):
    """Every Jinja template parses — catches unclosed {% if %}/{% block %} tags
    in templates no render test exercises (e.g. public briefing archive)."""
    from pathlib import Path

    env = client.application.jinja_env
    root = Path(client.application.template_folder)
    broken = []
    for path in root.rglob('*.html'):
        try:
            env.parse(path.read_text(encoding='utf-8'))
        except Exception as exc:  # noqa: BLE001 - report all, fail once
            broken.append(f'{path.relative_to(root)}: {exc}')
    assert not broken, 'Templates with syntax errors:\n' + '\n'.join(broken)

