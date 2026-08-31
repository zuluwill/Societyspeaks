"""Tests for per-recipient send-failure classification and suppression policy.

Covers the fix for recurring Resend 400s: distinguish permanent per-recipient
failures from transient ones, stop retrying a permanently-failing edition every
catch-up run, and auto-suppress a dead address after a threshold.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.brief.email_client import (
    BriefEmailScheduler,
    ResendClient,
    build_send_failure_record,
    classify_send_failure,
    format_send_failure_message,
    log_brief_batch_results,
    log_send_failure,
    truncate_resend_error,
    _PAGEABLE_BATCH_ERROR_THRESHOLD,
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
    ('API error: 520 - resend.com | 520: Web server is returning an unknown error', 'transient'),
    ('Transient 520 after 3 attempts', 'transient'),
    ('Rate limited after 3 attempts', 'transient'),
    ('Transient 503 after 3 attempts', 'transient'),
    ('simulated API failure', 'transient'),           # no status code — unknown → retry
    ('', 'transient'),
    (None, 'transient'),
])
def test_classify_send_failure_maps_codes(error, expected):
    assert classify_send_failure(error) == expected


def test_truncate_resend_error_strips_html_and_caps_length():
    raw = 'API error: 400 - <html><head><title>400 Bad Request</title></head><body>x</body></html>'
    out = truncate_resend_error(raw, max_len=40)
    assert '<' not in out
    assert '400 Bad Request' in out
    assert len(out) <= 40


def test_build_send_failure_record_marks_pageable_transient_only():
    permanent = build_send_failure_record(
        subscriber_id=1,
        email='a@example.com',
        brief_id=9,
        resend_error='API error: 400 - bad',
        send_failure_count=1,
    )
    assert permanent['classification'] == 'permanent'
    assert permanent['pageable'] is False

    transient = build_send_failure_record(
        subscriber_id=2,
        email='b@example.com',
        brief_id=9,
        resend_error='API error: 503 - down',
        send_failure_count=0,
    )
    assert transient['classification'] == 'transient'
    assert transient['pageable'] is True


def test_format_send_failure_message_includes_structured_fields():
    record = build_send_failure_record(
        subscriber_id=4581,
        email='user@example.com',
        brief_id=236,
        resend_error='API error: 400 - <html>400 Bad Request</html>',
        send_failure_count=1,
    )
    msg = format_send_failure_message(record)
    assert 'subscriber_id=4581' in msg
    assert 'brief_id=236' in msg
    assert 'send_failures=1/3' in msg
    assert '<html>' not in msg


def test_log_brief_batch_results_emits_summary_only(app):
    with app.app_context():
        with patch('app.brief.email_client.logger') as mock_logger:
            log_brief_batch_results(
                {
                    'sent': 71,
                    'failed': 1,
                    'failures': [
                        build_send_failure_record(
                            subscriber_id=1,
                            email='a@example.com',
                            brief_id=2,
                            resend_error='API error: 400 - bad',
                            send_failure_count=1,
                        )
                    ],
                },
                cadence='daily',
            )
            mock_logger.info.assert_called_once()
            assert mock_logger.info.call_args[0][1:] == ('Daily', 71, 1)
            mock_logger.warning.assert_called_once()
            mock_logger.error.assert_not_called()


def test_log_brief_batch_results_isolated_pageable_is_warning(app):
    """One Cloudflare 520 must not page — catch-up retries the claim."""
    with app.app_context():
        with patch('app.brief.email_client.logger') as mock_logger:
            log_brief_batch_results(
                {
                    'sent': 70,
                    'failed': 1,
                    'failures': [
                        build_send_failure_record(
                            subscriber_id=1,
                            email='a@example.com',
                            brief_id=2,
                            resend_error='API error: 520 - HTML error page',
                            send_failure_count=0,
                        )
                    ],
                },
                cadence='daily',
            )
            mock_logger.error.assert_not_called()
            mock_logger.warning.assert_called_once()
            assert 'pageable failure' in mock_logger.warning.call_args[0][0]


def test_log_brief_batch_results_outage_pageable_is_error(app):
    """A burst of transient failures in one batch is an outage — ERROR."""
    failures = [
        build_send_failure_record(
            subscriber_id=i,
            email=f'u{i}@example.com',
            brief_id=2,
            resend_error='Transient 520 after 3 attempts',
            send_failure_count=0,
        )
        for i in range(_PAGEABLE_BATCH_ERROR_THRESHOLD)
    ]
    with app.app_context():
        with patch('app.brief.email_client.logger') as mock_logger:
            log_brief_batch_results(
                {'sent': 10, 'failed': len(failures), 'failures': failures},
                cadence='daily',
            )
            mock_logger.error.assert_called_once()
            mock_logger.warning.assert_not_called()


def test_log_send_failure_pageable_is_warning_and_omits_email_extra(app):
    record = build_send_failure_record(
        subscriber_id=4188,
        email='user@example.com',
        brief_id=284,
        resend_error='API error: 520 - resend.com | 520',
        send_failure_count=0,
    )
    with app.app_context():
        with patch('app.brief.email_client.logger') as mock_logger:
            log_send_failure(record)
            mock_logger.error.assert_not_called()
            mock_logger.warning.assert_called_once()
            extra = mock_logger.warning.call_args.kwargs.get('extra') or {}
            assert 'email' not in extra
            assert extra.get('subscriber_id') == 4188


def test_log_brief_batch_results_captures_daily_brief_sent(app):
    with app.app_context():
        with patch('app.lib.posthog_utils.safe_system_capture') as capture:
            log_brief_batch_results(
                {
                    'sent': 71,
                    'failed': 1,
                    '_send_meta': {
                        'brief_id': 236,
                        'brief_date': '2026-07-22',
                        'brief_type': 'daily',
                        'cadence': 'daily',
                        'daily_question_id': 80,
                    },
                },
                cadence='daily',
            )
            capture.assert_called_once_with(
                'daily_brief_sent',
                properties={
                    'cadence': 'daily',
                    'sent': 71,
                    'failed': 1,
                    'brief_id': 236,
                    'brief_date': '2026-07-22',
                    'brief_type': 'daily',
                    'daily_question_id': 80,
                },
                insert_id='daily_brief_sent:daily:236',
            )


def test_log_brief_batch_results_skips_posthog_when_no_sends(app):
    with app.app_context():
        with patch('app.lib.posthog_utils.safe_system_capture') as capture:
            log_brief_batch_results({'sent': 0, 'failed': 0}, cadence='weekly')
            capture.assert_not_called()


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
        assert len(results['failures']) == 1
        assert results['failures'][0]['classification'] == 'permanent'
        assert results['failures'][0]['pageable'] is False

        db.session.expire_all()
        refreshed = db.session.get(DailyBriefSubscriber, sub_id)
        # Claim retained → can_receive_brief(brief.id) is now False, so no
        # within-day retry of this edition.
        assert refreshed.last_brief_id_sent == brief_id


def test_send_to_subscribers_structured_failure_is_not_pageable(app, db, brief_and_subscriber):
    brief_id, sub_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()

        def fake_send(subscriber, brief):
            client.last_send_error = 'API error: 400 - <html>400 Bad Request</html>'
            client._handle_send_failure(subscriber)
            return False

        client.send_brief = fake_send
        sched = BriefEmailScheduler.__new__(BriefEmailScheduler)
        sched.client = client

        with patch('app.brief.email_client.log_send_failure') as mock_log:
            results = sched.send_to_subscribers([sub], brief)
            mock_log.assert_called_once()
            record = mock_log.call_args[0][0]
            assert record['pageable'] is False
            assert record['send_failure_count'] == 1

        assert results['failures'][0]['pageable'] is False
