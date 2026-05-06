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
    """
    if not posthog_client or not getattr(posthog_client, "project_api_key", None):
        return

    try:
        props = dict(properties or {})
        if "$raw_user_agent" not in props:
            ua = _get_request_user_agent()
            if ua:
                props["$raw_user_agent"] = ua

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
