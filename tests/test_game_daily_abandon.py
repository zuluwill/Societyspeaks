"""Daily run expiry (abandon) and grace-window replay guards."""

from datetime import datetime, timedelta, timezone

from app.game.services.daily_service import scheduled_scenario_slug, utc_game_date
from app.game.services.run_service import get_or_start_daily_run
from app.lib.vote_identity import fingerprint_from_client_id
from app.models.game import GameRun


def _play_to_completion(db, run):
    from app.game.engine.scenario import load_scenario
    from app.game.services.run_service import apply_run_choice

    scenario = load_scenario(run.scenario_slug)
    for turn in scenario['turns']:
        result = apply_run_choice(run, turn['choices'][0]['id'])
        run = db.session.get(GameRun, run.id)
        if result['game_complete']:
            break
    return run


def test_stale_in_progress_daily_marked_abandoned_and_restarted(app, db):
    fp = fingerprint_from_client_id('abn' * 21)
    with app.app_context():
        db.create_all()
        slug = scheduled_scenario_slug()
        run = get_or_start_daily_run(
            scenario_slug=slug,
            user_id=None,
            session_fingerprint=fp,
        )
        first_uuid = run.uuid
        stale = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25)
        run.last_active_at = stale
        db.session.commit()

        fresh = get_or_start_daily_run(
            scenario_slug=slug,
            user_id=None,
            session_fingerprint=fp,
        )
        abandoned = db.session.get(GameRun, run.id)
        assert abandoned.status == 'abandoned'
        assert fresh.uuid != first_uuid
        assert fresh.status == 'in_progress'


def test_completed_yesterday_daily_not_replayable_via_seed_date(app, db):
    """Grace-window visit to yesterday's URL returns completed run, not a fresh one."""
    fp = fingerprint_from_client_id('grc' * 21)
    yesterday = utc_game_date() - timedelta(days=1)
    slug = scheduled_scenario_slug(yesterday)

    with app.app_context():
        db.create_all()
        run = get_or_start_daily_run(
            scenario_slug=slug,
            user_id=None,
            session_fingerprint=fp,
            seed_date=yesterday,
        )
        y_start = datetime.combine(yesterday, datetime.min.time())
        run.started_at = y_start
        db.session.commit()
        run = _play_to_completion(db, run)
        run.started_at = y_start
        db.session.commit()
        completed_uuid = run.uuid

        rerun = get_or_start_daily_run(
            scenario_slug=slug,
            user_id=None,
            session_fingerprint=fp,
            seed_date=yesterday,
        )
        assert rerun.uuid == completed_uuid
        assert rerun.status == 'completed'
