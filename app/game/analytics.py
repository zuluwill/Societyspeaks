"""PostHog events for Society Play (Tradeoffs)."""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    import posthog
except ImportError:
    posthog = None

from app.lib.posthog_utils import (
    posthog_js_distinct_id,
    safe_posthog_capture,
)
from app.lib.request_user import current_user_is_authenticated
from app.lib.subscriber_identity import read_subscriber_ref
from app.models.game import GameRun

_GAME_TRAFFIC_SOURCES = frozenset({
    'brief_email',
    'daily_question_email',
    'direct',
    'organic',
    'social',
})


def resolve_game_traffic_source() -> Optional[str]:
    """Best-effort attribution for Society Play entry (email ref, UTM, ?source=)."""
    try:
        from flask import has_request_context, request

        if not has_request_context():
            return None

        explicit = (request.args.get('source') or '').strip().lower()
        if explicit in _GAME_TRAFFIC_SOURCES:
            return explicit

        utm_source = (request.args.get('utm_source') or '').strip().lower()
        if utm_source in ('brief_email', 'daily_brief', 'daily-brief'):
            return 'brief_email'
        if utm_source in ('daily_question', 'daily-question', 'daily_question_email'):
            return 'daily_question_email'

        ref = read_subscriber_ref()
        if ref:
            if ref.get('b'):
                return 'brief_email'
            if ref.get('q'):
                return 'daily_question_email'
    except Exception:
        return None
    return None

def resolve_distinct_id_for_run(run: GameRun) -> str:
    """Resolve the PostHog identity for ``run`` at creation time.

    Mirrors what the JS SDK uses so server events stitch to the same person:
    plain ``str(user_id)`` for logged-in players (the JS SDK calls
    ``identify('<id>')``), otherwise the browser's PostHog cookie ``distinct_id``
    when available, falling back to the durable session fingerprint, then the
    run uuid. No ``user:``/``anon:`` prefixes — those were the reason logged-in
    server events (``user:14``) never matched JS pageviews (``14``).
    """
    if run.user_id:
        return str(run.user_id)
    js_id = posthog_js_distinct_id()
    if js_id:
        return js_id
    if run.session_fingerprint:
        return run.session_fingerprint
    return run.uuid


def _distinct_id_for_run(run: GameRun) -> str:
    # Logged-in identity always wins (matches the JS SDK's identify()), even if
    # the run was stamped while anonymous and the player has since logged in.
    if run.user_id:
        return str(run.user_id)
    stored = getattr(run, 'posthog_distinct_id', None)
    if stored:
        return stored
    return resolve_distinct_id_for_run(run)


def track_game_event(
    run: GameRun,
    event: str,
    *,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """Fire a game analytics event; never raises into callers."""
    try:
        props = {
            'run_uuid': run.uuid,
            'scenario_slug': run.scenario_slug,
            'mode': run.mode,
            'turn_index': run.turn_index,
            'total_turns': run.total_turns,
            'is_authenticated': current_user_is_authenticated(),
        }
        if properties:
            props.update(properties)
        if 'source' not in props:
            traffic_source = resolve_game_traffic_source()
            if traffic_source:
                props['source'] = traffic_source
        safe_posthog_capture(
            posthog_client=posthog,
            distinct_id=_distinct_id_for_run(run),
            event=event,
            properties=props,
        )
    except Exception:
        # Analytics must never break run creation / choice application.
        return
