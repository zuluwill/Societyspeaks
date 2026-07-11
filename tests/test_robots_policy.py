"""Contract tests for the crawler policy in /robots.txt and the cache
headers on the discovery endpoints (robots.txt, sitemap.xml, llms.txt).

Rationale (bandwidth audit 2026-07-10): 65% of web egress was crawler
traffic, led by Meta's AI-training crawler which was previously *allowed*.
These tests pin the policy so a future robots.txt edit can't silently
re-open the tap or drop the edge-cache headers Cloudflare relies on.
"""

import re

import pytest


BLOCKED_CRAWLERS = [
    'Meta-ExternalAgent',
    'AhrefsBot',
    'SemrushBot',
    'DataForSeoBot',
    'Bytespider',
    'PetalBot',
    'MJ12bot',
    'DotBot',
    'BLEXBot',
]

# AI answer engines deliberately allowed for GEO/AI discovery — they cite
# and refer users back, unlike training-harvest crawlers.
ALLOWED_CRAWLERS = [
    'GPTBot',
    'ChatGPT-User',
    'ClaudeBot',
    'Claude-Web',
    'PerplexityBot',
    'Googlebot',
    'Bingbot',
]


def _directive_for(body, agent):
    """Return the first Allow/Disallow directive in *agent*'s UA block."""
    match = re.search(
        rf'^User-agent: {re.escape(agent)}\n((?:[A-Za-z-]+: .*\n?)+)',
        body,
        re.MULTILINE,
    )
    assert match, f'robots.txt has no block for User-agent: {agent}'
    for line in match.group(1).splitlines():
        if line.startswith(('Allow:', 'Disallow:')):
            return line
    pytest.fail(f'no Allow/Disallow directive for {agent}')


@pytest.fixture
def robots_body(client):
    response = client.get('/robots.txt')
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize('agent', BLOCKED_CRAWLERS)
def test_bandwidth_heavy_crawlers_are_disallowed(robots_body, agent):
    assert _directive_for(robots_body, agent) == 'Disallow: /'


@pytest.mark.parametrize('agent', ALLOWED_CRAWLERS)
def test_geo_crawlers_stay_allowed(robots_body, agent):
    assert _directive_for(robots_body, agent) == 'Allow: /'


def test_facebook_link_previews_not_blocked(robots_body):
    # facebookexternalhit renders FB/WhatsApp link cards; it must never get
    # an explicit Disallow block (it falls under the permissive default).
    assert not re.search(
        r'^User-agent: facebookexternalhit\nDisallow:',
        robots_body,
        re.MULTILINE | re.IGNORECASE,
    )


@pytest.mark.parametrize('path, edge_ttl', [
    # Sitemap stays short so daily brief permalinks surface within the hour;
    # robots/llms change rarely and can sit at the edge for a day.
    ('/robots.txt', 86400),
    ('/sitemap.xml', 3600),
    ('/llms.txt', 86400),
])
def test_discovery_endpoints_are_edge_cacheable(client, path, edge_ttl):
    response = client.get(path)
    assert response.status_code == 200
    cache_control = response.headers.get('Cache-Control', '')
    assert 'public' in cache_control
    assert f's-maxage={edge_ttl}' in cache_control
