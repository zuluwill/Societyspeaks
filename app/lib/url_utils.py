from urllib.parse import urlparse


def safe_next_url(raw_url):
    """Return raw_url if it is a safe same-origin relative path, else None.

    Accepts only paths that start with '/' but not '//' (protocol-relative
    URLs) and carry no scheme or netloc, guarding against open-redirect attacks.
    """
    candidate = (raw_url or '').strip()
    if not candidate or not candidate.startswith('/') or candidate.startswith('//'):
        return None
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    return candidate
