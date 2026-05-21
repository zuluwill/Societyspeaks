"""Tests for Society Play engine and vertical slice."""

import json

import pytest

from app.game.engine.archetype import (
    _outcome_category,
    build_outcome,
    prosperity_fairness_axis,
    trust_autonomy_axis,
)
from app.game.engine.contradiction import detect_contradiction
from app.game.engine.effects import apply_choice, process_turn_start
from app.game.engine.scenario import load_scenario
from app.game.engine.state import SocietyState
from app.game.services.run_service import apply_run_choice, get_or_start_slice_run
from app.models.game import GameRun


@pytest.fixture
def debt_scenario():
    return load_scenario('debt-inherited')


# ---------- Engine ----------

def test_load_debt_scenario_has_five_turns(debt_scenario):
    assert len(debt_scenario['turns']) == 5
    assert debt_scenario['slug'] == 'debt-inherited'


def test_apply_choice_updates_stats(debt_scenario):
    state = SocietyState.from_dict(debt_scenario['initial_state'])
    choice = debt_scenario['turns'][0]['choices'][0]
    queue: list = []
    result = apply_choice(state, choice, 0, 5, queue)
    assert result['headline']
    assert state.trust > 48
    assert state.debt_stress > 62


def test_apply_choice_schedules_delayed_within_total_turns(debt_scenario):
    state = SocietyState.from_dict(debt_scenario['initial_state'])
    choice = debt_scenario['turns'][0]['choices'][0]  # borrow_hospitals — turn_offset 3
    queue: list = []
    apply_choice(state, choice, 0, 5, queue)
    assert len(queue) == 1
    assert queue[0]['fires_on_turn'] == 3


def test_process_turn_start_fires_overdue_events():
    queue = [
        {'fires_on_turn': 2, 'effects': {'trust': -3}, 'headline': 'overdue'},
        {'fires_on_turn': 5, 'effects': {'trust': -1}, 'headline': 'future'},
    ]
    remaining, fired = process_turn_start(queue, 3)
    assert len(fired) == 1
    assert fired[0]['headline'] == 'overdue'
    assert len(remaining) == 1
    assert remaining[0]['fires_on_turn'] == 5


# ---------- Axes ----------

def test_trust_autonomy_axis_centred_when_equal():
    state = SocietyState(trust=50, autonomy=50)
    assert trust_autonomy_axis(state) == 50.0


def test_trust_autonomy_axis_skews_toward_autonomy_when_higher():
    state = SocietyState(trust=20, autonomy=80)
    assert trust_autonomy_axis(state) == 80.0


def test_prosperity_fairness_axis_skews_toward_prosperity():
    state = SocietyState(prosperity=80, fairness=20)
    assert prosperity_fairness_axis(state) == 20.0


def test_build_outcome_stores_axis_floats(debt_scenario):
    state = SocietyState(prosperity=60, trust=70, fairness=40, stability=50, debt_stress=70, autonomy=30)
    out = build_outcome(state, [{'tags': ['welfare'], 'turn_index': 0}], debt_scenario)
    assert isinstance(out['axis_trust_autonomy'], float)
    assert isinstance(out['axis_prosperity_fairness'], float)
    assert 0 <= out['axis_trust_autonomy'] <= 100
    assert 0 <= out['axis_prosperity_fairness'] <= 100


@pytest.mark.parametrize(
    'stats,category',
    [
        ({'stability': 15, 'trust': 30, 'prosperity': 28}, 'spectacular_collapse'),
        ({'stability': 65, 'autonomy': 28, 'fairness': 40, 'trust': 40}, 'accidental_dystopia'),
        ({'debt_stress': 88, 'trust': 60, 'prosperity': 50}, 'ironic_success'),
        ({'future': 68, 'prosperity': 32, 'trust': 45}, 'ironic_failure'),
        ({'debt_stress': 88, 'trust': 40, 'stability': 35}, 'collapse'),
        ({'trust': 78, 'fairness': 65, 'stability': 50}, 'unexpected_utopia'),
        ({'trust': 50, 'fairness': 50, 'prosperity': 50, 'stability': 50}, 'mixed_legacy'),
    ],
)
def test_outcome_category_routing(stats, category):
    state = SocietyState(**stats)
    assert _outcome_category(state) == category


def test_trait_chips_picks_strongest_deviations():
    """The three chips should reflect the run's most distinctive signals."""
    state = SocietyState(
        prosperity=85, trust=20, fairness=70, stability=50, autonomy=55, future=50, debt_stress=35
    )
    out = build_outcome(state, [], {})
    chips = out['trait_chips']
    assert len(chips) <= 3
    # prosperity 85 (Δ35) and trust 20 (Δ30) are the strongest deviations and must surface.
    assert 'Growing' in chips
    assert 'Low-trust' in chips


def test_trait_chips_fall_back_when_mid_range():
    """A society that's mid on every axis still gets a chip — never empty."""
    state = SocietyState(
        prosperity=50, trust=50, fairness=50, stability=50, autonomy=50, future=50, debt_stress=50
    )
    out = build_outcome(state, [], {})
    assert out['trait_chips']  # never empty


# ---------- Contradiction guard ----------

def test_contradiction_fires_on_repeated_reversal():
    """≥2 evidence on each side: should flag."""
    log = [
        {'tags': ['welfare'], 'turn_index': 0},
        {'tags': ['welfare'], 'turn_index': 1},
        {'tags': ['austerity'], 'turn_index': 2},
        {'tags': ['austerity'], 'turn_index': 3},
    ]
    c = detect_contradiction(log)
    assert c is not None
    assert c['headline'] == 'Under pressure'


def test_contradiction_does_not_fire_on_single_instance():
    """One welfare → one austerity is two different problems, not a reversal."""
    log = [
        {'tags': ['welfare'], 'turn_index': 0},
        {'tags': ['growth'], 'turn_index': 1},
        {'tags': ['austerity'], 'turn_index': 2},
        {'tags': ['stability'], 'turn_index': 3},
    ]
    c = detect_contradiction(log)
    assert c is None


def test_contradiction_requires_minimum_log_length():
    log = [
        {'tags': ['welfare'], 'turn_index': 0},
        {'tags': ['austerity'], 'turn_index': 1},
    ]
    assert detect_contradiction(log) is None


def test_contradiction_summary_uses_final_turn_number():
    log = [
        {'tags': ['welfare'], 'turn_index': 0},
        {'tags': ['welfare'], 'turn_index': 1},
        {'tags': ['austerity'], 'turn_index': 2},
        {'tags': ['austerity'], 'turn_index': 3},
    ]
    c = detect_contradiction(log)
    assert 'Turn 4' in c['summary']


# ---------- Full lifecycle ----------

def test_full_run_lifecycle(app, db):
    from app.lib.vote_identity import fingerprint_from_client_id

    fp = fingerprint_from_client_id('c' * 64)
    with app.app_context():
        db.create_all()
        run = get_or_start_slice_run(user_id=None, session_fingerprint=fp)
        assert run.turn_index == 0
        scenario = load_scenario(run.scenario_slug)
        for turn in scenario['turns']:
            choice_id = turn['choices'][0]['id']
            result = apply_run_choice(run, choice_id)
            run = db.session.get(GameRun, run.id)
            if result['game_complete']:
                break
        assert run.status == 'completed'
        assert run.outcome is not None
        assert run.outcome.headline
        assert run.outcome.axis_trust_autonomy is not None
        assert run.outcome.axis_prosperity_fairness is not None


def test_daily_page_loads(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'd' * 64)
    resp = client.get('/play/daily')
    assert resp.status_code == 200
    assert b'game-app' in resp.data
    assert b'game-choice' in resp.data


def test_choose_api_returns_next_turn_payload(app, client, db):
    from app.lib.vote_identity import fingerprint_from_client_id

    client_id = 'e' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        from app.game.services.run_service import get_or_start_daily_run

        run = get_or_start_daily_run(
            scenario_slug='debt-inherited',
            user_id=None,
            session_fingerprint=fp,
        )
        run_uuid = run.uuid

    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.post(
        f'/play/api/run/{run_uuid}/choose',
        data=json.dumps({'choice_id': 'borrow_hospitals'}),
        content_type='application/json',
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['consequence']['headline']
    assert data['turn_index'] == 1
    assert data['next_turn'] is not None
    assert data['next_turn']['turn_index'] == 1
    assert data['next_turn']['prompt']
    assert len(data['next_turn']['choices']) >= 2
    assert data['game_complete'] is False


def test_choose_api_rejects_wrong_fingerprint(app, client, db):
    from app.lib.vote_identity import fingerprint_from_client_id

    owner_client = 'f' * 64
    owner_fp = fingerprint_from_client_id(owner_client)
    with app.app_context():
        db.create_all()
        run = get_or_start_slice_run(user_id=None, session_fingerprint=owner_fp)
        run_uuid = run.uuid

    attacker_client = '9' * 64
    client.set_cookie('ss_voter_client_id', attacker_client)
    resp = client.post(
        f'/play/api/run/{run_uuid}/choose',
        data=json.dumps({'choice_id': 'borrow_hospitals'}),
        content_type='application/json',
    )
    assert resp.status_code == 403


def test_choose_api_rejects_logged_in_user_on_foreign_fingerprint_run(app, client, db):
    """Logged-in users must not advance another visitor's anonymous run by UUID."""
    from app.lib.vote_identity import fingerprint_from_client_id
    from app.models import User

    owner_client = 'a' * 64
    owner_fp = fingerprint_from_client_id(owner_client)
    with app.app_context():
        db.create_all()
        user = User(email='attacker@example.com', username='attacker')
        user.set_password('test-password-123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        run = get_or_start_slice_run(user_id=None, session_fingerprint=owner_fp)
        run_uuid = run.uuid

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True
    client.set_cookie('ss_voter_client_id', 'b' * 64)
    resp = client.post(
        f'/play/api/run/{run_uuid}/choose',
        data=json.dumps({'choice_id': 'borrow_hospitals'}),
        content_type='application/json',
    )
    assert resp.status_code == 403


def _play_to_completion(app, db, client_id):
    from app.lib.vote_identity import fingerprint_from_client_id

    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        run = get_or_start_slice_run(user_id=None, session_fingerprint=fp)
        scenario = load_scenario(run.scenario_slug)
        for turn in scenario['turns']:
            result = apply_run_choice(run, turn['choices'][0]['id'])
            run = db.session.get(GameRun, run.id)
            if result['game_complete']:
                break
        return run.uuid


def test_outcome_og_svg_renders(app, client, db):
    run_uuid = _play_to_completion(app, db, '7' * 64)
    resp = client.get(f'/play/outcome/{run_uuid}/og.svg')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'].startswith('image/svg+xml')
    body = resp.data.decode('utf-8')
    assert '<svg' in body
    assert 'TRADEOFFS' in body


def test_outcome_og_png_serves_png_or_redirects_to_svg(app, client, db):
    """In environments with Pillow: PNG. Without: redirect to SVG. Either is valid."""
    from app.game.services import og_image_service

    run_uuid = _play_to_completion(app, db, '8' * 64)
    resp = client.get(f'/play/outcome/{run_uuid}/og.png')

    if og_image_service.is_available():
        assert resp.status_code == 200
        assert resp.headers['Content-Type'] == 'image/png'
        assert resp.headers['Cache-Control'].startswith('public')
        # PNG magic number
        assert resp.data[:8] == b'\x89PNG\r\n\x1a\n'
        assert len(resp.data) > 2_000  # sanity — a real card is >> a few bytes
    else:
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/og.svg')


def test_outcome_og_png_redirects_to_svg_when_pillow_missing(app, client, db, monkeypatch):
    """Force the no-Pillow code path even on hosts where Pillow loads."""
    from app.game.services import og_image_service

    monkeypatch.setattr(og_image_service, 'is_available', lambda: False)
    run_uuid = _play_to_completion(app, db, '4' * 64)
    resp = client.get(f'/play/outcome/{run_uuid}/og.png')
    assert resp.status_code == 302
    assert '/og.svg' in resp.headers['Location']


def test_outcome_og_png_404_for_incomplete_run(app, client, db):
    """The card only exists once the run is complete."""
    from app.lib.vote_identity import fingerprint_from_client_id

    fp = fingerprint_from_client_id('3' * 64)
    with app.app_context():
        db.create_all()
        run = get_or_start_slice_run(user_id=None, session_fingerprint=fp)
        run_uuid = run.uuid  # still in-progress
    resp = client.get(f'/play/outcome/{run_uuid}/og.png')
    assert resp.status_code == 404


def test_outcome_og_meta_points_to_png(app, client, db):
    """The outcome HTML's og:image must point at the PNG endpoint, not SVG."""
    run_uuid = _play_to_completion(app, db, '2' * 64)
    client.set_cookie('ss_voter_client_id', '2' * 64)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert f'/og.png' in body
    assert 'og:image:alt' in body
    assert 'og:image:type' in body
    assert 'image/png' in body
