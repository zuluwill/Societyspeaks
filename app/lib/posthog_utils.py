from __future__ import annotations

from typing import Any, Optional


def safe_posthog_capture(
    *,
    posthog_client: Any,
    distinct_id: str,
    event: str,
    properties: Optional[dict] = None,
    flush: bool = False,
    identify_properties: Optional[dict] = None,
) -> None:
    """Capture (and optionally identify) in PostHog, never raising into callers."""
    if not posthog_client or not getattr(posthog_client, "project_api_key", None):
        return

    try:
        posthog_client.capture(
            distinct_id=str(distinct_id),
            event=event,
            properties=properties or {},
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

