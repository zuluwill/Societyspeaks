"""Tests for safe subscriber deletion and email_event FK unlinking."""

import pytest

from app.lib.email_analytics import EmailAnalytics
from app.lib.email_subscriber_delete import (
    InvalidSubscriberIds,
    delete_brief_subscriber,
    delete_brief_subscribers_bulk,
    delete_question_subscriber,
    delete_question_subscribers_bulk,
    parse_subscriber_ids,
    unlink_email_events_for_brief_subscribers,
    unlink_email_events_for_question_subscribers,
)
from app.models import DailyBriefSubscriber, DailyQuestionSubscriber
from app.models.email import EmailEvent


def _record_brief_event(db, subscriber):
    EmailEvent.record_event(
        recipient_email=subscriber.email,
        event_type=EmailEvent.EVENT_SENT,
        email_category=EmailAnalytics.CATEGORY_DAILY_BRIEF,
        brief_subscriber_id=subscriber.id,
    )
    db.session.commit()


def _record_question_event(db, subscriber):
    EmailEvent.record_event(
        recipient_email=subscriber.email,
        event_type=EmailEvent.EVENT_SENT,
        email_category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
        question_subscriber_id=subscriber.id,
    )
    db.session.commit()


class TestParseSubscriberIds:
    def test_dedupes_and_parses_strings(self):
        assert parse_subscriber_ids(['3', '1', '3', '2']) == [3, 1, 2]

    def test_accepts_ints(self):
        assert parse_subscriber_ids([5, 5, 2]) == [5, 2]

    def test_rejects_non_numeric(self):
        with pytest.raises(InvalidSubscriberIds):
            parse_subscriber_ids(['12', 'abc'])

    def test_rejects_non_positive(self):
        with pytest.raises(InvalidSubscriberIds):
            parse_subscriber_ids(['0', '-1'])


class TestBriefSubscriberDelete:
    def test_delete_unlinks_email_events_and_removes_subscriber(self, app, db):
        with app.app_context():
            sub = DailyBriefSubscriber(email='del_brief@example.com', status='active')
            db.session.add(sub)
            db.session.commit()
            _record_brief_event(db, sub)
            event_id = EmailEvent.query.filter_by(brief_subscriber_id=sub.id).first().id

            assert delete_brief_subscriber(sub.id) is True
            db.session.commit()

            assert db.session.get(DailyBriefSubscriber, sub.id) is None
            event = db.session.get(EmailEvent, event_id)
            assert event is not None
            assert event.brief_subscriber_id is None
            assert event.recipient_email == 'del_brief@example.com'

    def test_bulk_delete_handles_multiple_with_events(self, app, db):
        with app.app_context():
            a = DailyBriefSubscriber(email='bulk_a@example.com', status='active')
            b = DailyBriefSubscriber(email='bulk_b@example.com', status='active')
            db.session.add_all([a, b])
            db.session.commit()
            _record_brief_event(db, a)
            _record_brief_event(db, b)

            removed = delete_brief_subscribers_bulk([a.id, b.id])
            db.session.commit()

            assert removed == 2
            assert EmailEvent.query.filter(
                EmailEvent.brief_subscriber_id.isnot(None)
            ).count() == 0
            assert DailyBriefSubscriber.query.count() == 0

    def test_unlink_only_leaves_subscriber(self, app, db):
        with app.app_context():
            sub = DailyBriefSubscriber(email='unlink_only@example.com', status='active')
            db.session.add(sub)
            db.session.commit()
            _record_brief_event(db, sub)

            count = unlink_email_events_for_brief_subscribers([sub.id])
            db.session.commit()

            assert count == 1
            assert db.session.get(DailyBriefSubscriber, sub.id) is not None
            assert EmailEvent.query.filter_by(brief_subscriber_id=sub.id).count() == 0


class TestQuestionSubscriberDelete:
    def test_delete_unlinks_email_events_and_removes_subscriber(self, app, db):
        with app.app_context():
            sub = DailyQuestionSubscriber(email='del_dq@example.com', is_active=True)
            db.session.add(sub)
            db.session.commit()
            _record_question_event(db, sub)
            event_id = EmailEvent.query.filter_by(question_subscriber_id=sub.id).first().id

            assert delete_question_subscriber(sub.id) is True
            db.session.commit()

            assert db.session.get(DailyQuestionSubscriber, sub.id) is None
            event = db.session.get(EmailEvent, event_id)
            assert event.question_subscriber_id is None

    def test_bulk_delete_with_mixed_ids_only_deletes_existing(self, app, db):
        with app.app_context():
            sub = DailyQuestionSubscriber(email='bulk_dq@example.com', is_active=True)
            db.session.add(sub)
            db.session.commit()
            _record_question_event(db, sub)
            sub_id = sub.id

            removed = delete_question_subscribers_bulk([sub_id, 99999])
            db.session.commit()

            assert removed == 1
            assert EmailEvent.query.filter_by(question_subscriber_id=sub_id).count() == 0

    def test_delete_missing_returns_false(self, app, db):
        with app.app_context():
            assert delete_question_subscriber(424242) is False
