"""Server-side PostHog helpers and process lifecycle.

Architecture (intentional):

- **Never** call ``posthog.flush()`` on the HTTP request path. It blocks on the
  PostHog API and harms TTFB / Core Web Vitals. Capture only; the SDK batches.

- **Gunicorn**: ``preload_app`` is **off** (see gunicorn_config.py — preloading
  monkey-patches the master and breaks worker reaping), so each worker builds
  its own PostHog client at app import and no fork handling is needed.
  :func:`reinitialize_posthog_after_fork` is retained (tested, unwired) in case
  a preload configuration ever returns (PostHog/posthog-python#290).

- **Gevent**: monkey-patched ``queue.Queue`` lacks ``all_tasks_done``, so
  ``flush()``/``shutdown()`` can raise ``AttributeError``. Drain is best-effort;
  do not let that fail worker exit.

- **Drain on shutdown**: ``register_posthog_atexit()`` (from ``create_app``) and
  ``gunicorn`` ``worker_exit`` call ``shutdown_server_posthog()``.

- **Best-effort delivery**: SIGKILL, OOM, or hard crashes can lose buffered events.
  For revenue‑critical attribution, persist facts in your DB first; analytics mirror
  that truth.

- **Frontend analytics** (snippet in ``layout.html``) are separate from this module.
"""
from __future__ import annotations

import atexit
import logging
from typing import Any, Optional

_shutdown_done = False
_log = logging.getLogger(__name__)


def configure_posthog_credentials(
    api_key: str,
    host: str,
    *,
    debug: bool = False,
) -> None:
    """Set module-level PostHog credentials used by ``capture`` / ``setup``.

    Does not force a client to start; the first capture (or an explicit
    :func:`reinitialize_posthog_after_fork`) creates the default client.
    """
    import posthog as ph

    # api_key drives setup(); project_api_key is what our call-site guards check.
    ph.api_key = api_key
    ph.project_api_key = api_key
    ph.host = host
    ph.debug = debug


def reinitialize_posthog_after_fork() -> None:
    """Replace any pre-fork PostHog client with a worker-local one.

    Safe to call when PostHog is not configured (no-op). Currently unwired:
    preload_app is off, so workers never inherit a pre-fork client. Wire this
    into a post-fork hook again only if preload_app is ever re-enabled.
    """
    global _shutdown_done
    try:
        import posthog as ph

        api_key = getattr(ph, "api_key", None) or getattr(ph, "project_api_key", None)
        if not api_key:
            return

        # Drop inherited client/consumers from the master process.
        old = getattr(ph, "default_client", None)
        if old is not None:
            try:
                old.shutdown()
            except Exception:
                pass
            ph.default_client = None

        _shutdown_done = False
        # setup() builds a fresh Client + consumer threads for this worker.
        if hasattr(ph, "setup"):
            ph.setup()
        _log.info("PostHog client reinitialized after fork")
    except Exception as exc:
        _log.warning("PostHog post-fork reinitialize failed: %s", exc)


def _drain_client_queue(client: Any, timeout: float = 3.0) -> None:
    """Wait for the client's consumer threads to empty the capture queue.

    ``flush()`` relies on ``Queue.all_tasks_done``, which gevent's patched
    Queue lacks — so under gunicorn+gevent it raises AttributeError and the
    tail batch of events was lost on every worker exit. Polling ``qsize()``
    needs nothing gevent lacks: the consumer keeps uploading batches while we
    (cooperatively) sleep, achieving a real drain instead of a tolerated loss.
    """
    import time

    queue = getattr(client, "queue", None)
    if queue is None:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if queue.qsize() == 0:
                return
        except Exception:
            return
        time.sleep(0.05)
    _log.warning(
        "PostHog queue not fully drained at shutdown (%s events left)",
        queue.qsize(),
    )


def shutdown_server_posthog() -> None:
    """Drain and shut down the PostHog client for this OS process.

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
        client = getattr(ph, "default_client", None)
        if client is not None:
            _drain_client_queue(client)
        # flush()/shutdown() still raise AttributeError on gevent's Queue
        # (no all_tasks_done); after the drain above they have nothing left
        # to save, so swallowing the error no longer loses events.
        try:
            ph.flush()
        except AttributeError:
            pass
        try:
            ph.shutdown()
        except AttributeError:
            pass
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


def request_is_scripted_client() -> bool:
    """True when the current request's User-Agent is a known scripted client.

    Reuses the aggressive session-policy list (python-requests, curl, headless
    browsers, declared bots). Returns False outside a request context or when
    no User-Agent is present, so cron/scheduler captures are unaffected.
    """
    try:
        from app.lib.session_policy import (
            SESSION_SKIP_UA_INDICATORS,
            user_agent_is_bot,
        )

        ua = _get_request_user_agent()
        if not ua:
            return False
        return user_agent_is_bot(ua, SESSION_SKIP_UA_INDICATORS)
    except Exception:
        return False


def request_is_prefetch() -> bool:
    """True when the current request is a link prefetch / preview, not a human view.

    Detects the standard, explicit signals email clients and browsers send when
    they fetch a link *before* a human opens it — mail scanners, Apple Mail /
    Safari link previews, Chrome/Firefox prefetch:

    - ``Sec-Purpose: prefetch`` / ``prerender`` (Fetch Metadata standard)
    - ``Purpose: prefetch``
    - ``X-Purpose: prefetch`` / ``preview``
    - ``X-Moz: prefetch``

    High precision by design: a human clicking the link sends none of these, so
    gating the GET-fired ``email_vote_confirm_viewed`` on this never drops a real
    view. Unlike a User-Agent or cookie heuristic it won't skip a first-time
    human, so the confirm-viewed step stays symmetric with the (ungated) POST
    ``email_vote_confirmed`` and the funnel cannot go negative. Returns False
    outside a request context.
    """
    try:
        from flask import request

        headers = request.headers
        sec_purpose = (headers.get('Sec-Purpose') or '').lower()
        if 'prefetch' in sec_purpose or 'prerender' in sec_purpose:
            return True
        if (headers.get('Purpose') or '').strip().lower() == 'prefetch':
            return True
        if (headers.get('X-Purpose') or '').strip().lower() in ('prefetch', 'preview'):
            return True
        if (headers.get('X-Moz') or '').strip().lower() == 'prefetch':
            return True
        return False
    except Exception:
        # Outside a request context (cron/scheduler) there is no prefetch signal.
        return False


def request_has_browser_evidence() -> bool:
    """True when the current request demonstrably comes from a JS-executing browser.

    The only reliable crawler signal at our traffic mix is cookie carriage:
    most crawlers present ordinary browser User-Agents but never execute the
    PostHog JS snippet, so they never send the ``ph_<key>_posthog`` cookie
    (measured 2026-07: 6,952 of 6,962 ``journey_started`` distinct_ids had no
    client-side event, ~99.9% crawler share). Use this to gate any server-side
    capture that fires on a bare GET; action-gated events (votes, POSTs) do
    not need it. Trade-off: a human's very first page render is skipped too —
    they are captured on any subsequent navigation once the cookie exists.
    """
    if request_is_scripted_client():
        return False
    return posthog_js_distinct_id() is not None


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


def email_subscriber_distinct_id(email: Optional[str]) -> Optional[str]:
    """Stable, pseudonymous ``distinct_id`` for an email-only (no account) person.

    Email subscribers have no user id and (for cron-sent digests) no browser
    cookie, so their email is the only stable identifier tying together
    subscribe -> digest_sent -> one-click vote -> unsubscribe. We hash it so raw
    PII never becomes a PostHog distinct_id (which surfaces in exports/URLs),
    while staying identical across every one of that subscriber's events.

    Must be used for *all* email-keyed events so they share one identity. Returns
    ``None`` for a falsy email.
    """
    if not email:
        return None
    import hashlib

    normalized = str(email).strip().lower()
    return "subscriber:" + hashlib.sha256(normalized.encode()).hexdigest()[:32]


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


def stitch_email_subscriber_posthog_identity(
    subscriber_email: Optional[str],
) -> Optional[str]:
    """Merge a browser PostHog person into the email-subscriber canonical id.

    Email vote funnels must attribute to ``subscriber:<hash>`` so confirm-viewed
    and confirmed events stitch across sessions and devices. When the visitor
    already has a JS cookie distinct_id, alias it into the subscriber hash before
    capture so server events join the same person as prior pageviews.
    """
    canonical = email_subscriber_distinct_id(subscriber_email)
    if not canonical:
        return None
    js_id = posthog_js_distinct_id()
    if js_id and js_id != canonical:
        try:
            import posthog as ph

            # Match safe_posthog_capture's readiness check so alias and capture
            # agree on whether PostHog is configured.
            if not getattr(ph, "project_api_key", None):
                return canonical
            ph.alias(previous_id=js_id, distinct_id=canonical)
        except Exception as exc:
            _log.warning(
                "PostHog alias %s -> %s failed: %s",
                js_id,
                canonical,
                exc,
            )
    return canonical


def stitch_posthog_on_user_login(
    user: Any,
    *,
    subscriber_email: Optional[str] = None,
    event: str = "user_logged_in",
    properties: Optional[dict] = None,
    identify_properties: Optional[dict] = None,
) -> None:
    """Merge anonymous/subscriber PostHog persons into an authenticated user.

    Call immediately after ``login_user`` on magic-link paths so email-acquired
    anonymous events (``subscriber:<hash>``, JS cookie UUID) stitch to
    ``str(user.id)`` — matching the frontend ``identify('<id>')`` in
    ``layout.html``.
    """
    if user is None or not getattr(user, "id", None):
        return
    try:
        import posthog as ph

        if not (getattr(ph, "api_key", None) or getattr(ph, "project_api_key", None)):
            return

        canonical = str(user.id)
        prior: list[str] = []
        js_id = posthog_js_distinct_id()
        if js_id and js_id != canonical:
            prior.append(js_id)
        sub_hash = email_subscriber_distinct_id(subscriber_email)
        if sub_hash and sub_hash != canonical and sub_hash not in prior:
            prior.append(sub_hash)

        for previous_id in prior:
            try:
                ph.alias(previous_id=previous_id, distinct_id=canonical)
            except Exception as exc:
                _log.warning(
                    "PostHog alias %s -> %s failed: %s",
                    previous_id,
                    canonical,
                    exc,
                )

        id_props = identify_properties or {
            "email": getattr(user, "email", None),
            "username": getattr(user, "username", None),
        }
        safe_posthog_capture(
            posthog_client=ph,
            distinct_id=canonical,
            event=event,
            properties=properties or {},
            identify_properties={k: v for k, v in id_props.items() if v},
        )
    except Exception as exc:
        _log.warning(
            "PostHog login stitch failed for user %s: %s",
            getattr(user, "id", None),
            exc,
        )


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
        _log.warning("Skipping PostHog event %s — no distinct_id", event)
        return
    # Scripted clients (python-requests, curl, declared bots) are never worth
    # capturing; UA-based filtering downstream cannot recover once they are in.
    # Browser-UA crawlers are NOT caught here — page-load-triggered call sites
    # must additionally gate on request_has_browser_evidence().
    if request_is_scripted_client():
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
    except Exception as exc:
        # Analytics must never break product flows, but failures must be visible.
        _log.warning("PostHog capture failed for event %s: %s", event, exc)
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
    except Exception as exc:
        _log.warning("PostHog system capture failed for event %s: %s", event, exc)
