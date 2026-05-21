"""Scenario JSON validation for publish gate (plan §10.4, §10.7).

Editorial note (charter §10.5): neutrality means no partisan tribe labels and no
choice IDs that accuse the player — not bloodless copy. Reactions should name
real stakeholders and visible trade-offs (unions protest, investors flee, locals
cheer). Abstract-only consequences (central-bank charts, spreadsheet verbs) are
a publish smell unless paired with human-scale fallout.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.game.constants import STAT_ALL, STAT_VISIBLE

_REQUIRED_BEATS = ('hook', 'confidence', 'crack', 'oh_no', 'legacy')
_MIN_CHOICES_PER_TURN = 3

# Mirrors contradiction.py — a single choice can't be on both sides of these axes
# without breaking the player-pattern contradiction detector.
_OPPOSING_TAG_PAIRS = (
    ('welfare', 'austerity'),
    ('redistribute', 'austerity'),
    ('centralise', 'decentralise'),
    ('open', 'restrict'),
    ('borrow', 'austerity'),
    ('growth', 'environment'),
)


class ScenarioValidationError(ValueError):
    """Raised when scenario content fails editorial/engine checks."""


def validate_scenario(data: Dict[str, Any], *, slug: str | None = None) -> None:
    """Validate a scenario dict. Raises ScenarioValidationError on failure."""
    errors: List[str] = []

    file_slug = slug or data.get('slug')
    if not file_slug:
        errors.append('missing slug')
    elif data.get('slug') and data['slug'] != file_slug:
        errors.append(f'slug mismatch: file {file_slug!r} vs json {data.get("slug")!r}')

    turns = data.get('turns')
    has_any_delayed = False
    if not turns or not isinstance(turns, list):
        errors.append('turns must be a non-empty list')
    elif len(turns) != 5:
        errors.append(f'expected 5 turns, got {len(turns)}')
    else:
        seen_ids: set[str] = set()
        for idx, turn in enumerate(turns):
            prefix = f'turns[{idx}]'
            beat = turn.get('beat')
            if beat != _REQUIRED_BEATS[idx]:
                errors.append(f'{prefix} beat must be {_REQUIRED_BEATS[idx]!r}, got {beat!r}')
            if not (turn.get('prompt') or '').strip():
                errors.append(f'{prefix} missing prompt')
            choices = turn.get('choices') or []
            if len(choices) < _MIN_CHOICES_PER_TURN:
                errors.append(f'{prefix} needs at least {_MIN_CHOICES_PER_TURN} choices')
            if idx == 3:
                callbacks = turn.get('memory_callbacks') or []
                if not callbacks:
                    errors.append(f'{prefix} (oh_no) requires memory_callbacks')
                elif len(callbacks) < 3:
                    errors.append(
                        f'{prefix} (oh_no) needs at least 3 memory_callbacks, got {len(callbacks)}'
                    )

            # Plan §10.4 — "all choices viable". A turn where every choice shows only
            # down-arrows to the player (no visible upside anywhere) reads as picked-on.
            if choices and not any(
                _choice_has_visible_upside((c.get('effects') or {}).get('immediate') or {})
                for c in choices
            ):
                errors.append(f'{prefix} has no visible upside on any choice')

            for cidx, choice in enumerate(choices):
                cp = f'{prefix}.choices[{cidx}]'
                cid = choice.get('id')
                if not cid:
                    errors.append(f'{cp} missing id')
                elif cid in seen_ids:
                    errors.append(f'duplicate choice id {cid!r}')
                else:
                    seen_ids.add(cid)
                if not (choice.get('label') or '').strip():
                    errors.append(f'{cp} missing label')

                tag_set = set(choice.get('tags') or [])
                for a, b in _OPPOSING_TAG_PAIRS:
                    if a in tag_set and b in tag_set:
                        errors.append(
                            f'{cp} has contradictory tags {a!r} and {b!r}'
                        )
                effects = choice.get('effects') or {}
                immediate = effects.get('immediate') or {}
                if not immediate:
                    errors.append(f'{cp} missing effects.immediate')
                elif not _choice_has_effect(immediate):
                    errors.append(f'{cp} must change at least one stat')
                elif not _choice_has_upside(immediate):
                    errors.append(f'{cp} must improve at least one stat (plan §2.1)')

                delayed = effects.get('delayed')
                if delayed:
                    has_any_delayed = True
                    specs = delayed if isinstance(delayed, list) else [delayed]
                    for spec in specs:
                        offset = int(spec.get('turn_offset', 0))
                        if offset < 1:
                            errors.append(f'{cp} delayed turn_offset must be >= 1')

    # Plan §4.6 / §2.3 — every scenario needs at least one delayed consequence
    # for the "oh no…" ironic reversal to land.
    if turns and not has_any_delayed:
        errors.append('scenario must contain at least one delayed effect (plan §4.6)')

    initial = data.get('initial_state') or {}
    for key in ('prosperity', 'trust', 'fairness', 'stability'):
        if key not in initial:
            errors.append(f'initial_state missing {key}')

    if errors:
        raise ScenarioValidationError('; '.join(errors))


def _choice_has_effect(immediate: Dict[str, Any]) -> bool:
    return any(
        key in STAT_ALL and int(immediate.get(key) or 0) != 0
        for key in immediate
    )


def _choice_has_upside(immediate: Dict[str, Any]) -> bool:
    """At least one stat moves in a direction that can read as a benefit."""
    for key, delta in immediate.items():
        if key not in STAT_ALL:
            continue
        d = int(delta)
        if d == 0:
            continue
        if key in ('debt_stress', 'fragility') and d < 0:
            return True
        if key not in ('debt_stress', 'fragility') and d > 0:
            return True
    return False


def _choice_has_visible_upside(immediate: Dict[str, Any]) -> bool:
    """At least one *visible* stat goes up — the arrows the player actually sees."""
    return any(int(immediate.get(k) or 0) > 0 for k in STAT_VISIBLE)
