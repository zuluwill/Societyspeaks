"""Tests for the content-depth layer: seeded opening variation and
'beat your past self'. These keep a fixed scenario library feeling fresh
without breaking the shared-daily property."""

from datetime import date, datetime, time, timedelta

from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.engine.variant import (
    apply_initial_variation,
    daily_variant_seed,
    random_variant_seed,
    variation_descriptor,
)
from app.game.services.daily_service import scheduled_scenario_slug, utc_game_date
from app.game.services.past_self_service import previous_outcome_for_scenario
from app.game.services.run_service import (
    get_or_start_daily_run,
    run_situation,
    start_quick_run,
)
from app.lib.vote_identity import fingerprint_from_client_id
from app.models.game import GameRun, GameRunOutcome

_BASE = {
    'prosperity': 55,
    'trust': 52,
    'fairness': 50,
    'stability': 54,
    'future': 48,
    'debt_stress': 40,
    'autonomy': 60,
    'fragility': 8,
}


# ---------- Variation engine (pure) ----------

def test_variation_is_deterministic_for_same_seed():
    a = apply_initial_variation(_BASE, 12345)
    b = apply_initial_variation(_BASE, 12345)
    assert a == b


def test_variation_differs_across_seeds():
    a = apply_initial_variation(_BASE, 1)
    b = apply_initial_variation(_BASE, 2)
    assert a != b


def test_variation_none_seed_returns_baseline():
    assert apply_initial_variation(_BASE, None) == _BASE


def test_variation_stays_in_band_and_clamped():
    for seed in range(50):
        out = apply_initial_variation(_BASE, seed)
        for key, value in out.items():
            assert 0 <= value <= 100
            assert abs(value - _BASE[key]) <= 10  # hidden band is the widest


def test_daily_seed_stable_per_day_and_varies_by_day():
    today = date(2026, 6, 1)
    assert daily_variant_seed('pandemic-outbreak', today) == daily_variant_seed(
        'pandemic-outbreak', today
    )
    assert daily_variant_seed('pandemic-outbreak', today) != daily_variant_seed(
        'pandemic-outbreak', today + timedelta(days=1)
    )
    # Different scenarios on the same day vary independently.
    assert daily_variant_seed('pandemic-outbreak', today) != daily_variant_seed(
        'crime-and-justice', today
    )


def test_random_seed_in_range():
    for _ in range(20):
        assert 0 <= random_variant_seed() <= 0xFFFFFFFF


def test_descriptor_none_when_identical():
    assert variation_descriptor(_BASE, dict(_BASE)) is None


def test_descriptor_picks_largest_drift():
    varied = dict(_BASE)
    varied['debt_stress'] = _BASE['debt_stress'] + 10
    desc = variation_descriptor(_BASE, varied)
    assert desc is not None
    assert desc['stat'] == 'debt_stress'
    assert desc['direction'] == 'high'
    assert desc['line']


# ---------- Variation wired into run creation ----------

def test_daily_run_opening_is_shared_across_players(app, db):
    """Two players on the same day get the same opening — shared-daily holds."""
    with app.app_context():
        db.create_all()
        slug = scheduled_scenario_slug()
        run_a = get_or_start_daily_run(
            scenario_slug=slug, user_id=None,
            session_fingerprint=fingerprint_from_client_id('a' * 64),
        )
        run_b = get_or_start_daily_run(
            scenario_slug=slug, user_id=None,
            session_fingerprint=fingerprint_from_client_id('b' * 64),
        )
        assert run_a.variant_seed is not None
        assert run_a.variant_seed == run_b.variant_seed
        assert run_a.state_json == run_b.state_json


def test_backdated_daily_seeds_by_schedule_date_not_today(app, db):
    """Streak-grace / challenge replays of a past day must inherit that day's
    opening, not today's — otherwise the shared-daily guarantee breaks."""
    with app.app_context():
        db.create_all()
        slug = scheduled_scenario_slug()
        play_date = utc_game_date() - timedelta(days=1)
        run = get_or_start_daily_run(
            scenario_slug=slug, user_id=None,
            session_fingerprint=fingerprint_from_client_id('y' * 64),
            seed_date=play_date,
        )
        assert run.variant_seed == daily_variant_seed(slug, play_date)
        assert run.variant_seed != daily_variant_seed(slug, utc_game_date())


def test_quick_runs_get_independent_seeds(app, db):
    with app.app_context():
        db.create_all()
        slug = scheduled_scenario_slug()
        fp = fingerprint_from_client_id('c' * 64)
        a = start_quick_run(scenario_slug=slug, user_id=None, session_fingerprint=fp)
        b = start_quick_run(scenario_slug=slug, user_id=None, session_fingerprint=fp)
        # Independent seeds; astronomically unlikely to collide.
        assert a.variant_seed is not None and b.variant_seed is not None
        assert a.variant_seed != b.variant_seed


def test_variation_can_be_disabled(app, db):
    with app.app_context():
        db.create_all()
        app.config['GAME_SCENARIO_VARIATION_ENABLED'] = False
        try:
            slug = scheduled_scenario_slug()
            run = get_or_start_daily_run(
                scenario_slug=slug, user_id=None,
                session_fingerprint=fingerprint_from_client_id('d' * 64),
            )
            assert run.variant_seed is None
            assert run_situation(run) is None
        finally:
            app.config['GAME_SCENARIO_VARIATION_ENABLED'] = True


# ---------- Beat your past self ----------

def _completed(db, *, slug, fingerprint, headline, when):
    run = GameRun(
        uuid=GameRun.generate_uuid(),
        scenario_slug=slug,
        mode='daily',
        user_id=None,
        session_fingerprint=fingerprint,
        society_name='Testland',
        emblem_seed=GameRun.generate_uuid(),
        state_json={},
        choice_log_json=[],
        delayed_queue_json=[],
        headline_log_json=[],
        turn_index=5,
        total_turns=5,
        status=GAME_RUN_STATUS_COMPLETED,
        started_at=when,
        completed_at=when,
    )
    db.session.add(run)
    db.session.flush()
    db.session.add(
        GameRunOutcome(
            run_id=run.id,
            headline=headline,
            governance_label='Pragmatic survivor',
            outcome_category='mixed_legacy',
            axis_trust_autonomy=50.0,
            axis_prosperity_fairness=50.0,
            stat_finals_json={},
            trait_chips_json=[],
        )
    )
    db.session.commit()
    return run


def test_past_self_none_on_first_encounter(app, db):
    fp = fingerprint_from_client_id('e' * 64)
    with app.app_context():
        db.create_all()
        run = _completed(
            db, slug='pandemic-outbreak', fingerprint=fp,
            headline='Only run', when=datetime.combine(utc_game_date(), time(12, 0)),
        )
        assert previous_outcome_for_scenario(run) is None


def test_past_self_returns_prior_and_flags_divergence(app, db):
    fp = fingerprint_from_client_id('f' * 64)
    today = utc_game_date()
    with app.app_context():
        db.create_all()
        _completed(
            db, slug='pandemic-outbreak', fingerprint=fp,
            headline='You kept order. Freedom quietly eroded.',
            when=datetime.combine(today - timedelta(days=14), time(12, 0)),
        )
        current = _completed(
            db, slug='pandemic-outbreak', fingerprint=fp,
            headline='Against the odds, you held society together.',
            when=datetime.combine(today, time(12, 0)),
        )
        prior = previous_outcome_for_scenario(current)
        assert prior is not None
        assert prior['headline'] == 'You kept order. Freedom quietly eroded.'
        assert prior['diverged'] is True


def test_past_self_scoped_to_same_scenario_and_visitor(app, db):
    fp = fingerprint_from_client_id('g' * 64)
    other = fingerprint_from_client_id('h' * 64)
    today = utc_game_date()
    with app.app_context():
        db.create_all()
        # Different scenario by same visitor — must not match.
        _completed(
            db, slug='crime-and-justice', fingerprint=fp, headline='Other scenario',
            when=datetime.combine(today - timedelta(days=2), time(12, 0)),
        )
        # Same scenario by a different visitor — must not match.
        _completed(
            db, slug='pandemic-outbreak', fingerprint=other, headline='Someone else',
            when=datetime.combine(today - timedelta(days=1), time(12, 0)),
        )
        current = _completed(
            db, slug='pandemic-outbreak', fingerprint=fp, headline='Mine, today',
            when=datetime.combine(today, time(12, 0)),
        )
        assert previous_outcome_for_scenario(current) is None
