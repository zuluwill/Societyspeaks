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

        original_commit = db.session.commit
        calls = {'n': 0}

        def flaky_commit():
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('connection dropped')
            return original_commit()

        # First claim-commit fails (subscriber 1); the loop must isolate the
        # error and still send to subscriber 2.
        with patch.object(db.session, 'commit', side_effect=flaky_commit):
            results = sched.send_to_subscribers([sub, sub2], brief)

        assert results['sent'] == 1
        assert results['failed'] == 1
        assert mock_client.send_brief.call_count == 1


def test_send_claim_prevents_duplicate_sends(app, db, brief_and_subscriber):
    """Two overlapping send loops (deploy zombie + catch-up run, or a manual
    resume) must produce exactly one send per subscriber: the conditional
    claim on (last_brief_id_sent == brief.id) lets only one loop win.
    Regression for 2026-07-12 (295 duplicated send records)."""
    brief_id, sub_id, sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        subs = [db.session.get(DailyBriefSubscriber, sub_id),
                db.session.get(DailyBriefSubscriber, sub2_id)]

        mock_client = MagicMock()
        mock_client.send_brief.return_value = True
        sched = BriefEmailScheduler.__new__(BriefEmailScheduler)
        sched.client = mock_client

        first = sched.send_to_subscribers(subs, brief)
        second = sched.send_to_subscribers(subs, brief)

        assert first['sent'] == 2
        assert second['sent'] == 0
        assert mock_client.send_brief.call_count == 2


def test_failed_send_releases_claim_for_retry(app, db, brief_and_subscriber):
    """A failed send must not leave the subscriber claimed, or catch-up runs
    would silently skip them forever."""
    brief_id, sub_id, _ = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)

        mock_client = MagicMock()
        mock_client.send_brief.return_value = False
        mock_client.last_send_error = 'simulated API failure'
        sched = BriefEmailScheduler.__new__(BriefEmailScheduler)
        sched.client = mock_client

        results = sched.send_to_subscribers([sub], brief)
        assert results['failed'] == 1

        db.session.expire_all()
        refreshed = db.session.get(DailyBriefSubscriber, sub_id)
        assert refreshed.last_brief_id_sent is None  # claim released

        mock_client.send_brief.return_value = True
        retry = sched.send_to_subscribers([refreshed], brief)
        assert retry['sent'] == 1
