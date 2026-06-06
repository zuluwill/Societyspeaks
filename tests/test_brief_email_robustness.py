"""Regression tests for daily-brief email batch isolation and fallback paths."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.brief.email_client import BriefEmailScheduler, ResendClient
from app.models import DailyBrief, DailyBriefSubscriber, db


def _bare_client() -> ResendClient:
    client = ResendClient.__new__(ResendClient)
    client._disabled = True
    client.api_key = 'test'
    client.from_email = 'Brief <brief@test.io>'
    client._from_email_addr = 'brief@test.io'
    client.reply_to = 'reply@test.io'
    client.rate_limiter = MagicMock()
    client.last_send_error = None
    return client


@pytest.fixture
def brief_and_subscriber(app, db):
    with app.app_context():
        brief = DailyBrief(
            date=date.today(),
            title='Test Brief',
            intro_text='Intro',
            status='published',
        )
        db.session.add(brief)
        db.session.flush()
        sub = DailyBriefSubscriber(
            email='one@example.com',
            status='active',
            magic_token='magic-one',
        )
        sub2 = DailyBriefSubscriber(
            email='two@example.com',
            status='active',
            magic_token='magic-two',
        )
        db.session.add_all([sub, sub2])
        db.session.commit()
        return brief.id, sub.id, sub2.id


def test_send_brief_resets_stale_last_send_error(app, db, brief_and_subscriber):
    brief_id, _sub_id, _sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        client = _bare_client()
        client.last_send_error = 'stale from subscriber N-1'

        bad_sub = MagicMock()
        bad_sub.id = 99
        bad_sub.email = 'not-an-email'
        ok = client.send_brief(bad_sub, brief)
        assert ok is False
        assert client.last_send_error is None


def test_send_brief_outer_exception_surfaces_error(app, db, brief_and_subscriber):
    brief_id, sub_id, _sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()

        with patch.object(client, '_get_sorted_brief_items', side_effect=RuntimeError('db gone')):
            ok = client.send_brief(sub, brief)
        assert ok is False
        assert 'db gone' in (client.last_send_error or '')


def test_fallback_html_survives_brief_attribute_expiry(app, db, brief_and_subscriber):
    brief_id, _sub_id, _sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        client = _bare_client()
        html = client._fallback_html(
            brief,
            magic_link_url='https://example.com/brief/m/x',
            unsubscribe_url='https://example.com/brief/unsubscribe/x',
        )
        assert 'SOCIETY SPEAKS DAILY BRIEF' in html
        assert 'https://example.com/brief/m/x' in html


def test_batch_send_continues_after_flush_failure(app, db, brief_and_subscriber):
    brief_id, sub_id, sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        sub2 = db.session.get(DailyBriefSubscriber, sub2_id)

        mock_client = MagicMock()
        mock_client.send_brief.return_value = True

        sched = BriefEmailScheduler.__new__(BriefEmailScheduler)
        sched.client = mock_client

        original_flush = db.session.flush
        calls = {'n': 0}

        def flaky_flush():
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('connection dropped')
            return original_flush()

        with patch.object(db.session, 'flush', side_effect=flaky_flush):
            results = sched.send_to_subscribers([sub, sub2], brief)

        assert results['sent'] == 1
        assert results['failed'] == 1
        assert mock_client.send_brief.call_count == 1
