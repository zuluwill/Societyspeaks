"""Scenario loading and validation."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.game.engine.validation import validate_scenario

_SCENARIOS_DIR = Path(__file__).resolve().parent.parent / 'scenarios'


def get_scenario_path(slug: str) -> Path:
    return _SCENARIOS_DIR / f'{slug}.json'


def list_scenario_slugs() -> List[str]:
    """Return slugs for all JSON scenarios on disk."""
    if not _SCENARIOS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _SCENARIOS_DIR.glob('*.json'))


@lru_cache(maxsize=32)
def load_scenario(slug: str) -> Dict[str, Any]:
    path = get_scenario_path(slug)
    with path.open(encoding='utf-8') as fh:
        data = json.load(fh)
    if 'turns' not in data or not data['turns']:
        raise ValueError(f'Scenario {slug!r} has no turns')
    validate_scenario(data, slug=slug)
    return data


def scenario_turn(scenario: Dict[str, Any], turn_index: int) -> Optional[Dict[str, Any]]:
    turns: List[Dict[str, Any]] = scenario.get('turns', [])
    if turn_index < 0 or turn_index >= len(turns):
        return None
    return turns[turn_index]


def choice_by_id(turn: Dict[str, Any], choice_id: str) -> Optional[Dict[str, Any]]:
    for choice in turn.get('choices', []):
        if choice.get('id') == choice_id:
            return choice
    return None


def turn_context_for_player(
    turn: Dict[str, Any],
    choice_log: List[Dict[str, Any]],
) -> str:
    """Build prompt + memory callback lines."""
    parts = [turn.get('prompt', '')]
    context = turn.get('context')
    if context:
        parts.append(context)

    chosen_ids = {entry.get('choice_id') for entry in choice_log}
    for callback in turn.get('memory_callbacks', []):
        required = callback.get('requires_choice')
        if required and required in chosen_ids:
            line = callback.get('text')
            if line:
                parts.append(line)
    return ' '.join(p.strip() for p in parts if p and p.strip())
