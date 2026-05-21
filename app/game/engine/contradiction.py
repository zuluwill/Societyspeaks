"""Contradiction detection from choice tags.

Plan §5.4: signature "Under pressure" mechanic. Only flags real value reversals —
both sides need at least two pieces of evidence, and the contradicting tag must
appear meaningfully in the overall run, not as a single late accident.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional


_OPPOSING_TAG_PAIRS = [
    ('welfare', 'austerity'),
    ('redistribute', 'austerity'),
    ('centralise', 'decentralise'),
    ('open', 'restrict'),
    ('borrow', 'austerity'),
    ('growth', 'environment'),
]

_MIN_LOG_LENGTH = 4
_MIN_EVIDENCE_PER_SIDE = 2


def detect_contradiction(choice_log: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return contradiction summary if a real value reversal occurred."""
    if len(choice_log) < _MIN_LOG_LENGTH:
        return None

    half = len(choice_log) // 2
    early = choice_log[:half]
    late = choice_log[half:]

    early_tags: Counter = Counter()
    late_tags: Counter = Counter()
    all_tags: Counter = Counter()
    for entry in early:
        tags = entry.get('tags') or []
        early_tags.update(tags)
        all_tags.update(tags)
    for entry in late:
        tags = entry.get('tags') or []
        late_tags.update(tags)
        all_tags.update(tags)

    for a, b in _OPPOSING_TAG_PAIRS:
        if (
            early_tags[a] >= _MIN_EVIDENCE_PER_SIDE
            and late_tags[b] >= _MIN_EVIDENCE_PER_SIDE
            and all_tags[b] >= _MIN_EVIDENCE_PER_SIDE
        ):
            return _build_contradiction(a, b, choice_log)
        if (
            early_tags[b] >= _MIN_EVIDENCE_PER_SIDE
            and late_tags[a] >= _MIN_EVIDENCE_PER_SIDE
            and all_tags[a] >= _MIN_EVIDENCE_PER_SIDE
        ):
            return _build_contradiction(b, a, choice_log)

    return None


def _build_contradiction(
    started: str,
    ended: str,
    choice_log: List[Dict[str, Any]],
) -> Dict[str, Any]:
    started_label = _tag_label(started)
    ended_label = _tag_label(ended)
    final_turn = choice_log[-1].get('turn_index', len(choice_log) - 1) + 1
    summary = (
        f'You started by prioritising {started_label}. '
        f'By Turn {final_turn}, pressure pushed you toward {ended_label}.'
    )
    return {
        'started_tag': started,
        'ended_tag': ended,
        'summary': summary,
        'headline': 'Under pressure',
    }


def _tag_label(tag: str) -> str:
    labels = {
        'welfare': 'welfare and public services',
        'austerity': 'spending cuts',
        'redistribute': 'fairness and redistribution',
        'centralise': 'central authority',
        'decentralise': 'local autonomy',
        'borrow': 'borrowing for relief',
        'growth': 'economic growth',
        'environment': 'environmental protection',
        'open': 'openness',
        'restrict': 'restriction',
    }
    return labels.get(tag, tag.replace('_', ' '))
