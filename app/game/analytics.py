"""PostHog events for Society Play (Tradeoffs)."""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    import posthog
except ImportError:
    posthog = None

from app.lib.posthog_utils import safe_posthog_capture
from app.models.game import GameRun


def _distinct_id_for_run(run: GameRun) -> str:
    if run.user_id:
        return f'user:{run.user_id}'
    if run.session_fingerprint:
        return f'anon:{run.session_fingerprint}'
    return f'run:{run.uuid}'


def track_game_event(
    run: GameRun,
    event: str,
    *,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """Fire a game analytics event; never raises into callers."""
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
