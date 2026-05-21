"""Validate all launch daily scenarios meet editorial and engine contracts."""

import pytest

from app.game.engine.scenario import load_scenario
from app.game.engine.validation import ScenarioValidationError, validate_scenario
from app.game.services.daily_service import LAUNCH_SCENARIO_ROTATION


@pytest.mark.parametrize(
    'entry',
    LAUNCH_SCENARIO_ROTATION,
    ids=lambda e: e['slug'],
)
def test_launch_scenario_loads_and_validates(entry):
    slug = entry['slug']
    data = load_scenario(slug)
    validate_scenario(data, slug=slug)
    assert data['locale'] == 'global'
    assert len(data['turns']) == 5
    assert data['turns'][0]['beat'] == 'hook'
    assert data['turns'][3]['beat'] == 'oh_no'
    assert data['turns'][4]['beat'] == 'legacy'


def test_launch_rotation_has_fourteen_scenarios():
    assert len(LAUNCH_SCENARIO_ROTATION) == 14
    slugs = [e['slug'] for e in LAUNCH_SCENARIO_ROTATION]
    assert len(slugs) == len(set(slugs))


def test_all_rotation_slugs_exist_on_disk():
    from app.game.engine.scenario import list_scenario_slugs

    available = set(list_scenario_slugs())
    for entry in LAUNCH_SCENARIO_ROTATION:
        assert entry['slug'] in available, f"missing scenario file for {entry['slug']}"


def test_each_scenario_runs_to_completion():
    from app.game.services.run_service import apply_run_choice

    for entry in LAUNCH_SCENARIO_ROTATION:
        slug = entry['slug']
        scenario = load_scenario(slug)
        state_data = scenario['initial_state']
        from app.game.engine.state import SocietyState

        state = SocietyState.from_dict(state_data)
        queue: list = []
        for tidx, turn in enumerate(scenario['turns']):
            choice = turn['choices'][0]
            from app.game.engine.effects import apply_choice

            apply_choice(state, choice, tidx, len(scenario['turns']), queue)
        assert state.to_dict()


def test_validator_rejects_scenario_with_no_delayed_effects():
    """Plan §4.6 — every scenario needs at least one delayed consequence."""
    bad = {
        'slug': 'bad', 'locale': 'global', 'mode': 'daily',
        'initial_state': {'prosperity': 50, 'trust': 50, 'fairness': 50, 'stability': 50},
        'turns': [
            {
                'id': f't{i}', 'beat': beat, 'prompt': 'p',
                'choices': [
                    {'id': f'c{i}{j}', 'label': 'l', 'effects': {'immediate': {'trust': 5, 'prosperity': -2}}}
                    for j in range(3)
                ],
                **({'memory_callbacks': [
                    {'requires_choice': 'c00', 'text': 'mc1'},
                    {'requires_choice': 'c01', 'text': 'mc2'},
                    {'requires_choice': 'c02', 'text': 'mc3'},
                ]} if beat == 'oh_no' else {}),
            }
            for i, beat in enumerate(['hook', 'confidence', 'crack', 'oh_no', 'legacy'])
        ],
    }
    with pytest.raises(ScenarioValidationError, match='delayed'):
        validate_scenario(bad, slug='bad')


def test_validator_rejects_choice_with_contradictory_tags():
    """A single choice can't sit on both sides of an opposing axis —
    the contradiction engine would flag the player as reversing themselves
    within a single click."""
    bad = {
        'slug': 'bad', 'locale': 'global', 'mode': 'daily',
        'initial_state': {'prosperity': 50, 'trust': 50, 'fairness': 50, 'stability': 50},
        'turns': [
            {
                'id': f't{i}', 'beat': beat, 'prompt': 'p',
                'choices': [
                    {
                        'id': f'c{i}{j}',
                        'label': 'l',
                        'tags': ['welfare', 'austerity'] if (i == 0 and j == 0) else [],
                        'effects': {
                            'immediate': {'trust': 5, 'prosperity': -2},
                            **(
                                {'delayed': {'turn_offset': 1, 'effects': {'trust': -1}}}
                                if (i == 0 and j == 0) else {}
                            ),
                        },
                    }
                    for j in range(3)
                ],
                **(
                    {'memory_callbacks': [
                        {'requires_choice': 'c00', 'text': 'mc1'},
                        {'requires_choice': 'c01', 'text': 'mc2'},
                        {'requires_choice': 'c02', 'text': 'mc3'},
                    ]}
                    if beat == 'oh_no' else {}
                ),
            }
            for i, beat in enumerate(['hook', 'confidence', 'crack', 'oh_no', 'legacy'])
        ],
    }
    with pytest.raises(ScenarioValidationError, match='contradictory tags'):
        validate_scenario(bad, slug='bad')


def test_validator_rejects_turn_with_no_visible_upside():
    """Plan §10.4 — no turn should show only down-arrows."""
    bad = {
        'slug': 'bad', 'locale': 'global', 'mode': 'daily',
        'initial_state': {'prosperity': 50, 'trust': 50, 'fairness': 50, 'stability': 50},
        'turns': [
            {
                'id': f't{i}', 'beat': beat, 'prompt': 'p',
                'choices': [
                    # Every choice in this scenario is visible-down only
                    # (hidden upside via debt_stress drop satisfies the per-choice rule
                    # but the per-turn check should still catch this).
                    {'id': f'c{i}{j}', 'label': 'l', 'effects': {'immediate': {'trust': -2, 'debt_stress': -5}}}
                    for j in range(3)
                ],
                **(
                    {'memory_callbacks': [
                        {'requires_choice': 'c00', 'text': 'mc1'},
                        {'requires_choice': 'c01', 'text': 'mc2'},
                        {'requires_choice': 'c02', 'text': 'mc3'},
                    ]}
                    if beat == 'oh_no' else {}
                ),
                **(
                    {} if i > 0 else {}
                ),
            }
            for i, beat in enumerate(['hook', 'confidence', 'crack', 'oh_no', 'legacy'])
        ],
    }
    # Add a delayed effect to one choice so the §4.6 check passes and we isolate
    # the per-turn upside rule.
    bad['turns'][0]['choices'][0]['effects']['delayed'] = {
        'turn_offset': 1,
        'effects': {'trust': -1},
    }
    with pytest.raises(ScenarioValidationError, match='no visible upside'):
        validate_scenario(bad, slug='bad')


def test_validator_requires_three_memory_callbacks():
    bad = {
        'slug': 'bad', 'locale': 'global', 'mode': 'daily',
        'initial_state': {'prosperity': 50, 'trust': 50, 'fairness': 50, 'stability': 50},
        'turns': [
            {
                'id': f't{i}', 'beat': beat, 'prompt': 'p',
                'choices': [
                    {
                        'id': f'c{i}{j}', 'label': 'l',
                        'effects': {
                            'immediate': {'trust': 5, 'prosperity': 2},
                            **({'delayed': {'turn_offset': 1, 'effects': {'trust': -1}}} if i == 0 and j == 0 else {}),
                        },
                    }
                    for j in range(3)
                ],
                **(
                    {'memory_callbacks': [
                        {'requires_choice': 'c30', 'text': 'one'},
                        {'requires_choice': 'c31', 'text': 'two'},
                    ]}
                    if beat == 'oh_no' else {}
                ),
            }
            for i, beat in enumerate(['hook', 'confidence', 'crack', 'oh_no', 'legacy'])
        ],
    }
    with pytest.raises(ScenarioValidationError, match='3 memory_callbacks'):
        validate_scenario(bad, slug='bad')


def test_launch_scenarios_have_three_memory_callbacks():
    for entry in LAUNCH_SCENARIO_ROTATION:
        data = load_scenario(entry['slug'])
        callbacks = data['turns'][3].get('memory_callbacks') or []
        assert len(callbacks) >= 3, entry['slug']
