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


def is_safe_external_http_url(url: str) -> bool:
    """True when *url* is http(s) with a hostname Werkzeug can emit as Location.

    Click-tracking redirects call ``flask.redirect``, which runs Werkzeug
    ``iri_to_uri``. That encodes the hostname with the IDNA codec; an empty
    DNS label or a label longer than 63 bytes raises ``UnicodeError``
    (Sentry PYTHON-FLASK-JA) after the HMAC check already passed.
    """
    candidate = (url or "").strip()
    if not candidate:
        return False
    try:
        parsed = urlparse(candidate)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    try:
        host = parsed.hostname
    except Exception:
        return False
    if not host:
        return False
    try:
        host.encode("idna")
    except UnicodeError:
        return False
    return True
