"""Tests for the world-class additions: derived emblem, in-run pressure,
cohort comparison, challenge CTA, the player archive, and keyboard play."""

from datetime import datetime, time

import pytest

from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.engine.emblem import emblem_for_run, emblem_style
from app.game.engine.state import SocietyState
from app.game.services.archive_service import (
    completed_societies_for_visitor,
    count_completed_societies_for_visitor,
)
from app.game.services.cohort_service import cohort_comparison, cohort_share_line
from app.game.services.daily_service import scheduled_scenario_slug, utc_game_date
from app.lib.vote_identity import fingerprint_from_client_id
from app.models.game import GameRun, GameRunOutcome


def _make_completed_daily(
    db,
    *,
    scenario_slug,
    fingerprint,
    ta=50.0,
    pf=50.0,
    category='mixed_legacy',
    name='Testland',
    headline='A nation, governed.',
    when=None,
):
    started = when or datetime.combine(utc_game_date(), time(12, 0))
    run = GameRun(
        uuid=GameRun.generate_uuid(),
        scenario_slug=scenario_slug,
        mode='daily',
        user_id=None,
        session_fingerprint=fingerprint,
        society_name=name,
        emblem_seed=GameRun.generate_uuid(),
        state_json={},
        choice_log_json=[],
        delayed_queue_json=[],
        headline_log_json=[],
        turn_index=5,
        total_turns=5,
        status=GAME_RUN_STATUS_COMPLETED,
        started_at=started,
        completed_at=started,
    )
    db.session.add(run)
    db.session.flush()
    outcome = GameRunOutcome(
        run_id=run.id,
        headline=headline,
        governance_label='Pragmatic survivor',
        outcome_category=category,
        axis_trust_autonomy=ta,
        axis_prosperity_fairness=pf,
        stat_finals_json={'prosperity': 50, 'trust': 50, 'fairness': 50, 'stability': 50},
        trait_chips_json=['Steady', 'Balanced'],
    )
    db.session.add(outcome)
    db.session.commit()
    return run


# ---------- Pressure (in-run hidden-cost tell) ----------

@pytest.mark.parametrize(
    'debt,frag,expected',
    [
        (0, 0, 0),
        (44, 0, 0),
        (45, 0, 1),
        (30, 10, 1),   # 30 + 15 = 45
        (68, 0, 2),
        (50, 12, 2),   # 50 + 18 = 68
        (90, 0, 3),
        (60, 20, 3),   # 60 + 30 = 90
    ],
)
def test_pressure_level_bands(debt, frag, expected):
    state = SocietyState(debt_stress=debt, fragility=frag)
    assert state.pressure_level() == expected


# ---------- Emblem derived from run ----------

@pytest.mark.parametrize(
    'ta,pf,expected_shape',
    [
        (20, 20, 0),   # trust + prosperity
        (80, 20, 1),   # autonomy + prosperity
        (20, 80, 2),   # trust + fairness
        (80, 80, 3),   # autonomy + fairness
    ],
)
def test_emblem_shape_follows_axis_quadrant(app, db, ta, pf, expected_shape):
    with app.app_context():
        db.create_all()
        run = _make_completed_daily(
            db, scenario_slug='debt-inherited', fingerprint='e' * 64, ta=ta, pf=pf
        )
        emblem = emblem_for_run(run)
        assert emblem['shape'] == expected_shape
        assert emblem['accent'].startswith('hsl(')


def test_emblem_is_deterministic_for_same_run(app, db):
    with app.app_context():
        db.create_all()
        run = _make_completed_daily(
            db, scenario_slug='debt-inherited', fingerprint='f' * 64, ta=70, pf=40
        )
        assert emblem_for_run(run) == emblem_for_run(run)


def test_emblem_falls_back_to_seed_without_outcome():
    class _Stub:
        outcome = None
        emblem_seed = 'seed-123'
        uuid = 'uuid-123'

    derived = emblem_for_run(_Stub())
    assert derived == emblem_style('seed-123')
    assert derived['shape'] in (0, 1, 2, 3)


# ---------- Cohort comparison ----------

def test_cohort_below_threshold_is_not_ready(app, db):
    with app.app_context():
        db.create_all()
        run = _make_completed_daily(db, scenario_slug='housing-squeeze', fingerprint='a' * 64)
        _make_completed_daily(db, scenario_slug='housing-squeeze', fingerprint='b' * 64)
        result = cohort_comparison(run, min_n=5)
        assert result['ready'] is False
        assert result['sample_size'] == 2


def test_cohort_reports_axis_percentile_and_rarity(app, db):
    with app.app_context():
        db.create_all()
        # Current leader: strongly autonomy-led, rare ending.
        run = _make_completed_daily(
            db,
            scenario_slug='energy-price-shock',
            fingerprint='c' * 64,
            ta=80.0,
            pf=50.0,
            category='unexpected_utopia',
        )
        # Nine more middling, common-ending runs the same day.
        for i in range(9):
            _make_completed_daily(
                db,
                scenario_slug='energy-price-shock',
                fingerprint=f'd{i}' + 'd' * 60,
                ta=50.0,
                pf=50.0,
                category='mixed_legacy',
            )
        result = cohort_comparison(run, min_n=10)
        assert result['ready'] is True
        assert result['sample_size'] == 10
        assert result['axis']['direction'] == 'autonomy'
        assert result['axis']['more_than_percent'] == 90
        # Label is localised once in the service so the template/share line agree.
        assert result['axis']['label'] == 'Autonomy'
        assert result['rarity']['percent'] == 10

        line = cohort_share_line(result)
        assert line and '%' in line


def test_cohort_share_line_none_when_not_ready():
    assert cohort_share_line(None) is None
    assert cohort_share_line({'ready': False, 'sample_size': 1}) is None


# ---------- Archive ----------

def test_archive_returns_visitor_societies_newest_first(app, db):
    fp = fingerprint_from_client_id('g' * 64)
    other = fingerprint_from_client_id('h' * 64)
    with app.app_context():
        db.create_all()
        _make_completed_daily(
            db, scenario_slug='debt-inherited', fingerprint=fp, name='Older',
            when=datetime.combine(utc_game_date(), time(9, 0)),
        )
        _make_completed_daily(
            db, scenario_slug='housing-squeeze', fingerprint=fp, name='Newer',
            when=datetime.combine(utc_game_date(), time(18, 0)),
        )
        _make_completed_daily(db, scenario_slug='debt-inherited', fingerprint=other, name='Someone else')

        societies = completed_societies_for_visitor(user_id=None, session_fingerprint=fp)
        assert [s['society_name'] for s in societies] == ['Newer', 'Older']
        assert all('emblem' in s and s['emblem']['accent'].startswith('hsl(') for s in societies)
        assert 'Someone else' not in [s['society_name'] for s in societies]


def test_archive_empty_for_unknown_visitor(app, db):
    with app.app_context():
        db.create_all()
        assert completed_societies_for_visitor(user_id=None, session_fingerprint=None) == []


def test_archive_count_scoped_to_visitor(app, db):
    fp = fingerprint_from_client_id('n' * 64)
    other = fingerprint_from_client_id('m' * 64)
    with app.app_context():
        db.create_all()
        for i in range(3):
            _make_completed_daily(db, scenario_slug='debt-inherited', fingerprint=fp, name=f'Mine{i}')
        _make_completed_daily(db, scenario_slug='debt-inherited', fingerprint=other, name='Theirs')
        assert count_completed_societies_for_visitor(user_id=None, session_fingerprint=fp) == 3
        assert count_completed_societies_for_visitor(user_id=None, session_fingerprint=other) == 1
        assert count_completed_societies_for_visitor(user_id=None, session_fingerprint=None) == 0


def test_archive_offset_paginates_without_overlap(app, db):
    fp = fingerprint_from_client_id('p' * 64)
    with app.app_context():
        db.create_all()
        for i in range(5):
            _make_completed_daily(
                db, scenario_slug='debt-inherited', fingerprint=fp, name=f'Run{i}',
                when=datetime.combine(utc_game_date(), time(8 + i, 0)),
            )
        first = completed_societies_for_visitor(user_id=None, session_fingerprint=fp, limit=2, offset=0)
        second = completed_societies_for_visitor(user_id=None, session_fingerprint=fp, limit=2, offset=2)
        assert [s['society_name'] for s in first] == ['Run4', 'Run3']
        assert [s['society_name'] for s in second] == ['Run2', 'Run1']


# ---------- Routes ----------

def test_archive_route_empty_state(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'z' * 64)
    resp = client.get('/play/archive')
    assert resp.status_code == 200
    assert b'Your societies' in resp.data
    assert b"Play today's scenario" in resp.data


def test_archive_route_lists_societies(app, client, db):
    client_id = 'w' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        _make_completed_daily(
            db, scenario_slug='debt-inherited', fingerprint=fp,
            name='Aurelia', headline='You bought time. The future will collect.',
        )
    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get('/play/archive')
    assert resp.status_code == 200
    assert b'Aurelia' in resp.data
    assert b'The future will collect' in resp.data


def test_archive_route_pager_appears_when_more_pages(app, client, db):
    client_id = 'q' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        for i in range(26):  # one more than the 24-per-page cap
            _make_completed_daily(
                db, scenario_slug='debt-inherited', fingerprint=fp, name=f'Society{i}',
                when=datetime.combine(utc_game_date(), time(0, i)),
            )
    client.set_cookie('ss_voter_client_id', client_id)
    first = client.get('/play/archive')
    assert first.status_code == 200
    assert b'Older' in first.data  # next-page link present
    # Hero shows the true total, not just this page's slice (26, not 24).
    assert b'26 societies governed' in first.data
    assert b'Page 1 of 2' in first.data
    second = client.get('/play/archive?page=2')
    assert second.status_code == 200
    assert b'Newer' in second.data  # prev-page link present
    assert b'26 societies governed' in second.data
    assert b'Page 2 of 2' in second.data


def test_outcome_renders_cohort_and_challenge(app, client, db):
    client_id = 'k' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        run = _make_completed_daily(db, scenario_slug='debt-inherited', fingerprint=fp)
        run_uuid = run.uuid
    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    body = resp.data
    assert b'How you compare' in body
    assert b'Challenge a friend' in body
    assert b'reveal-step' in body
    # Single play is below the cohort threshold → honest "among the first" copy.
    assert b'among the first' in body


def test_outcome_renders_past_self_when_prior_run_exists(app, client, db):
    client_id = 'q' * 64
    fp = fingerprint_from_client_id(client_id)
    today = utc_game_date()
    with app.app_context():
        db.create_all()
        _make_completed_daily(
            db, scenario_slug='debt-inherited', fingerprint=fp, name='Yesterland',
            headline='You kept order. Freedom quietly eroded.',
            when=datetime.combine(today, time(8, 0)),
        )
        current = _make_completed_daily(
            db, scenario_slug='debt-inherited', fingerprint=fp, name='Todayland',
            headline='Against the odds, you held society together.',
            when=datetime.combine(today, time(18, 0)),
        )
        run_uuid = current.uuid
    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    body = resp.data
    assert b'You vs your past self' in body
    assert b'You kept order. Freedom quietly eroded.' in body


def test_past_self_not_leaked_to_non_owner_on_shared_link(app, client, db):
    owner_id = 'r' * 64
    owner_fp = fingerprint_from_client_id(owner_id)
    today = utc_game_date()
    with app.app_context():
        db.create_all()
        _make_completed_daily(
            db, scenario_slug='debt-inherited', fingerprint=owner_fp, name='Priorland',
            headline='You kept order. Freedom quietly eroded.',
            when=datetime.combine(today, time(8, 0)),
        )
        current = _make_completed_daily(
            db, scenario_slug='debt-inherited', fingerprint=owner_fp, name='Currentland',
            headline='Against the odds, you held society together.',
            when=datetime.combine(today, time(18, 0)),
        )
        run_uuid = current.uuid
    # A different visitor opens the public share link.
    client.set_cookie('ss_voter_client_id', 's' * 64)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    body = resp.data
    assert b'You vs your past self' not in body
    assert b'You kept order. Freedom quietly eroded.' not in body


def test_turn_screen_has_pressure_and_keyboard_affordances(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'p' * 64)
    resp = client.get('/play/run/housing-squeeze')
    assert resp.status_code == 200
    body = resp.data
    assert b'id="society-pressure"' in body
    assert b'data-pressure-labels' in body
    assert b'game-choice-num' in body
    assert b'aria-keyshortcuts' in body
    assert b'press 1' in body
