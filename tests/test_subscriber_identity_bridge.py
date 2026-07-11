"""Email-subscriber ↔ anonymous-visitor identity bridge.

The product is intentionally anonymous-first: most participants never sign
up. These tests lock in the measurement bridge that joins a subscriber (email)
to a session fingerprint / PostHog id (site) — the join that made
"did Tuesday's email lead to any participation?" unanswerable before.
"""

from flask import Response

from app.lib.subscriber_identity import (
    SUBSCRIBER_REF_COOKIE,
    link_subscriber_identity_from_request,
    read_subscriber_ref,
    record_identity_link,
    set_subscriber_ref_cookie,
)
from app.models.email import SubscriberIdentityLink
from app.models import DailyQuestionSubscriber


def _make_subscriber(db):
    sub = DailyQuestionSubscriber(email='bridge@example.com')
    db.session.add(sub)
    db.session.commit()
    return sub


def _cookie_value(app, question_subscriber_id):
    """Produce a signed cookie value by round-tripping through the setter."""
    with app.test_request_context('/'):
        resp = Response()
        set_subscriber_ref_cookie(resp, question_subscriber_id=question_subscriber_id)
        header = resp.headers.get('Set-Cookie', '')
    assert SUBSCRIBER_REF_COOKIE in header
    return header.split(f'{SUBSCRIBER_REF_COOKIE}=', 1)[1].split(';', 1)[0]


def test_cookie_round_trip_and_tamper_rejection(app):
    value = _cookie_value(app, question_subscriber_id=42)

    with app.test_request_context(
        '/', environ_base={'HTTP_COOKIE': f'{SUBSCRIBER_REF_COOKIE}={value}'}
    ):
        assert read_subscriber_ref() == {'q': 42}

    # Tampered signature must be rejected, not trusted.
    with app.test_request_context(
        '/', environ_base={'HTTP_COOKIE': f'{SUBSCRIBER_REF_COOKIE}={value}x'}
    ):
        assert read_subscriber_ref() is None

    # Absent cookie: no ref.
    with app.test_request_context('/'):
        assert read_subscriber_ref() is None


def test_record_identity_link_upserts_and_requires_both_sides(app, db):
    with app.app_context():
        sub = _make_subscriber(db)

        # Needs a subscriber ref AND a visitor identity — else no row.
        record_identity_link(source='vote', session_fingerprint='fp-1')
        record_identity_link(source='vote', question_subscriber_id=sub.id)
        assert SubscriberIdentityLink.query.count() == 0

        record_identity_link(
            source='vote',
            question_subscriber_id=sub.id,
            session_fingerprint='fp-1',
        )
        assert SubscriberIdentityLink.query.count() == 1
        first_seen = SubscriberIdentityLink.query.one().last_seen_at

        # Same identity pair again: same row, refreshed last_seen.
        record_identity_link(
            source='vote',
            question_subscriber_id=sub.id,
            session_fingerprint='fp-1',
        )
        row = SubscriberIdentityLink.query.one()
        assert row.last_seen_at >= first_seen

        # A different fingerprint is a new link (new device/browser).
        record_identity_link(
            source='vote',
            question_subscriber_id=sub.id,
            session_fingerprint='fp-2',
        )
        assert SubscriberIdentityLink.query.count() == 2


def test_participation_links_only_visitors_who_came_from_email(app, db):
    with app.app_context():
        sub = _make_subscriber(db)
        value = _cookie_value(app, question_subscriber_id=sub.id)

        # No cookie (organic visitor): participation records nothing.
        with app.test_request_context('/'):
            link_subscriber_identity_from_request(
                source='vote', session_fingerprint='fp-organic'
            )
        assert SubscriberIdentityLink.query.count() == 0

        # Email-acquired visitor: participation joins subscriber to fingerprint.
        with app.test_request_context(
            '/', environ_base={'HTTP_COOKIE': f'{SUBSCRIBER_REF_COOKIE}={value}'}
        ):
            link_subscriber_identity_from_request(
                source='vote', session_fingerprint='fp-email'
            )
        row = SubscriberIdentityLink.query.one()
        assert row.question_subscriber_id == sub.id
        assert row.session_fingerprint == 'fp-email'
        assert row.source == 'vote'


def test_cookie_attributes_are_hardened(app):
    with app.test_request_context('/'):
        resp = Response()
        set_subscriber_ref_cookie(resp, brief_subscriber_id=7)
        header = resp.headers.get('Set-Cookie', '')
    assert 'HttpOnly' in header
    assert 'SameSite=Lax' in header
    assert 'Max-Age=15552000' in header  # 180 days
