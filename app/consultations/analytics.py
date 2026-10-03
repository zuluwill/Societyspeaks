"""PostHog events for the consultation product.

Host screens turn autocapture and session recording off, because those screens
show a customer's question and results. These server events are the record of
the funnel instead. They carry the account id, counts, the campaign that
brought the host and a few billing facts. They never carry the question, the
organisation, the statements, or a link token.
"""
from typing import Optional

from flask import current_app, has_request_context

# Anything else a caller passes is dropped, so a question cannot ride along.
_PROPERTIES = frozenset({
    'consultation_id',
    'consultation_number',
    'covered_by',
    'plan',
    'amount_pence',
    'currency',
    'revenue',
    'domain_repeat',
    'existing_account',
    'statement_count',
    'trial_days',
    'channel',
    'participant_count',
    'vote_count',
    'closed_by',
    'format',
    'report_kind',
    'acquisition_source',
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_term',
})


def _clean(value) -> str:
    """Campaign values keep letters, numbers and ``._-`` only, so nothing personal can be stored."""
    return ''.join(ch for ch in str(value or '').strip().lower() if ch.isalnum() or ch in '._-')[:80]


def campaign_params() -> dict:
    """The UTMs of the visit that brought the host, cleaned, for carrying through a sign-in link."""
    if not has_request_context():
        return {}
    from app.lib.utm import UTM_KEYS, peek_utms
    return {key: _clean(value) for key, value in peek_utms().items() if key in UTM_KEYS and _clean(value)}


def acquisition_properties() -> dict:
    """``utm_*`` plus ``acquisition_source`` (the utm_source, or ``direct``)."""
    params = campaign_params()
    return {**params, 'acquisition_source': params.get('utm_source') or 'direct'}


def capture_consultation_event(
    event: str,
    *,
    user_id: Optional[int],
    insert_id: str,
    properties: Optional[dict] = None,
    durable: bool = False,
    attribution: bool = False,
) -> None:
    """Record one funnel event. Never raises, and does nothing without PostHog.

    ``attribution=True`` adds the campaign that brought the host, and records it
    once on the person (``first_consultation_source`` and friends) so every
    later event, payments included, can be broken down by it.
    """
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
        merged = {**(acquisition_properties() if attribution else {}), **(properties or {})}
        safe = {key: merged[key] for key in _PROPERTIES if key in merged and merged[key] is not None}
        if attribution:
            safe['$set_once'] = {
                'first_consultation_source': safe.get('acquisition_source', 'direct'),
                'first_consultation_medium': safe.get('utm_medium'),
                'first_consultation_campaign': safe.get('utm_campaign'),
            }
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
