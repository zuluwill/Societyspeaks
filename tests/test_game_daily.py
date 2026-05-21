"""Tests for Tradeoffs daily schedule and hub."""

from datetime import date, timedelta

import pytest

from app.game.engine.scenario import list_scenario_slugs, load_scenario
from app.game.services.daily_service import (
    LAUNCH_SCENARIO_ROTATION,
    daily_meta,
    ensure_schedule_buffer,
    scheduled_scenario_slug,
    tomorrow_teaser,
    utc_game_date,
)
from app.models.game import GameDailySchedule


def test_list_scenario_slugs_includes_launch_scenarios():
    slugs = list_scenario_slugs()
    assert 'debt-inherited' in slugs
    assert 'housing-squeeze' in slugs


def test_housing_scenario_has_five_turns():
    scenario = load_scenario('housing-squeeze')
    assert scenario['slug'] == 'housing-squeeze'
    assert len(scenario['turns']) == 5
    assert scenario['turns'][3]['beat'] == 'oh_no'
    assert scenario['turns'][3].get('memory_callbacks')


def test_scheduled_scenario_fallback_rotates(app, db):
    with app.app_context():
        db.create_all()
        day_a = date(2026, 1, 1)
        day_b = day_a + timedelta(days=1)
        slug_a = scheduled_scenario_slug(day_a)
        slug_b = scheduled_scenario_slug(day_b)
        assert slug_a in {e['slug'] for e in LAUNCH_SCENARIO_ROTATION}
        assert slug_b in {e['slug'] for e in LAUNCH_SCENARIO_ROTATION}
        assert slug_a != slug_b


def test_db_schedule_overrides_rotation(app, db):
    with app.app_context():
        db.create_all()
        day = date(2030, 6, 15)
        db.session.add(
            GameDailySchedule(
                schedule_date=day,
                scenario_slug='housing-squeeze',
                category_label='Housing',
            )
        )
        db.session.commit()
        assert scheduled_scenario_slug(day) == 'housing-squeeze'


def test_ensure_schedule_buffer_idempotent(app, db):
    with app.app_context():
        db.create_all()
        first = ensure_schedule_buffer(days=7)
        second = ensure_schedule_buffer(days=7)
        assert first == 7
        assert second == 0
        assert GameDailySchedule.query.count() == 7


def test_ensure_schedule_buffer_extends_when_short(app, db):
    """When the buffer's max date is short, seed only the missing tail."""
    with app.app_context():
        db.create_all()
        ensure_schedule_buffer(days=3)
        assert GameDailySchedule.query.count() == 3
        extended = ensure_schedule_buffer(days=7)
        assert extended == 4
        assert GameDailySchedule.query.count() == 7


def test_tomorrow_teaser_hides_title(app, db):
    with app.app_context():
        db.create_all()
        teaser = tomorrow_teaser()
        assert 'category' in teaser
        assert 'title' not in teaser


def test_daily_meta_includes_title(app, db):
    with app.app_context():
        db.create_all()
        meta = daily_meta()
        assert meta['title']
        assert meta['scenario_slug']
        assert meta['total_turns'] == 5


def test_hub_page_loads(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'a' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'Today' in resp.data or b'today' in resp.data.lower()
    assert b'Tradeoffs' in resp.data or b'debt' in resp.data.lower() or b'Housing' in resp.data


def test_daily_redirects_to_hub_for_future_date(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'b' * 64)
    future = (utc_game_date() + timedelta(days=5)).isoformat()
    resp = client.get(f'/play/daily/{future}')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/play/')


def test_daily_redirects_to_hub_for_ancient_date(app, client, db):
    """Plan §3.1: 48h grace, then ancient dates redirect to today."""
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'c' * 64)
    ancient = (utc_game_date() - timedelta(days=30)).isoformat()
    resp = client.get(f'/play/daily/{ancient}')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/play/')


def test_daily_allows_yesterday_grace_window(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'd' * 64)
    yesterday = (utc_game_date() - timedelta(days=1)).isoformat()
    resp = client.get(f'/play/daily/{yesterday}')
    assert resp.status_code == 200


def test_completed_today_redirects_to_outcome(app, client, db):
    """A user who already finished today's daily cannot start a fresh run on it."""
    from app.game.engine.scenario import load_scenario as _load
    from app.game.services.daily_service import scheduled_scenario_slug
    from app.game.services.run_service import apply_run_choice, get_or_start_daily_run
    from app.lib.vote_identity import fingerprint_from_client_id
    from app.models.game import GameRun

    client_id = '6' * 64
    fp = fingerprint_from_client_id(client_id)

    with app.app_context():
        db.create_all()
        slug = scheduled_scenario_slug()
        run = get_or_start_daily_run(
            scenario_slug=slug,
            user_id=None,
            session_fingerprint=fp,
        )
        scenario = _load(slug)
        for turn in scenario['turns']:
            choice_id = turn['choices'][0]['id']
            result = apply_run_choice(run, choice_id)
            run = db.session.get(GameRun, run.id)
            if result['game_complete']:
                break
        completed_uuid = run.uuid

    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get('/play/daily')
    assert resp.status_code == 302
    assert f'/play/outcome/{completed_uuid}' in resp.headers['Location']


def test_hub_shows_completed_today_cta(app, client, db):
    """Hub should surface 'View today's outcome' once the user has finished."""
    from app.game.engine.scenario import load_scenario as _load
    from app.game.services.daily_service import scheduled_scenario_slug
    from app.game.services.run_service import apply_run_choice, get_or_start_daily_run
    from app.lib.vote_identity import fingerprint_from_client_id
    from app.models.game import GameRun

    client_id = '5' * 64
    fp = fingerprint_from_client_id(client_id)

    with app.app_context():
        db.create_all()
        slug = scheduled_scenario_slug()
        run = get_or_start_daily_run(
            scenario_slug=slug,
            user_id=None,
            session_fingerprint=fp,
        )
        scenario = _load(slug)
        for turn in scenario['turns']:
            choice_id = turn['choices'][0]['id']
            result = apply_run_choice(run, choice_id)
            run = db.session.get(GameRun, run.id)
            if result['game_complete']:
                break

    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b"View today" in resp.data or b"view today" in resp.data.lower()
