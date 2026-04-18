"""Tests for daily subscribe UX helpers and redirects (DRY messaging)."""

import hashlib
import hmac
import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def client(app, db):
    return app.test_client()


def _patch_process(monkeypatch, result):
    monkeypatch.setattr('app.daily.routes.process_daily_question_subscription', lambda *a, **k: result)


def _valid_bot_ts_field(secret_key: str) -> str:
    """Signed _ts older than MIN_SUBMIT_SECONDS so check_bot_submission passes."""
    ts = str(int(time.time()) - 60)
    sig = hmac.new(secret_key.encode(), ts.encode(), hashlib.sha256).hexdigest()[:16]
    return f'{ts}.{sig}'


class TestFormatDqHour12h:
    def test_midnight_and_noon(self):
        from app.daily.utils import format_dq_hour_12h

        assert format_dq_hour_12h(0) == '12:00 am'
        assert format_dq_hour_12h(12) == '12:00 pm'

    def test_morning_and_afternoon(self):
        from app.daily.utils import format_dq_hour_12h

        assert format_dq_hour_12h(9) == '9:00 am'
        assert format_dq_hour_12h(17) == '5:00 pm'


class TestDailyQuestionEmailSendWindowLabel:
    def test_matches_constants(self):
        from app.daily import constants as c
        from app.daily.utils import daily_question_email_send_window_utc_label

        label = daily_question_email_send_window_utc_label()
        assert str(c.DAILY_QUESTION_EMAIL_SEND_UTC_HOUR) in label
        assert f'{c.DAILY_QUESTION_EMAIL_SEND_UTC_MINUTE:02d}' in label
        assert 'UTC' in label


class TestBuildDailySubscribeRecap:
    def test_weekly_includes_day_and_time(self):
        from app.daily.utils import build_daily_subscribe_recap

        sub = SimpleNamespace(
            email_frequency='weekly',
            timezone='Europe/London',
            preferred_send_day=1,
            preferred_send_hour=9,
        )
        r = build_daily_subscribe_recap(sub)
        assert r['frequency'] == 'weekly'
        assert r['weekly_day_name'] == 'Tuesday'
        assert r['weekly_time_label'] == '9:00 am'
        assert r['timezone'] == 'Europe/London'

    def test_monthly_has_schedule_copy(self):
        from app.daily.utils import build_daily_subscribe_recap, monthly_digest_schedule_short

        sub = SimpleNamespace(
            email_frequency='monthly',
            timezone='America/New_York',
            preferred_send_day=3,
            preferred_send_hour=14,
        )
        r = build_daily_subscribe_recap(sub)
        assert r['frequency'] == 'monthly'
        assert 'weekly_day_name' not in r
        assert r['monthly_schedule_short'] == monthly_digest_schedule_short()

    def test_daily_has_utc_window(self):
        from app.daily.utils import build_daily_subscribe_recap, daily_question_email_send_window_utc_label

        sub = SimpleNamespace(
            email_frequency='daily',
            timezone=None,
            preferred_send_day=1,
            preferred_send_hour=9,
        )
        r = build_daily_subscribe_recap(sub)
        assert r['frequency'] == 'daily'
        assert r['daily_window_label'] == daily_question_email_send_window_utc_label()


class TestSubscribeAlreadyActiveRedirect:
    def test_redirects_to_subscribe_with_flag(self, monkeypatch, client, db):
        client.application.config['WTF_CSRF_ENABLED'] = False
        secret = client.application.config['SECRET_KEY']
        _patch_process(
            monkeypatch,
            {
                'status': 'already_active',
                'subscriber': None,
                'message': 'Already in.',
            },
        )
        resp = client.post(
            '/daily/subscribe',
            data={
                'email': 'any@example.com',
                'email_frequency': 'weekly',
                'timezone': 'UTC',
                'preferred_send_day': '1',
                'preferred_send_hour': '9',
                '_ts': _valid_bot_ts_field(secret),
                'website_url': '',
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert '/daily/subscribe' in resp.location
        assert 'already_active=1' in resp.location

    def test_success_sets_session_recap(self, monkeypatch, client, db):
        client.application.config['WTF_CSRF_ENABLED'] = False
        secret = client.application.config['SECRET_KEY']
        sub = SimpleNamespace(
            email_frequency='weekly',
            timezone='UTC',
            preferred_send_day=0,
            preferred_send_hour=8,
        )
        _patch_process(
            monkeypatch,
            {
                'status': 'created',
                'subscriber': sub,
                'message': 'OK',
            },
        )
        client.post(
            '/daily/subscribe',
            data={
                'email': 'new@example.com',
                'email_frequency': 'weekly',
                'timezone': 'UTC',
                'preferred_send_day': '0',
                'preferred_send_hour': '8',
                '_ts': _valid_bot_ts_field(secret),
                'website_url': '',
            },
            follow_redirects=False,
        )
        with client.session_transaction() as sess:
            recap = sess.get('daily_subscribe_recap')
        assert recap is not None
        assert recap['frequency'] == 'weekly'
        assert recap['weekly_day_name'] == 'Monday'
