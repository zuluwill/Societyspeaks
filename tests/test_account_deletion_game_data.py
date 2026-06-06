"""Account deletion must cascade Society Play data per privacy-policy §1.4."""

from datetime import datetime, timedelta, timezone

import pytest

from app.game.engine.scenario import load_scenario
from app.game.services.challenge_service import get_or_create_challenge
from app.game.services.run_service import apply_run_choice, get_or_start_daily_run
from app.lib.vote_identity import fingerprint_from_client_id
from app.models import User
from app.models.game import (
    GameChallenge,
    GameReminderSubscription,
    GameRun,
    GameRunOutcome,
)
from app.settings.routes import _delete_game_data_for_user


def _complete_run(db, run):
    scenario = load_scenario(run.scenario_slug)
    for turn in scenario['turns']:
        result = apply_run_choice(run, turn['choices'][0]['id'])
        run = db.session.get(GameRun, run.id)
        if result['game_complete']:
            break
    return run


def test_delete_game_data_helper_removes_runs_outcomes_challenges_reminders(app, db):
    fp = fingerprint_from_client_id('del' * 21)
    with app.app_context():
        user = User(email='gamer@example.com', username='gamer')
        user.set_password('secure-pass-123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        run = get_or_start_daily_run(
            scenario_slug='debt-inherited',
            user_id=user_id,
            session_fingerprint=fp,
        )
        run = _complete_run(db, run)
        get_or_create_challenge(run)

        db.session.add(
            GameReminderSubscription(
                user_id=user_id,
                email='gamer@example.com',
                session_fingerprint=fp,
            )
        )
        db.session.commit()

        assert GameRun.query.filter_by(user_id=user_id).count() == 1
        assert GameRunOutcome.query.count() == 1
        assert GameChallenge.query.count() == 1
        assert GameReminderSubscription.query.filter_by(user_id=user_id).count() == 1

        _delete_game_data_for_user(user_id)
        db.session.commit()

        assert GameRun.query.filter_by(user_id=user_id).count() == 0
        assert GameRunOutcome.query.count() == 0
        assert GameChallenge.query.count() == 0
        assert GameReminderSubscription.query.filter_by(user_id=user_id).count() == 0


def test_delete_account_route_removes_game_history(app, client, db):
    with app.app_context():
        user = User(email='route-del@example.com', username='routedel')
        user.set_password('secure-pass-123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        fp = fingerprint_from_client_id('rtd' * 21)
        run = get_or_start_daily_run(
            scenario_slug='housing-squeeze',
            user_id=user_id,
            session_fingerprint=fp,
        )
        _complete_run(db, run)
        run_uuid = run.uuid

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    resp = client.post('/settings/delete-account', follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        assert db.session.get(User, user_id) is None
        assert GameRun.query.filter_by(uuid=run_uuid).count() == 0
        assert GameRunOutcome.query.count() == 0


def test_anonymous_runs_survive_account_deletion(app, db):
    """Fingerprint-only runs must not be purged when a different user deletes."""
    fp = fingerprint_from_client_id('ano' * 21)
    with app.app_context():
        anon_run = get_or_start_daily_run(
            scenario_slug='debt-inherited',
            user_id=None,
            session_fingerprint=fp,
        )
        anon_uuid = anon_run.uuid

        user = User(email='other@example.com', username='other')
        user.set_password('secure-pass-123')
        db.session.add(user)
        db.session.commit()

        owned = get_or_start_daily_run(
            scenario_slug='housing-squeeze',
            user_id=user.id,
            session_fingerprint=fp,
        )
        owned_uuid = owned.uuid

        _delete_game_data_for_user(user.id)
        db.session.commit()

        assert db.session.get(GameRun, anon_run.id) is not None
        assert GameRun.query.filter_by(uuid=anon_uuid).count() == 1
        assert GameRun.query.filter_by(uuid=owned_uuid).count() == 0
