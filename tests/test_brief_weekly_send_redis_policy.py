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
