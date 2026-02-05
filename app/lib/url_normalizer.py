"""
URL Normalization Utility

Provides canonical URL normalization for article lookup.
Ensures consistent matching between partner-provided URLs and stored URLs.

Usage:
    from app.lib.url_normalizer import normalize_url

    normalized = normalize_url('https://www.example.com/article?utm_source=twitter')
    # Returns: 'https://example.com/article'
"""
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
import re
import hashlib
from typing import Optional, Set, Dict


# Tracking parameters to strip (lowercase)
TRACKING_PARAMS: Set[str] = {
    # UTM parameters
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'utm_source_platform', 'utm_creative_format', 'utm_marketing_tactic',

    # Facebook/Meta
    'fbclid', 'fb_action_ids', 'fb_action_types', 'fb_source', 'fb_ref',

    # Google
    'gclid', 'gclsrc', 'dclid', 'gbraid', 'wbraid',

    # Microsoft/Bing
    'msclkid',

    # Twitter/X
    'twclid',

    # Other common tracking
    'mc_cid', 'mc_eid',  # Mailchimp
    'cmpid', 'campaignid', 'campaign_id',
    '_ga', '_gl',  # Google Analytics
    'ref', 'source', 'referrer',  # Generic referral (when used for tracking)
    'share', 'shared',
    'affiliate', 'aff_id',
    'partner', 'partner_id',
    'tracking_id', 'track',
    'click_id', 'clickid',
    'ad_id', 'adid',
    'hsCtaTracking',  # HubSpot
    'mkt_tok',  # Marketo
    's_kwcid',  # Adobe
    'trk', 'trkInfo',  # LinkedIn
    'igshid',  # Instagram
    'si',  # Spotify
    'at_medium', 'at_campaign',  # AddThis
    'nr_email_referer',  # New Relic
    '_openstat',  # OpenStat
    'xtor',  # XiTi
}

# Parameters that may define content (keep these unless in domain-specific rules)
CONTENT_PARAMS: Set[str] = {
    'id', 'article_id', 'post_id', 'page_id', 'story_id',
    'p', 'page', 'v', 'video',
    'q', 'query', 'search',
    'category', 'tag', 'section',
    'lang', 'language', 'locale',
    'edition', 'region',
}

# Domain-specific rules for known tricky publishers
DOMAIN_RULES: Dict[str, dict] = {
    # Guardian: strip /uk/ vs /us/ locale prefix from path for canonical matching
    'theguardian.com': {
        'strip_path_prefixes': ['/uk/', '/us/', '/au/', '/international/'],
        'strip_params': ['CMP', 'INTCMP'],
    },
    # Financial Times: strip various FT-specific params
    'ft.com': {
        'strip_params': ['ftcamp', 'segmentId'],
    },
    # BBC: normalize various formats
    'bbc.com': {
        'strip_params': ['at_medium', 'at_campaign', 'at_custom1', 'at_custom2', 'at_custom3', 'at_custom4'],
    },
    'bbc.co.uk': {
        'strip_params': ['at_medium', 'at_campaign', 'at_custom1', 'at_custom2', 'at_custom3', 'at_custom4'],
    },
    # New York Times
    'nytimes.com': {
        'strip_params': ['smid', 'smtyp', 'algo', 'block', 'campaign_id', 'emc', 'instance_id', 'nl', 'regi_id', 'segment_id', 'te', 'user_id'],
    },
}


def normalize_url(url: str, apply_domain_rules: bool = True) -> Optional[str]:
    """
    Normalize a URL to its canonical form.

    Normalization rules:
    - Force HTTPS scheme
    - Lowercase hostname
    - Strip 'www.' prefix from hostname
    - Strip trailing slash from path
    - Strip fragment (#...)
    - Strip tracking parameters
    - Apply domain-specific rules if enabled

    Args:
        url: The URL to normalize
        apply_domain_rules: Whether to apply domain-specific normalization rules

    Returns:
        Normalized URL string, or None if URL is invalid

    Examples:
        >>> normalize_url('http://WWW.Example.com/Article/?utm_source=twitter#comments')
        'https://example.com/article'

        >>> normalize_url('https://www.theguardian.com/uk/news/article')
        'https://theguardian.com/news/article'
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    # Must be http or https
    if parsed.scheme not in ('http', 'https'):
        return None

    # Must have a hostname
    if not parsed.netloc:
        return None

    # Force HTTPS
    scheme = 'https'

    # Lowercase and strip www. from hostname
    hostname = parsed.netloc.lower()

    # Handle port numbers
    if ':' in hostname:
        host_part, port_part = hostname.rsplit(':', 1)
        host_part = host_part.lstrip('www.')
        # Only include port if non-standard
        if port_part not in ('80', '443'):
            hostname = f"{host_part}:{port_part}"
        else:
            hostname = host_part
    else:
        hostname = hostname.lstrip('www.')

    # Normalize path
    path = parsed.path or '/'

    # Strip trailing slash (but keep root /)
    if path != '/' and path.endswith('/'):
        path = path.rstrip('/')

    # Apply domain-specific path rules
    if apply_domain_rules:
        domain_rule = _get_domain_rule(hostname)
        if domain_rule:
            # Strip path prefixes (e.g., /uk/ from Guardian)
            for prefix in domain_rule.get('strip_path_prefixes', []):
                if path.startswith(prefix):
                    rest = path[len(prefix):].lstrip('/')
                    path = '/' + rest if rest else '/'
                    break

    # Handle AMP URLs
    if '/amp/' in path or path.endswith('/amp'):
        path = path.replace('/amp/', '/').replace('/amp', '')
        if not path:
            path = '/'

    # Process query parameters
    query = ''
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=False)
        filtered_params = {}

        # Get domain-specific params to strip
        domain_strip_params = set()
        if apply_domain_rules:
            domain_rule = _get_domain_rule(hostname)
            if domain_rule:
                domain_strip_params = {p.lower() for p in domain_rule.get('strip_params', [])}

        for key, values in params.items():
            key_lower = key.lower()

            # Skip tracking params
            if key_lower in TRACKING_PARAMS:
                continue

            # Skip domain-specific params
            if key_lower in domain_strip_params:
                continue

            # Keep the param
            filtered_params[key] = values[0] if len(values) == 1 else values

        if filtered_params:
            # Sort params for consistent ordering
            query = urlencode(sorted(filtered_params.items()), doseq=True)

    # Reconstruct URL (fragment is always stripped)
    normalized = urlunparse((scheme, hostname, path, '', query, ''))

    return normalized


def _get_domain_rule(hostname: str) -> Optional[dict]:
    """
    Get domain-specific normalization rules for a hostname.

    Args:
        hostname: The hostname to look up (should already be lowercase, no www.)

    Returns:
        Domain rules dict if found, None otherwise
    """
    # Direct match
    if hostname in DOMAIN_RULES:
        return DOMAIN_RULES[hostname]

    # Try without subdomains (e.g., news.bbc.co.uk -> bbc.co.uk)
    parts = hostname.split('.')
    for i in range(len(parts) - 1):
        subdomain = '.'.join(parts[i:])
        if subdomain in DOMAIN_RULES:
            return DOMAIN_RULES[subdomain]

    return None


def url_hash(url: str, length: int = 32) -> Optional[str]:
    """
    Generate a hash of a normalized URL for fast indexing.

    Args:
        url: The URL to hash (will be normalized first)
        length: Length of hash to return (default 32 = 16 bytes of SHA-256)

    Returns:
        Hex string of hash, or None if URL is invalid

    Example:
        >>> url_hash('https://example.com/article')
        'a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6'
    """
    normalized = normalize_url(url)
    if not normalized:
        return None

    full_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return full_hash[:length]


def is_amp_url(url: str) -> bool:
    """
    Check if a URL is an AMP (Accelerated Mobile Pages) URL.

    Args:
        url: URL to check

    Returns:
        True if URL appears to be an AMP URL
    """
    if not url:
        return False

    try:
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Check path patterns
        if '/amp/' in path or path.endswith('/amp'):
            return True

        # Check query param (including ?amp without a value)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if 'amp' in query or 'amp' in [k.lower() for k in query.keys()]:
            return True
        # Also check for ?amp at the end of query string (no value, no =)
        if parsed.query.lower() == 'amp' or parsed.query.lower().startswith('amp&') or '&amp&' in parsed.query.lower() or parsed.query.lower().endswith('&amp'):
            return True

        # Check hostname patterns (Google AMP cache, etc.)
        hostname = parsed.netloc.lower()
        if hostname.endswith('.ampproject.org') or hostname.endswith('.amp.cloudflare.com'):
            return True

        return False
    except Exception:
        return False


def extract_domain(url: str) -> Optional[str]:
    """
    Extract the domain from a URL (without www. prefix).

    Args:
        url: URL to extract domain from

    Returns:
        Domain string, or None if invalid

    Example:
        >>> extract_domain('https://www.example.com/path')
        'example.com'
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        hostname = parsed.netloc.lower()

        # Remove port
        if ':' in hostname:
            hostname = hostname.rsplit(':', 1)[0]

        # Remove www.
        hostname = hostname.lstrip('www.')

        return hostname if hostname else None
    except Exception:
        return None
