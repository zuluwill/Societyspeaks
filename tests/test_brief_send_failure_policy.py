"""Tests for per-recipient send-failure classification and suppression policy.

Covers the fix for recurring Resend 400s: distinguish permanent per-recipient
failures from transient ones, stop retrying a permanently-failing edition every
catch-up run, and auto-suppress a dead address after a threshold.
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.brief.email_client import (
    BriefEmailScheduler,
    ResendClient,
    classify_send_failure,
)
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
        brief = DailyBrief(date=date.today(), title='Test Brief', intro_text='Intro', status='published')
        db.session.add(brief)
        db.session.flush()
        sub = DailyBriefSubscriber(email='one@example.com', status='active', magic_token='magic-one')
        db.session.add(sub)
        db.session.commit()
        return brief.id, sub.id


@pytest.mark.parametrize("error,expected", [
    ('API error: 422 - {"name":"validation_error"}', 'invalid_recipient'),
    ('API error: 400 - <html>...400 Bad Request...</html>', 'permanent'),
    ('API error: 403 - forbidden', 'transient'),      # account/global — never suppress a subscriber
    ('API error: 401 - unauthorized', 'transient'),   # bad API key — global
    ('API error: 429 - rate limited', 'transient'),
    ('API error: 500 - server error', 'transient'),
    ('Rate limited after 3 attempts', 'transient'),
    ('Transient 503 after 3 attempts', 'transient'),
    ('simulated API failure', 'transient'),           # no status code — unknown → retry
    ('', 'transient'),
    (None, 'transient'),
])
def test_classify_send_failure_maps_codes(error, expected):
    assert classify_send_failure(error) == expected


def test_model_failure_counter_increment_and_reset(app, db, brief_and_subscriber):
    _brief_id, sub_id = brief_and_subscriber
    with app.app_context():
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        assert sub.send_failure_count == 0
        assert sub.register_permanent_send_failure() is False  # 1
        assert sub.register_permanent_send_failure() is False  # 2
        assert sub.register_permanent_send_failure() is True   # 3 == threshold
        assert sub.send_failure_count == DailyBriefSubscriber.SEND_FAILURE_SUPPRESS_THRESHOLD
        sub.clear_send_failures()
        assert sub.send_failure_count == 0


def test_422_suppresses_immediately(app, db, brief_and_subscriber):
    _brief_id, sub_id = brief_and_subscriber
    with app.app_context():
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()
        client.last_send_error = 'API error: 422 - {"name":"validation_error"}'

        client._handle_send_failure(sub)

        refreshed = db.session.get(DailyBriefSubscriber, sub_id)
        assert refreshed.status == 'bounced'
        assert refreshed.unsubscribed_at is not None


def test_400_counts_then_suppresses_at_threshold(app, db, brief_and_subscriber):
    _brief_id, sub_id = brief_and_subscriber
    with app.app_context():
        client = _bare_client()
        client.last_send_error = 'API error: 400 - <html>400 Bad Request</html>'

        # First two failures: counted, still active.
        for expected_count in (1, 2):
            sub = db.session.get(DailyBriefSubscriber, sub_id)
            client._handle_send_failure(sub)
            refreshed = db.session.get(DailyBriefSubscriber, sub_id)
            assert refreshed.send_failure_count == expected_count
            assert refreshed.status == 'active'

        # Third failure crosses the threshold → suppressed.
        client._handle_send_failure(db.session.get(DailyBriefSubscriber, sub_id))
        refreshed = db.session.get(DailyBriefSubscriber, sub_id)
        assert refreshed.status == 'bounced'


def test_transient_failure_does_not_touch_subscriber(app, db, brief_and_subscriber):
    _brief_id, sub_id = brief_and_subscriber
    with app.app_context():
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()
        client.last_send_error = 'API error: 503 - server error'

        client._handle_send_failure(sub)

        refreshed = db.session.get(DailyBriefSubscriber, sub_id)
        assert refreshed.status == 'active'
        assert refreshed.send_failure_count == 0


def test_permanent_failure_keeps_claim(app, db, brief_and_subscriber):
    """A permanent 400 must NOT release the claim — otherwise the same edition
    is retried (and re-errors) on every catch-up run."""
    brief_id, sub_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)

        mock_client = MagicMock()
        mock_client.send_brief.return_value = False
        mock_client.last_send_error = 'API error: 400 - <html>400 Bad Request</html>'
        sched = BriefEmailScheduler.__new__(BriefEmailScheduler)
        sched.client = mock_client

        results = sched.send_to_subscribers([sub], brief)
        assert results['failed'] == 1

        db.session.expire_all()
        refreshed = db.session.get(DailyBriefSubscriber, sub_id)
        # Claim retained → can_receive_brief(brief.id) is now False, so no
        # within-day retry of this edition.
        assert refreshed.last_brief_id_sent == brief_id
