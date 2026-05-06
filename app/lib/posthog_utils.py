from __future__ import annotations

from typing import Any, Optional


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
    flush: bool = False,
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
        if flush and hasattr(posthog_client, "flush"):
            posthog_client.flush()
    except Exception:
        # Intentionally swallow: analytics must never break product flows.
        return
