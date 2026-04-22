"""
HTTP(S) probe helpers for journey optional-reading URLs.

Used by scripts/verify_journey_reading_links.py and unit tests (stdlib only).
"""
from __future__ import annotations

import ssl
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Browser-style User-Agent. Government / health / statistics sites
# (canada.ca, insee.fr, ifo.de, santepubliquefrance.fr, medicaid.gov,
# enecho.meti.go.jp, antidiskriminierungsstelle.de, cpahq.org) WAF-block
# or slow-path non-browser UAs, producing false-positive "dead link"
# failures even though the URLs load fine in a real browser. Since the
# probe's purpose is to answer "can a user reach these pages?", browser-
# shape UA is the honest signal.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


@dataclass
class ProbeOutcome:
    ok: bool
    status: Optional[int]
    method: str
    message: str
    soft_forbidden: bool


# Hosts that refuse automated probes (TLS fingerprinting, aggressive WAF, or
# geo-blocked from GitHub Actions / US cloud IPs) but load fine in a real
# browser. The probe flags them as "soft" failures (WARN, not FAIL) so CI
# stays green while the URLs remain discoverable to users. If any of these
# genuinely go down, users will notice — the probe is not a useful signal
# for them regardless of the soft flag.
_BOT_WALLED_HOSTS = (
    "canada.ca",
    "cjc-ccm.ca",
    "www.insee.fr",
    "www.santepubliquefrance.fr",
    "www.medicaid.gov",
    "www.enecho.meti.go.jp",
    "www.antidiskriminierungsstelle.de",
    "www.cpahq.org",
    "cep.lse.ac.uk",
    # Additional hosts seen blocking GH Actions IPs (confirmed via CI logs):
    "unfccc.int",
    "www.ccomptes.fr",
    "www.conseil-constitutionnel.fr",
    "www.conseil-etat.fr",
)


def _is_bot_walled(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _BOT_WALLED_HOSTS)


def _transient_network_error(message: str) -> bool:
    m = (message or "").lower()
    return any(
        x in m
        for x in (
            "reset by peer",
            "connection reset",
            "broken pipe",
            "remote end closed",
            "timed out",
            "timeout",
            "temporarily unavailable",
        )
    )


def _request_once(
    url: str,
    method: str,
    timeout: float,
    ctx: ssl.SSLContext,
) -> Tuple[Optional[int], Optional[str]]:
    # Request headers closer to a real browser. Some gov/WAF hosts (canada.ca,
    # insee.fr, santepubliquefrance.fr) refuse or time out requests that don't
    # look like a browser. Accept-Language is included because a handful of
    # sites 400/500 on a bare */* Accept.
    # Accept-Encoding deliberately omitted: urllib does not decompress, so the
    # response body would come back gzip-framed and we don't need it anyway
    # (status code is all we read).
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method=method,
    )
    try:
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.getcode(), None
    except HTTPError as e:
        return int(e.code), None
    except URLError as e:
        reason = getattr(e, "reason", e)
        return None, str(reason)
    except OSError as e:
        # Catches http.client.RemoteDisconnected (subclass of ConnectionResetError)
        # and other low-level socket errors that escape URLError when the peer drops
        # the connection mid-read. Without this, the probe crashes the whole thread
        # pool instead of being counted as a single-URL failure (which retries once
        # if the message matches _transient_network_error).
        return None, str(e) or type(e).__name__


def _ssl_context() -> ssl.SSLContext:
    """Prefer certifi's CA bundle so macOS / minimal CI images match Linux verify behaviour."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def probe_url(url: str, timeout: float) -> ProbeOutcome:
    """
    Prefer HEAD (cheap); retry with GET when HEAD is not allowed or looks bot-blocked.
    """
    ctx = _ssl_context()

    head_status, head_err = _request_once(url, "HEAD", timeout, ctx)
    if head_err:
        pass  # try GET
    elif head_status is not None and 200 <= head_status < 400:
        return ProbeOutcome(True, head_status, "HEAD", f"HEAD {head_status}", False)
    elif head_status == 429:
        time.sleep(2.0)
    elif head_status is not None and head_status >= 400:
        # For any non-2xx/3xx HEAD response — 4xx or 5xx — retry with GET
        # before declaring the URL dead. Empirically: German federal gov
        # sites return 400 on HEAD, INSEE/ifo/StatCan return 500/406 on
        # HEAD, and some edge CDNs return 404 on HEAD only, but all
        # answer GET successfully. If GET also errors, the URL is dead.
        pass  # try GET

    get_status, get_err = _request_once(url, "GET", timeout, ctx)
    if get_err and _transient_network_error(get_err):
        time.sleep(1.5)
        get_status, get_err = _request_once(url, "GET", timeout, ctx)
    walled = _is_bot_walled(url)
    if get_err:
        return ProbeOutcome(False, None, "GET", get_err, walled)
    if get_status == 429:
        time.sleep(2.0)
        get_status, get_err = _request_once(url, "GET", timeout, ctx)
        if get_err:
            return ProbeOutcome(False, None, "GET", get_err, walled)
    assert get_status is not None
    if 200 <= get_status < 400:
        return ProbeOutcome(True, get_status, "GET", f"GET {get_status}", False)
    soft = walled or get_status in (401, 403)
    return ProbeOutcome(False, get_status, "GET", f"GET {get_status}", soft)
