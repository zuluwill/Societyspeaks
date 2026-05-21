"""Apply choice effects and delayed consequences."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Tuple

from app.game.engine.state import SocietyState


def process_turn_start(
    delayed_queue: List[Dict[str, Any]],
    turn_index: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fire delayed effects due on or before this turn.

    Returns (remaining_queue, fired_events). Past-due events fire defensively so
    nothing is silently dropped if a future cascade jumps turn_index.
    """
    remaining: List[Dict[str, Any]] = []
    fired: List[Dict[str, Any]] = []
    for item in delayed_queue:
        if int(item.get('fires_on_turn', -1)) <= turn_index:
            fired.append(item)
        else:
            remaining.append(item)
    return remaining, fired


def apply_choice(
    state: SocietyState,
    choice: Dict[str, Any],
    current_turn_index: int,
    total_turns: int,
    delayed_queue: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply a choice and return consequence payload for the client.

    Mutates state and delayed_queue in place. Effects schema is canonical:
    ``choice.effects.immediate`` (dict) and ``choice.effects.delayed`` (object or list).
    """
    effects = choice.get('effects') or {}
    immediate = effects.get('immediate') or {}
    applied = state.apply_deltas(immediate)

    headline = choice.get('reaction') or choice.get('flavour') or ''

    delayed_spec = effects.get('delayed')
    if delayed_spec:
        specs = delayed_spec if isinstance(delayed_spec, list) else [delayed_spec]
        for spec in specs:
            offset = int(spec.get('turn_offset', 1))
            if offset < 1:
                offset = 1
            fires_on = current_turn_index + offset
            if fires_on < total_turns:
                delayed_queue.append(
                    {
                        'fires_on_turn': fires_on,
                        'effects': spec.get('effects') or {},
                        'headline': spec.get('reaction') or spec.get('headline') or '',
                        'source_choice_id': choice.get('id'),
                    }
                )

    return {
        'headline': headline,
        'stat_deltas': applied,
        'mood_level': state.mood_level(),
    }


def apply_delayed_events(
    state: SocietyState,
    fired: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply queued delayed events at turn start."""
    headlines: List[str] = []
    total_deltas: Dict[str, int] = {}
    for event in fired:
        applied = state.apply_deltas(event.get('effects') or {})
        for key, delta in applied.items():
            total_deltas[key] = total_deltas.get(key, 0) + delta
        h = event.get('headline')
        if h:
            headlines.append(h)
    return {
        'headlines': headlines,
        'stat_deltas': total_deltas,
        'mood_level': state.mood_level(),
    }


def clone_delayed_queue(queue: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return deepcopy(queue)
