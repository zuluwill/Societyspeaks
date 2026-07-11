"""PostHog events for Society Play (Tradeoffs)."""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    import posthog
except ImportError:
    posthog = None

from app.lib.posthog_utils import (
    posthog_js_distinct_id,
    request_has_browser_evidence,
    safe_posthog_capture,
)
from app.models.game import GameRun

# Events emitted by a bare GET (run rows are created on page load — see
# routes.quick_run). Crawlers with ordinary browser UAs inflated these ~40x
# (2026-07: ~800 single-run fingerprints vs ~20 players with completed turns),
# so they require browser evidence. Turn/completion events are POST-driven
# and exempt.
_PAGE_LOAD_EVENTS = frozenset({'game_run_started'})


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
    if event in _PAGE_LOAD_EVENTS and not request_has_browser_evidence():
        return
    props = {
        'run_uuid': run.uuid,
        'scenario_slug': run.scenario_slug,
        'mode': run.mode,
        'turn_index': run.turn_index,
        'total_turns': run.total_turns,
    }
    if properties:
        props.update(properties)
    safe_posthog_capture(
        posthog_client=posthog,
        distinct_id=_distinct_id_for_run(run),
        event=event,
        properties=props,
    )
