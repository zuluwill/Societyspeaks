"""Server-side PostHog helpers and process lifecycle.

Architecture (intentional):

- **Never** call ``posthog.flush()`` on the HTTP request path. It blocks on the
  PostHog API and harms TTFB / Core Web Vitals. Capture only; the SDK batches.

- **Drain on shutdown**: ``register_posthog_atexit()`` (from ``create_app``) and
  ``gunicorn`` ``worker_exit`` call ``shutdown_server_posthog()`` so each worker
  flushes its queue when the process exits gracefully (including ``max_requests``
  recycle). This matches multi-worker deployments with ``preload_app=True``.

- **Best-effort delivery**: SIGKILL, OOM, or hard crashes can lose buffered events.
  For revenue‑critical attribution, persist facts in your DB first; analytics mirror
  that truth.

- **Frontend analytics** (snippet in ``layout.html``) are separate from this module.
"""
from __future__ import annotations

import atexit
from typing import Any, Optional

_shutdown_done = False


def shutdown_server_posthog() -> None:
    """Flush and shut down the PostHog client for this OS process.

    Safe to call multiple times (e.g. gunicorn ``worker_exit`` + interpreter
    ``atexit``). No-ops when the SDK was not configured.
    """
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    try:
        import posthog as ph

        if not (
            getattr(ph, "api_key", None) or getattr(ph, "project_api_key", None)
        ):
            return
        ph.flush()
        ph.shutdown()
    except Exception:
        pass


def register_posthog_atexit(registrar=None) -> None:
    """Register :func:`shutdown_server_posthog` for normal interpreter exit.

    Tests may pass a ``registrar`` callable (signature matching ``atexit.register``).
    """
    _reg = registrar if registrar is not None else atexit.register
    _reg(shutdown_server_posthog)


def _get_request_user_agent() -> Optional[str]:
    """Return the current request's user-agent string, or None outside request context."""
    try:
        from flask import request
        return request.headers.get("User-Agent")
    except Exception:
        return None


def posthog_js_distinct_id() -> Optional[str]:
    """Return the PostHog JS SDK's ``distinct_id`` for the current request.

    The browser SDK persists its identity in a cookie named
    ``ph_<POSTHOG_API_KEY>_posthog`` whose value is a (URL-encoded) JSON blob.
    Reusing that ``distinct_id`` as the server-side ``distinct_id`` is what
    stitches server events to the same person PostHog already tracks for
    pageviews — no ``$identify``/``alias`` round-trip required (same id == same
    person). Returns ``None`` outside a request, when analytics is unconfigured,
    or when the cookie is absent (first visit / cleared) so callers can fall
    back to a stable server-side identity (e.g. a fingerprint).
    """
    try:
        import json
        from urllib.parse import unquote

        from flask import current_app, request

        api_key = current_app.config.get("POSTHOG_API_KEY")
        if not api_key:
            return None
        raw = request.cookies.get(f"ph_{api_key}_posthog")
        if not raw:
            return None
        data = json.loads(unquote(raw))
        distinct_id = data.get("distinct_id")
        if isinstance(distinct_id, str) and distinct_id.strip():
            return distinct_id.strip()
        return None
    except Exception:
        return None


def resolve_request_distinct_id(
    user_id: Any = None,
    anon_fallback: Optional[str] = None,
) -> Optional[str]:
    """Canonical server-side ``distinct_id`` for an event fired during a request.

    The single source of truth for identity so server events stitch to the JS
    SDK's person (and to each other):

    - **Logged-in** → ``str(user_id)``, matching the JS SDK's ``identify('<id>')``.
    - **Anonymous** → the browser's PostHog cookie ``distinct_id`` when present
      (so server events join the same person as JS pageviews), else the supplied
      durable ``anon_fallback`` (e.g. a vote fingerprint or session id) so the
      event still attributes to a stable identity rather than fragmenting.

    Returns ``None`` only when anonymous with no cookie and no fallback, letting
    callers skip the capture rather than invent an id.
    """
    if user_id:
        return str(user_id)
    js_id = posthog_js_distinct_id()
    if js_id:
        return js_id
    if anon_fallback:
        return str(anon_fallback)
    return None


# Path/route argument names that carry secrets (magic-link / unsubscribe /
# preferences tokens, signatures, one-time codes). Their values must never reach
# analytics, so we redact them out of any URL we attach to events.
_SENSITIVE_URL_ARG_HINTS = (
    "token",
    "secret",
    "signature",
    "sig",
    "key",
    "code",
    "otp",
    "password",
    "passwd",
    "auth",
)


def _is_sensitive_arg(name: str) -> bool:
    lowered = (name or "").lower()
    return any(hint in lowered for hint in _SENSITIVE_URL_ARG_HINTS)


def _redact_path(path: str, view_args: Optional[dict]) -> str:
    """Replace secret path segments (e.g. ``/daily/unsubscribe/<token>``) with a
    placeholder, using the matched route args so only genuine secrets are masked
    (ids, dates, slugs, uuids are preserved for analytics)."""
    redacted = path or ""
    for key, value in (view_args or {}).items():
        if value is None:
            continue
        if _is_sensitive_arg(key):
            redacted = redacted.replace(str(value), f"<{key}>")
    return redacted


def request_context_properties() -> dict:
    """Browser-context event properties derived from the current Flask request.

    Server-side SDK captures carry none of the page context the JS SDK attaches
    automatically, which is why discovery/attribution questions are unanswerable
    from server events alone. We decompose the URL ourselves rather than relying
    on PostHog to parse ``$current_url``: UTM extraction is unreliable for custom
    (non-``$pageview``) server events. Returns ``{}`` outside a request context.

    Privacy: many server events fire on token-bearing routes (magic-link login,
    one-click unsubscribe, preferences). We therefore (a) drop the query string
    from the emitted URLs so ``?token=`` style secrets never leak — campaign data
    is preserved via the explicit ``$utm_*`` keys — and (b) redact secret path
    segments via the matched route args. First-touch attribution (``$initial_*``)
    lives on the person profile via the JS SDK and cannot be reconstructed here.
    """
    try:
        from urllib.parse import parse_qs, urlparse, urlunparse

        from flask import request

        parsed = urlparse(request.url)
        query = parse_qs(parsed.query)
        view_args = getattr(request, "view_args", None) or {}

        safe_path = _redact_path(parsed.path, view_args)
        # Rebuild without query/fragment so no secret query params survive.
        safe_url = urlunparse((parsed.scheme, parsed.netloc, safe_path, "", "", ""))
        props: dict = {
            "$current_url": safe_url,
            "$host": parsed.netloc,
            "$pathname": safe_path,
        }
        referrer = request.referrer
        if referrer:
            ref = urlparse(referrer)
            # Strip the referrer's query string too; keep domain + path for funnels.
            props["$referrer"] = urlunparse((ref.scheme, ref.netloc, ref.path, "", "", ""))
            props["$referring_domain"] = ref.netloc
        for param in (
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
        ):
            value = query.get(param, [None])[0]
            if value:
                props[f"${param}"] = value
        return props
    except Exception:
        return {}


def safe_posthog_capture(
    *,
    posthog_client: Any,
    distinct_id: str,
    event: str,
    properties: Optional[dict] = None,
    identify_properties: Optional[dict] = None,
) -> None:
    """Capture (and optionally identify) in PostHog, never raising into callers.

    Automatically attaches ``$raw_user_agent`` to every server-side event so
    that PostHog's "Filter Bot Events" Data Pipeline transformation can drop
    crawler traffic without any changes to individual call sites.

    When fired inside a request, also attaches browser context (``$current_url``,
    ``$referrer``/``$referring_domain``, ``$utm_*``) so server-side events are
    attributable to discovery channels. Explicit ``properties`` always win over
    the auto-derived values. Outside a request context these are simply omitted.
    """
    if not posthog_client or not getattr(posthog_client, "project_api_key", None):
        return
    # Never invent a 'None'/empty person when identity could not be resolved.
    if not distinct_id:
        return

    try:
        props = dict(properties or {})
        if "$raw_user_agent" not in props:
            ua = _get_request_user_agent()
            if ua:
                props["$raw_user_agent"] = ua
        for key, value in request_context_properties().items():
            props.setdefault(key, value)

        posthog_client.capture(
            distinct_id=str(distinct_id),
            event=event,
            properties=props,
        )
        if identify_properties:
            posthog_client.identify(
                distinct_id=str(distinct_id),
                properties=identify_properties,
            )
    except Exception:
        # Analytics must never break product flows.
        return


def safe_system_capture(event: str, properties: Optional[dict] = None) -> None:
    """Capture a PostHog event for automated background/scheduler jobs.

    Uses ``distinct_id='system'`` because these events have no user identity
    and no HTTP request context. Unlike ``safe_posthog_capture``, this function
    intentionally omits request-context enrichment (``$current_url``, UTM tags)
    since there is no request. Always a no-op when PostHog is not configured.
    """
    try:
        import posthog as ph

        if not (getattr(ph, "api_key", None) or getattr(ph, "project_api_key", None)):
            return
        ph.capture(
            distinct_id="system",
            event=event,
            properties=dict(properties or {}),
        )
    except Exception:
        pass
