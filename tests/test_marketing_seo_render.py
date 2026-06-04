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


def test_donate_page_renders_funding_story(client, db):
    resp = client.get('/donate')
    assert resp.status_code == 200, resp.status_code
    html = resp.get_data(as_text=True)
    assert 'How we sustain the platform' in html
    assert html.count('rel="canonical"') == 1


def test_faq_funding_jsonld_matches_visible(client, db):
    """New funding Q&A: JSON-LD entries must also be visible (Google policy)."""
    html = _get(client, db, '/faq')
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    faq = next(json.loads(b) for b in blocks if json.loads(b).get('@type') == 'FAQPage')
    names = [q['name'] for q in faq['mainEntity']]
    for n in ('How is Society Speaks funded?',
              'What do publishers pay for embeds and the Partner API?'):
        assert n in names, f"missing from JSON-LD: {n}"
        assert n in html, f"in JSON-LD but not visible: {n}"
