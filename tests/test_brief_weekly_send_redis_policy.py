"""Regression: weekly brief sends must fail closed without Redis (match daily policy)."""

from unittest.mock import MagicMock, patch


def test_weekly_brief_hourly_returns_empty_when_redis_url_missing(app, app_context, monkeypatch):
    monkeypatch.delenv('REDIS_URL', raising=False)

    with patch('app.brief.email_client.ResendClient', return_value=MagicMock()):
        from app.brief.email_client import BriefEmailScheduler

        sched = BriefEmailScheduler()
        result = sched.send_weekly_brief_hourly()

    assert result == {'sent': 0, 'failed': 0, 'errors': []}


def test_weekly_brief_hourly_returns_empty_when_lock_not_acquired(app, app_context, monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:9/0')
    fake_client = MagicMock()
    fake_client.set = MagicMock(return_value=False)

    with patch('app.brief.email_client.ResendClient', return_value=MagicMock()):
        with patch('app.lib.redis_client.get_client', return_value=fake_client):
            from app.brief.email_client import BriefEmailScheduler

            sched = BriefEmailScheduler()
            result = sched.send_weekly_brief_hourly()

    assert result == {'sent': 0, 'failed': 0, 'errors': []}
    fake_client.set.assert_called_once()


def test_weekly_lock_is_released_after_a_send(db, monkeypatch):
    """A completed send must free the slot, not hold it for the full 3500s TTL.

    The old hand-rolled lock never released, so a transient failure could not be
    retried until the key expired an hour later.
    """
    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:9/0')
    fake_client = MagicMock()
    fake_client.set = MagicMock(return_value=True)   # acquired

    with patch('app.brief.email_client.ResendClient', return_value=MagicMock()):
        with patch('app.lib.redis_client.get_client', return_value=fake_client):
            from app.brief.email_client import BriefEmailScheduler

            sched = BriefEmailScheduler()
            sched.send_weekly_brief_hourly()   # no weekly brief exists → returns None

    # Safe unlock is a token-checked Lua eval, not an unconditional DEL.
    assert fake_client.eval.called, "lock was never released"
    assert not fake_client.delete.called


def test_weekly_lock_is_released_even_when_the_send_raises(app, app_context, monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:9/0')
    fake_client = MagicMock()
    fake_client.set = MagicMock(return_value=True)

    with patch('app.brief.email_client.ResendClient', return_value=MagicMock()):
        with patch('app.lib.redis_client.get_client', return_value=fake_client):
            from app.brief.email_client import BriefEmailScheduler

            sched = BriefEmailScheduler()
            with patch.object(
                sched, 'get_subscribers_for_hour', side_effect=RuntimeError('db gone')
            ):
                with patch(
                    'app.brief.email_client.DailyBrief'
                ) as mock_brief_model:
                    import datetime as _dt
                    mock_brief_model.query.filter.return_value.order_by.return_value.first.return_value = (
                        MagicMock(date=_dt.date.today(), id=1)
                    )
                    try:
                        sched.send_weekly_brief_hourly()
                    except RuntimeError:
                        pass

    assert fake_client.eval.called, "lock leaked when the send raised"


def test_weekly_lock_key_is_scoped_per_hour(app, app_context):
    """Each hourly run serves a different timezone cohort and needs its own key."""
    import datetime as _dt
    from app.brief.email_client import _weekly_send_lock_key

    d = _dt.date(2026, 7, 26)
    assert _weekly_send_lock_key(d, 9) != _weekly_send_lock_key(d, 10)
    assert _weekly_send_lock_key(d, 9).startswith('brief_send_lock:weekly:')


def test_weekly_lock_token_is_not_the_pid(app, app_context, monkeypatch):
    """PIDs collide across Render instances; the token must be random."""
    import os
    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:9/0')
    fake_client = MagicMock()
    fake_client.set = MagicMock(return_value=True)

    with patch('app.lib.redis_client.get_client', return_value=fake_client):
        from app.brief.email_client import acquire_daily_send_lock, _weekly_send_lock_key

        _, _, _, token, _ = acquire_daily_send_lock(
            lock_key=_weekly_send_lock_key()
        )

    assert token != os.getpid()
    assert token != str(os.getpid())
    assert isinstance(token, str) and len(token) >= 16
