"""Outcome headlines, axes, and trait chips."""

from __future__ import annotations

from typing import Any, Dict, List

from app.game.engine.state import SocietyState


def trust_autonomy_axis(state: SocietyState) -> float:
    """0 = fully Trust-led, 100 = fully Autonomy-led."""
    return ((state.autonomy - state.trust) + 100) / 2


def prosperity_fairness_axis(state: SocietyState) -> float:
    """0 = fully Prosperity-led, 100 = fully Fairness-led."""
    return ((state.fairness - state.prosperity) + 100) / 2


def build_outcome(
    state: SocietyState,
    choice_log: List[Dict[str, Any]],
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    stats = state.to_dict()
    category = _outcome_category(state)
    headline = _headline_for_category(category, state)
    governance_label = _governance_label(choice_log, state)
    traits = _trait_chips(state)

    axis_ta = trust_autonomy_axis(state)
    axis_pf = prosperity_fairness_axis(state)

    return {
        'headline': headline,
        'governance_label': governance_label,
        'outcome_category': category,
        'stat_finals': stats,
        'trait_chips': traits,
        'axis_trust_autonomy': axis_ta,
        'axis_prosperity_fairness': axis_pf,
    }


def _outcome_category(state: SocietyState) -> str:
    """Route final stats to shareable outcome categories (plan §2.3, §5.1)."""
    # Most specific bands first.
    if state.stability <= 20 and (state.trust <= 35 or state.prosperity <= 30):
        return 'spectacular_collapse'
    if state.debt_stress >= 92 and state.stability <= 30:
        return 'spectacular_collapse'

    if state.stability >= 62 and state.autonomy <= 32:
        return 'accidental_dystopia'
    if state.stability >= 58 and state.fairness <= 32 and state.trust <= 42:
        return 'accidental_dystopia'

    if state.debt_stress >= 85 and state.trust >= 55:
        return 'ironic_success'
    if state.prosperity >= 68 and state.fairness < 38:
        return 'ironic_success'
    if state.trust >= 68 and state.prosperity < 42:
        return 'ironic_success'
    if state.stability >= 58 and state.autonomy < 38:
        return 'ironic_success'

    if state.future >= 62 and state.prosperity <= 38:
        return 'ironic_failure'
    if state.fairness >= 62 and state.prosperity <= 38:
        return 'ironic_failure'
    if state.trust >= 58 and state.stability <= 38 and state.fragility >= 12:
        return 'ironic_failure'

    if state.debt_stress >= 85:
        return 'collapse'
    if state.stability <= 28:
        return 'collapse'

    if state.trust >= 72 and state.fairness >= 58 and state.stability >= 45:
        return 'unexpected_utopia'

    return 'mixed_legacy'


def _headline_for_category(category: str, state: SocietyState) -> str:
    if category == 'spectacular_collapse':
        if state.stability <= 15:
            return 'The streets filled before the spreadsheets did.'
        return 'Everything broke at once — trust, treasury, and order.'

    if category == 'accidental_dystopia':
        if state.autonomy <= 25:
            return 'You accidentally built a society that runs on quiet obedience.'
        return 'It works smoothly — as long as nobody asks questions.'

    if category == 'ironic_success':
        if state.trust >= 60 and state.debt_stress >= 80:
            return 'Everyone trusted you. The country ran out of money.'
        if state.prosperity >= 65 and state.fairness < 40:
            return 'You got the economy moving. Inequality exploded.'
        if state.stability >= 60 and state.autonomy < 35:
            return 'You kept order. Freedom quietly eroded.'
        return 'It worked — until the bills arrived.'

    if category == 'ironic_failure':
        if state.future >= 65 and state.prosperity <= 35:
            return 'Your environmental revolution caused blackouts.'
        if state.fairness >= 65 and state.prosperity <= 35:
            return 'Your fairness drive tanked the economy.'
        if state.trust >= 60 and state.stability <= 35:
            return 'Your reforms won applause — then lost the streets.'
        return 'You did the right things. The wrong things happened anyway.'

    if category == 'collapse':
        if state.debt_stress >= 90:
            return 'The debt finally caught up with you.'
        return 'Stability gave out before the plan did.'

    if category == 'unexpected_utopia':
        return 'Against the odds, you held society together.'

    if state.debt_stress >= 70 and state.trust >= 55:
        return 'You bought time. The future will collect.'
    if state.prosperity >= 55 and state.fairness >= 50:
        return 'Uneven, imperfect — but still standing.'
    return 'You governed through chaos and survived — barely.'


def _governance_label(choice_log: List[Dict[str, Any]], state: SocietyState) -> str:
    tags: List[str] = []
    for entry in choice_log:
        tags.extend(entry.get('tags') or [])
    if not tags:
        return 'Pragmatic survivor'

    from collections import Counter

    counts = Counter(tags)
    top = counts.most_common(1)
    primary = top[0][0] if top else ''

    mapping = {
        'borrow': 'Short-Term Fixer',
        'austerity': 'Austerity Realist',
        'welfare': 'Welfare Guardian',
        'redistribute': 'Fairness First',
        'centralise': 'Reluctant Centraliser',
        'decentralise': 'Devolution Believer',
        'growth': 'Growth Gambler',
        'environment': 'Long-Term Steward',
        'restrict': 'Borders-First Realist',
        'open': 'Open-Door Idealist',
        'future': 'Future-First Strategist',
    }
    if primary in mapping:
        return mapping[primary]
    if state.debt_stress >= 75:
        return 'Debt Juggler'
    if state.trust >= 70:
        return 'Trust Preserver'
    return 'Pragmatic survivor'


def _trait_chips(state: SocietyState) -> List[str]:
    """Up to three identity chips for the outcome card.

    Chips draw from eight societal dimensions. Stronger deviations from the
    midpoint win the three slots — so the chips reflect *what stands out*
    about your run, not a fixed default list.
    """
    candidates: List[tuple[float, str]] = []

    def add(value: int, midpoint: int, high_label: str, low_label: str) -> None:
        deviation = abs(value - midpoint)
        if deviation < 15:
            return
        candidates.append((deviation, high_label if value > midpoint else low_label))

    add(state.trust, 50, 'High-trust', 'Low-trust')
    add(state.fairness, 50, 'Equitable', 'Unequal')
    add(state.prosperity, 50, 'Growing', 'Stagnant')
    add(state.stability, 50, 'Cohesive', 'Volatile')
    add(state.autonomy, 50, 'Free-spirited', 'Tightly-held')
    add(state.future, 50, 'Long-sighted', 'Short-sighted')

    # Hidden stats invert: low debt_stress / fragility is the "good" direction.
    if state.debt_stress <= 30:
        candidates.append((50 - state.debt_stress, 'Fiscally stable'))
    elif state.debt_stress >= 70:
        candidates.append((state.debt_stress - 50, 'Debt-heavy'))

    if state.fragility >= 15:
        candidates.append((state.fragility, 'Fragile'))

    if not candidates:
        return ['Steady', 'Balanced']

    candidates.sort(reverse=True)
    return [label for _, label in candidates[:3]]
