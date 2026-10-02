"""PostHog events for the consultation product.

Host screens turn autocapture and session recording off, because those screens
show a customer's question and results. These server events are the record of
the funnel instead. They carry the account id and a few billing facts. They
never carry the question, the organisation, the statements, or a link token.
"""
from typing import Optional

from flask import current_app

# Anything else a caller passes is dropped, so a question cannot ride along.
_PROPERTIES = frozenset({
    'consultation_id',
    'covered_by',
    'plan',
    'amount_pence',
    'currency',
    'domain_repeat',
})


def capture_consultation_event(
    event: str,
    *,
    user_id: Optional[int],
    insert_id: str,
    properties: Optional[dict] = None,
    durable: bool = False,
) -> None:
    """Record one funnel event. Never raises, and does nothing without PostHog."""
    if not user_id:
        return
    try:
        import posthog

        if not posthog or not getattr(posthog, 'project_api_key', None):
            return
        from app.lib.posthog_utils import resolve_request_distinct_id, safe_posthog_capture

        distinct_id = resolve_request_distinct_id(user_id=user_id)
        if not distinct_id:
            return
        safe = {key: properties[key] for key in _PROPERTIES if properties and key in properties}
        safe_posthog_capture(
            posthog_client=posthog,
            distinct_id=distinct_id,
            event=event,
            properties=safe,
            insert_id=insert_id,
            durable=durable,
        )
    except Exception:
        current_app.logger.warning('Consultation analytics event %s was not sent', event, exc_info=True)
