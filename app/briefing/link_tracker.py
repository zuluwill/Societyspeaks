"""
Email click-tracking utilities for briefing emails.

Every eligible link in an outgoing briefing email is rewritten through
/briefings/track/click/<run_id> so we can measure engagement without
relying on a third-party provider (e.g. Resend click-tracking).

Security model
--------------
Each tracking URL carries an HMAC-SHA256 signature derived from the
Flask SECRET_KEY, the run_id, and the target URL.  The route verifies
the signature before redirecting, which eliminates the open-redirect
risk without needing a hardcoded domain allow-list.

Exclusions (never wrapped)
--------------------------
- Unsubscribe links  – one-click unsubscribe must go directly to avoid
                       breaking RFC 8058 compliance and spam-filter signals.
- mailto: / tel:     – not real navigable URLs.
- Anchor (#) links   – same-page jumps; nothing useful to track.
"""

import re
import hmac
import hashlib
from html import unescape
from urllib.parse import urlencode, urlparse


# Matches the href attribute of any <a> tag.
# Groups:
#   1 - everything from '<a' up to (but not including) the whitespace before 'href'
#   2 - quote character (" or ')
#   3 - the raw href value
#   4 - the rest of the tag from the closing quote up to and including '>'
_RE_HREF = re.compile(
    r'(<a\b[^>]*?)\s+href=(["\'])([^"\']+)\2([^>]*>)',
    re.IGNORECASE | re.DOTALL,
)


def _should_skip(url: str) -> bool:
    """Return True for URLs that must never be wrapped."""
    s = url.strip().lower()
    if not s or s.startswith('#'):
        return True
    if s.startswith(('mailto:', 'tel:')):
        return True
    if 'unsubscribe' in s:
        return True
    return False


def _link_type(url: str, base_url: str) -> str:
    """Classify a URL as 'view', 'internal', or 'article'."""
    s = url.lower()
    base = base_url.lower().rstrip('/')
    if s.startswith(base):
        if any(k in s for k in ('/reader', '/view', '/m/', '/brief')):
            return 'view'
        return 'internal'
    return 'article'


def sign_url(run_id: int, target_url: str, secret: str) -> str:
    """Return a 24-character HMAC-SHA256 hex digest for this (run_id, url) pair."""
    msg = f"{run_id}:{target_url}".encode('utf-8')
    return hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()[:24]


def verify_url(run_id: int, target_url: str, signature: str, secret: str) -> bool:
    """Constant-time HMAC comparison to validate a tracking URL."""
    expected = sign_url(run_id, target_url, secret)
    return hmac.compare_digest(expected, signature)


def make_tracked_url(
    base_url: str,
    run_id: int,
    target_url: str,
    recipient_hash: str,
    secret: str,
    link_type: str = 'article',
    track_path: str = '/briefings/track/click',
) -> str:
    """Build a signed tracking redirect URL."""
    sig = sign_url(run_id, target_url, secret)
    params = urlencode({
        'url': target_url,
        'sig': sig,
        'r': recipient_hash,
        't': link_type,
    })
    return f"{base_url}{track_path}/{run_id}?{params}"


def recipient_hash(run_id: int, email: str) -> str:
    """Stable, anonymised identifier for a recipient within a specific run."""
    raw = f"{run_id}:{email.lower().strip()}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def wrap_links(
    html: str,
    base_url: str,
    run_id: int,
    r_hash: str,
    secret: str,
    track_path: str = '/briefings/track/click',
) -> str:
    """
    Rewrite all eligible <a href="..."> links in *html* through the tracking
    redirect endpoint.

    Unsubscribe links, anchors, mailto:, and tel: are left untouched.
    HTML entities in href values (e.g. &amp;) are decoded before signing
    so the target URL is always valid when the user arrives.

    track_path controls which server endpoint handles the redirect, e.g.
    '/briefings/track/click' (default), '/brief/track/click', or
    '/daily/track/click'.
    """
    def _replace(match: re.Match) -> str:
        prefix = match.group(1)
        quote = match.group(2)
        raw_url = match.group(3)
        suffix = match.group(4)

        if _should_skip(raw_url):
            return match.group(0)

        target = unescape(raw_url)

        ltype = _link_type(target, base_url)
        tracked = make_tracked_url(base_url, run_id, target, r_hash, secret, ltype, track_path=track_path)
        return f'{prefix} href={quote}{tracked}{quote}{suffix}'

    return _RE_HREF.sub(_replace, html)
