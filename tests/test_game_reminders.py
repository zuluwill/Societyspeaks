"""Tests for the daily re-engagement reminder: subscription, send logic
(skip-if-played, miss counting, dormant auto-pause), routes, and opt-in render."""

from datetime import datetime, time, timedelta

import app.resend_client as resend_client
from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.services.daily_service import utc_game_date
from app.game.services.reminder_service import (
    has_active_reminder,
    send_due_game_reminders,
    subscribe_to_reminders,
    unsubscribe,
)
from app.lib.time import utcnow_naive
from app.lib.vote_identity import fingerprint_from_client_id
from app.models.game import GameReminderSubscription, GameRun, GameRunOutcome


def _make_completed_daily(db, *, fingerprint, when=None, scenario_slug='debt-inherited'):
    started = when or datetime.combine(utc_game_date(), time(12, 0))
    run = GameRun(
        uuid=GameRun.generate_uuid(),
        scenario_slug=scenario_slug,
        mode='daily',
        session_fingerprint=fingerprint,
        society_name='Testland',
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
    db.session.add(GameRunOutcome(
        run_id=run.id,
        headline='A nation, governed.',
        governance_label='Pragmatic survivor',
        outcome_category='mixed_legacy',
        axis_trust_autonomy=50.0,
        axis_prosperity_fairness=50.0,
        stat_finals_json={},
        trait_chips_json=[],
    ))
    db.session.commit()
    return run


def _make_due_sub(db, *, email, fingerprint=None, **kwargs):
    sub = GameReminderSubscription(
        email=email,
        session_fingerprint=fingerprint,
        next_send_at=utcnow_naive() - timedelta(minutes=1),
    )
    sub.ensure_unsubscribe_token()
    for k, v in kwargs.items():
        setattr(sub, k, v)
    db.session.add(sub)
    db.session.commit()
    return sub


# ---------- Subscription model / service ----------

def test_subscribe_creates_active_subscription(app, db):
    with app.app_context():
        sub = subscribe_to_reminders(email='Player@Example.com ', session_fingerprint='f' * 64)
        assert sub is not None
        assert sub.email == 'player@example.com'  # normalised
        assert sub.is_active
        assert sub.unsubscribe_token
        assert sub.next_send_at is not None


def test_subscribe_rejects_invalid_email(app, db):
    with app.app_context():
        assert subscribe_to_reminders(email='not-an-email') is None
        assert subscribe_to_reminders(email='') is None


def test_subscribe_is_idempotent_and_reactivates(app, db):
    with app.app_context():
        sub1 = subscribe_to_reminders(email='dup@example.com', preferred_hour=9)
        unsubscribe(sub1)
        assert not sub1.is_active
        sub2 = subscribe_to_reminders(email='dup@example.com', preferred_hour=20)
        assert sub2.id == sub1.id  # same row
        assert sub2.is_active
        assert sub2.preferred_hour == 20
        assert GameReminderSubscription.query.filter_by(email='dup@example.com').count() == 1


def test_has_active_reminder(app, db):
    with app.app_context():
        subscribe_to_reminders(email='live@example.com', session_fingerprint='g' * 64)
        assert has_active_reminder(session_fingerprint='g' * 64)
        assert has_active_reminder(email='live@example.com')
        assert not has_active_reminder(session_fingerprint='z' * 64)


# ---------- Send orchestration ----------

def test_send_skips_player_who_played_today(app, db, monkeypatch):
    sent_calls = []
    monkeypatch.setattr(resend_client, 'send_game_reminder_email',
                        lambda *a, **k: sent_calls.append(k) or True)
    with app.app_context():
        fp = 'a' * 64
        _make_completed_daily(db, fingerprint=fp)
        sub = _make_due_sub(db, email='played@example.com', fingerprint=fp)
        old_next = sub.next_send_at

        result = send_due_game_reminders(db)
        assert result['skipped'] == 1
        assert result['sent'] == 0
        assert sent_calls == []
        db.session.refresh(sub)
        assert sub.consecutive_misses == 0
        assert sub.next_send_at > old_next  # rescheduled forward


def test_send_emails_player_who_has_not_played(app, db, monkeypatch):
    monkeypatch.setattr(resend_client, 'send_game_reminder_email', lambda *a, **k: True)
    with app.app_context():
        sub = _make_due_sub(db, email='absent@example.com', fingerprint='b' * 64)
        result = send_due_game_reminders(db)
        assert result['sent'] == 1
        db.session.refresh(sub)
        assert sub.reminder_count == 1
        assert sub.consecutive_misses == 1
        assert sub.last_sent_at is not None


def test_send_resets_misses_when_player_engaged_since_last_nudge(app, db, monkeypatch):
    """A daily player who plays AFTER the nudge each day must not be auto-paused
    just because they haven't played the new UTC day yet by the next nudge time.
    """
    monkeypatch.setattr(resend_client, 'send_game_reminder_email', lambda *a, **k: True)
    with app.app_context():
        fp = 'e' * 64
        # Subscription that just sent a nudge yesterday and the player played
        # in between (yesterday, after the nudge fired).
        yesterday_send = utcnow_naive() - timedelta(days=1)
        played_yesterday_after_send = yesterday_send + timedelta(hours=2)
        sub = _make_due_sub(
            db, email='afterhours@example.com', fingerprint=fp,
            last_sent_at=yesterday_send,
            consecutive_misses=4,  # one away from auto-pause
        )
        _make_completed_daily(db, fingerprint=fp, when=played_yesterday_after_send)

        result = send_due_game_reminders(db)
        assert result['sent'] == 1
        assert result['paused'] == 0  # engagement detected → no pause
        db.session.refresh(sub)
        # Counter reset because they engaged since the last nudge.
        assert sub.consecutive_misses == 0
        assert sub.is_active


def test_send_auto_pauses_after_max_misses(app, db, monkeypatch):
    monkeypatch.setattr(resend_client, 'send_game_reminder_email', lambda *a, **k: True)
    with app.app_context():
        sub = _make_due_sub(
            db, email='dormant@example.com', fingerprint='c' * 64,
            consecutive_misses=GameReminderSubscription.MAX_CONSECUTIVE_MISSES - 1,
        )
        result = send_due_game_reminders(db)
        assert result['sent'] == 1
        assert result['paused'] == 1
        db.session.refresh(sub)
        assert not sub.is_active
        assert sub.unsubscribe_reason == 'dormant'


def test_send_ignores_unsubscribed_and_not_due(app, db, monkeypatch):
    monkeypatch.setattr(resend_client, 'send_game_reminder_email', lambda *a, **k: True)
    with app.app_context():
        # Unsubscribed
        gone = _make_due_sub(db, email='gone@example.com')
        gone.unsubscribed_at = utcnow_naive()
        # Not due yet
        _make_due_sub(db, email='future@example.com',
                      next_send_at=utcnow_naive() + timedelta(hours=2))
        db.session.commit()
        result = send_due_game_reminders(db)
        assert result['due'] == 0
        assert result['sent'] == 0


def test_send_reschedules_on_email_failure(app, db, monkeypatch):
    monkeypatch.setattr(resend_client, 'send_game_reminder_email', lambda *a, **k: False)
    with app.app_context():
        sub = _make_due_sub(db, email='fail@example.com', fingerprint='d' * 64)
        old_next = sub.next_send_at
        result = send_due_game_reminders(db)
        assert result['errors'] == 1
        assert result['sent'] == 0
        db.session.refresh(sub)
        assert sub.reminder_count == 0  # not counted as sent
        assert sub.next_send_at > old_next  # rescheduled so it won't hot-loop


# ---------- Routes ----------

def test_subscribe_route_json_creates_subscription(app, client, db):
    client.set_cookie('ss_voter_client_id', 'k' * 64)
    resp = client.post(
        '/play/reminders/subscribe',
        data={'email': 'route@example.com', 'timezone': 'Europe/London', 'hour': '8'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 200
    assert resp.json['ok'] is True
    with app.app_context():
        sub = GameReminderSubscription.query.filter_by(email='route@example.com').first()
        assert sub is not None and sub.is_active
        assert sub.timezone == 'Europe/London'


def test_subscribe_route_rejects_bad_email_json(app, client, db):
    resp = client.post(
        '/play/reminders/subscribe',
        data={'email': 'nope'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 400
    assert resp.json['ok'] is False


def test_subscribe_route_ignores_external_referrer(app, client, db):
    """Form POST falls back to game.index when Referer points off-site
    (defends against a crafted Referer header → open redirect)."""
    resp = client.post(
        '/play/reminders/subscribe',
        data={'email': 'ext@example.com'},
        headers={'Referer': 'https://evil.example/landed-here'},
    )
    assert resp.status_code == 302
    # Same-host redirect (the test client's host) to /play/
    assert resp.location.endswith('/play/') or resp.location == '/play/'


def test_unsubscribe_route_one_click(app, client, db):
    with app.app_context():
        sub = subscribe_to_reminders(email='oneclick@example.com')
        token = sub.unsubscribe_token
    resp = client.post(
        f'/play/reminders/unsubscribe?token={token}',
        data={'List-Unsubscribe': 'One-Click'},
    )
    assert resp.status_code == 200
    with app.app_context():
        sub = GameReminderSubscription.query.filter_by(email='oneclick@example.com').first()
        assert not sub.is_active
        assert sub.unsubscribe_reason == 'one_click'


def test_unsubscribe_route_get_renders_confirmation(app, client, db):
    with app.app_context():
        sub = subscribe_to_reminders(email='human@example.com')
        token = sub.unsubscribe_token
    resp = client.get(f'/play/reminders/unsubscribe?token={token}')
    assert resp.status_code == 200
    assert b'Reminders stopped' in resp.data
    with app.app_context():
        sub = GameReminderSubscription.query.filter_by(email='human@example.com').first()
        assert not sub.is_active


def test_unsubscribe_route_invalid_token_post_is_silent(app, client, db):
    resp = client.post('/play/reminders/unsubscribe?token=bogus',
                       data={'List-Unsubscribe': 'One-Click'})
    assert resp.status_code == 200


# ---------- Opt-in render on outcome ----------

def test_outcome_shows_reminder_optin_for_owner(app, client, db):
    client_id = 'm' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        run = _make_completed_daily(db, fingerprint=fp)
        run_uuid = run.uuid
    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    assert b'data-reminder-form' in resp.data
    # The form must carry a CSRF token; conftest disables CSRF for the test
    # client but a missing field would break production POSTs silently.
    assert b'name="csrf_token"' in resp.data
    assert b'data-csrf="' in resp.data


def test_outcome_hides_optin_when_already_subscribed(app, client, db):
    client_id = 'n' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        run = _make_completed_daily(db, fingerprint=fp)
        run_uuid = run.uuid
        subscribe_to_reminders(email='sub@example.com', session_fingerprint=fp)
    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    assert b'data-reminder-form' not in resp.data
