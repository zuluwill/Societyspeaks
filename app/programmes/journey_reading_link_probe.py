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

USER_AGENT = (
    "SocietySpeaksJourneyLinkCheck/1.0 (repository QA; urllib; contact via project maintainer)"
)


@dataclass
class ProbeOutcome:
    ok: bool
    status: Optional[int]
    method: str
    message: str
    soft_forbidden: bool


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
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}, method=method)
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
    elif head_status in (400, 403, 404, 405, 501) or head_status == 401:
        # Many servers / CDNs (notably German federal gov sites and some CMS
        # platforms) return 400 or 404 on HEAD only; others gate HEAD behind
        # an auth check (401/403). In every case, retry with GET before
        # treating the URL as dead.
        pass  # try GET
    elif head_status is not None and head_status >= 400:
        return ProbeOutcome(False, head_status, "HEAD", f"HEAD {head_status}", False)

    get_status, get_err = _request_once(url, "GET", timeout, ctx)
    if get_err and _transient_network_error(get_err):
        time.sleep(1.5)
        get_status, get_err = _request_once(url, "GET", timeout, ctx)
    if get_err:
        return ProbeOutcome(False, None, "GET", get_err, False)
    if get_status == 429:
        time.sleep(2.0)
        get_status, get_err = _request_once(url, "GET", timeout, ctx)
        if get_err:
            return ProbeOutcome(False, None, "GET", get_err, False)
    assert get_status is not None
    if 200 <= get_status < 400:
        return ProbeOutcome(True, get_status, "GET", f"GET {get_status}", False)
    soft = get_status in (401, 403)
    return ProbeOutcome(False, get_status, "GET", f"GET {get_status}", soft)
