"""Resend webhook event recording: which event types are authoritative where.

Sends and (tracked-link) clicks are recorded first-party by the app — those
rows carry no resend_email_id, so webhook dedup cannot match them. The webhook
is authoritative only for what the app cannot see itself: delivered, opened,
bounced, complained. These tests lock that split in before the webhook is
re-enabled (dead since 2026-01-19; see docs/analysis/phase-a-data-foundation.md).
"""

from app.lib.email_analytics import EmailAnalytics
from app.models.email import EmailEvent


def _payload(event_type, email='sub@example.com', email_id='re_test_1', **data):
    return {
        'type': event_type,
        'data': {'to': [email], 'email_id': email_id, 'subject': 'Test', **data},
    }


def test_webhook_sent_is_skipped_by_default(app, db):
    """email.sent must be ignored: the app already records every send
    first-party, and recording both would double-count ~5k sends/day."""
    with app.app_context():
        assert app.config['EMAIL_ANALYTICS_RECORD_RESEND_WEBHOOK_SENDS'] is False
        result = EmailAnalytics.record_from_webhook(_payload('email.sent'))
        assert result is None
        assert EmailEvent.query.filter_by(event_type='sent').count() == 0


def test_webhook_sent_recorded_when_explicitly_enabled(app, db):
    with app.app_context():
        app.config['EMAIL_ANALYTICS_RECORD_RESEND_WEBHOOK_SENDS'] = True
        try:
            result = EmailAnalytics.record_from_webhook(_payload('email.sent'))
            assert result is not None
            assert result.event_type == 'sent'
        finally:
            app.config['EMAIL_ANALYTICS_RECORD_RESEND_WEBHOOK_SENDS'] = False


def test_webhook_opened_and_delivered_are_recorded(app, db):
    """opened/delivered exist ONLY as webhook events — they must persist."""
    with app.app_context():
        opened = EmailAnalytics.record_from_webhook(_payload('email.opened'))
        delivered = EmailAnalytics.record_from_webhook(
            _payload('email.delivered', email_id='re_test_2')
        )
        assert opened is not None and opened.event_type == 'opened'
        assert delivered is not None and delivered.event_type == 'delivered'


def test_webhook_opened_is_idempotent_per_email(app, db):
    """Svix retries must not double-record the same open."""
    with app.app_context():
        first = EmailAnalytics.record_from_webhook(_payload('email.opened'))
        second = EmailAnalytics.record_from_webhook(_payload('email.opened'))
        assert first is not None and second is not None
        assert first.id == second.id
        assert EmailEvent.query.filter_by(event_type='opened').count() == 1


def test_webhook_click_on_first_party_tracked_link_is_skipped(app, db):
    """Clicks routed through /brief/track/click are recorded by that endpoint;
    the webhook copy of the same click must be dropped."""
    with app.app_context():
        result = EmailAnalytics.record_from_webhook(
            _payload(
                'email.clicked',
                click={'link': 'https://societyspeaks.io/brief/track/click/1?url=x'},
            )
        )
        assert result is None
        assert EmailEvent.query.filter_by(event_type='clicked').count() == 0


def test_webhook_events_carry_was_created_flag(app, db):
    """Counter updates key off was_created: fresh events True, svix-retry
    duplicates False — otherwise retries inflate per-subscriber open counts."""
    with app.app_context():
        first = EmailAnalytics.record_from_webhook(_payload('email.opened'))
        assert first.was_created is True  # read immediately, as the webhook route does
        second = EmailAnalytics.record_from_webhook(_payload('email.opened'))
        assert second.was_created is False


def test_resend_webhook_fails_closed_without_secret(app, client, monkeypatch):
    """Production must reject unverified webhooks when the secret is unset —
    never fall through to process the payload."""
    monkeypatch.delenv('RESEND_WEBHOOK_SECRET', raising=False)
    was_testing, was_debug = app.testing, app.debug
    app.testing = False
    app.debug = False
    try:
        resp = client.post(
            '/brief/webhooks/resend',
            json={'type': 'email.delivered', 'data': {'to': ['a@b.c']}},
            headers={'Content-Type': 'application/json'},
        )
        assert resp.status_code == 503
        assert resp.get_json()['error'] == 'webhook secret not configured'
    finally:
        app.testing = was_testing
        app.debug = was_debug


def test_unsubscribe_routes_are_csrf_exempt(app):
    """RFC 8058 one-click unsubscribe POSTs come from mail clients with no
    CSRF token; Gmail bulk-sender compliance requires them to succeed."""
    from app import csrf
    from app.brief.routes import unsubscribe as brief_unsub
    from app.briefing.routes import unsubscribe as briefing_unsub
    from app.daily.routes import unsubscribe as daily_unsub
    from app.game.routes import reminders_unsubscribe
    from app.programmes.routes import journey_reminder_unsubscribe

    for view in (
        brief_unsub,
        daily_unsub,
        briefing_unsub,
        reminders_unsubscribe,
        journey_reminder_unsubscribe,
    ):
        assert f'{view.__module__}.{view.__name__}' in csrf._exempt_views


def test_resend_webhook_route_is_csrf_exempt(app):
    """Resend/svix POSTs carry no CSRF token. Without the exemption every
    webhook delivery 400s at the framework and delivered/opened/bounced/
    complained data silently stops — the suite can't catch this via the test
    client because conftest disables CSRF globally, so assert the exemption
    registration directly."""
    from app import csrf
    from app.brief.routes import resend_webhook

    dest = f'{resend_webhook.__module__}.{resend_webhook.__name__}'
    assert dest in csrf._exempt_views


def test_suppressed_event_removes_subscriber_from_active_pool(app, db):
    """email.suppressed means Resend will never deliver to this address —
    leaving it 'active' distorts every rate computed on the list."""
    from app.models import DailyBriefSubscriber

    with app.app_context():
        sub = DailyBriefSubscriber(email='suppressed@example.com', status='active')
        db.session.add(sub)
        db.session.commit()

        result = EmailAnalytics.record_from_webhook(
            _payload('email.suppressed', email='suppressed@example.com')
        )
        assert result is not None and result.event_type == 'suppressed'

        db.session.expire_all()
        refreshed = DailyBriefSubscriber.query.filter_by(
            email='suppressed@example.com'
        ).first()
        assert refreshed.status == 'suppressed'


def test_classify_bounce_type_accepts_resend_and_legacy_labels():
    assert EmailAnalytics.classify_bounce_type('Permanent') == 'hard'
    assert EmailAnalytics.classify_bounce_type('hard') == 'hard'
    assert EmailAnalytics.classify_bounce_type('Transient') == 'soft'
    assert EmailAnalytics.classify_bounce_type('Temporary') == 'soft'
    assert EmailAnalytics.classify_bounce_type('Undetermined') == 'soft'
    assert EmailAnalytics.classify_bounce_type('soft') == 'soft'
    assert EmailAnalytics.classify_bounce_type(None) == 'soft'


def test_permanent_bounce_removes_subscriber_from_active_pool(app, db):
    from app.models import DailyBriefSubscriber

    with app.app_context():
        sub = DailyBriefSubscriber(email='hard@example.com', status='active')
        db.session.add(sub)
        db.session.commit()

        result = EmailAnalytics.record_from_webhook(
            _payload(
                'email.bounced',
                email='hard@example.com',
                bounce={'type': 'Permanent'},
            )
        )
        assert result is not None and result.event_type == 'bounced'

        db.session.expire_all()
        refreshed = DailyBriefSubscriber.query.filter_by(email='hard@example.com').first()
        assert refreshed.status == 'bounced'


def test_one_transient_bounce_does_not_suppress(app, db):
    from app.models import DailyBriefSubscriber

    with app.app_context():
        sub = DailyBriefSubscriber(email='soft@example.com', status='active')
        db.session.add(sub)
        db.session.commit()

        EmailAnalytics.record_from_webhook(
            _payload(
                'email.bounced',
                email='soft@example.com',
                bounce={'type': 'Transient'},
            )
        )

        db.session.expire_all()
        refreshed = DailyBriefSubscriber.query.filter_by(email='soft@example.com').first()
        assert refreshed.status == 'active'


def test_recipient_email_from_webhook_accepts_resend_shapes():
    from app.lib.email_analytics import recipient_email_from_webhook

    assert recipient_email_from_webhook({'to': ['Ada <ada@example.com>']}) == 'ada@example.com'
    assert recipient_email_from_webhook({'to': 'plain@example.com'}) == 'plain@example.com'
    assert recipient_email_from_webhook({'to': [{'email': 'obj@example.com'}]}) == 'obj@example.com'
    assert recipient_email_from_webhook({'to': []}) is None


def test_mixed_case_permanent_bounce_still_suppresses(app, db):
    from app.models import DailyBriefSubscriber

    with app.app_context():
        sub = DailyBriefSubscriber(email='Case.Person@example.com', status='active')
        db.session.add(sub)
        db.session.commit()

        EmailAnalytics.record_from_webhook(
            _payload(
                'email.bounced',
                email='case.person@example.com',
                bounce={'type': 'Permanent'},
            )
        )
        db.session.expire_all()
        refreshed = DailyBriefSubscriber.query.filter_by(
            email='Case.Person@example.com'
        ).first()
        assert refreshed.status == 'bounced'


def test_bounce_does_not_overwrite_unsubscribed(app, db):
    from app.models import DailyBriefSubscriber

    with app.app_context():
        sub = DailyBriefSubscriber(email='unsub@example.com', status='unsubscribed')
        db.session.add(sub)
        db.session.commit()

        EmailAnalytics.record_from_webhook(
            _payload(
                'email.bounced',
                email='unsub@example.com',
                bounce={'type': 'Permanent'},
            )
        )
        db.session.expire_all()
        refreshed = DailyBriefSubscriber.query.filter_by(email='unsub@example.com').first()
        assert refreshed.status == 'unsubscribed'


def test_bounce_pauses_game_reminder(app, db):
    from app.models import DailyBriefSubscriber, GameReminderSubscription

    with app.app_context():
        sub = DailyBriefSubscriber(email='both@example.com', status='active')
        reminder = GameReminderSubscription(email='both@example.com')
        db.session.add_all([sub, reminder])
        db.session.commit()

        EmailAnalytics.record_from_webhook(
            _payload(
                'email.bounced',
                email='both@example.com',
                bounce={'type': 'Permanent'},
            )
        )
        db.session.expire_all()
        paused = GameReminderSubscription.query.filter_by(email='both@example.com').first()
        assert paused.unsubscribed_at is not None
        assert paused.unsubscribe_reason == 'bounce'


def test_process_subscription_refuses_bounced_address(app, db):
    from app.brief.subscription import process_subscription
    from app.models import DailyBriefSubscriber

    with app.app_context():
        sub = DailyBriefSubscriber(email='dead@example.com', status='bounced')
        db.session.add(sub)
        db.session.commit()
        with app.test_request_context('/brief/subscribe'):
            result = process_subscription('dead@example.com')
        assert result['status'] == 'undeliverable'
        db.session.expire_all()
        assert DailyBriefSubscriber.query.filter_by(email='dead@example.com').first().status == 'bounced'


def test_three_transient_bounces_suppress(app, db):
    from app.models import DailyBriefSubscriber

    with app.app_context():
        sub = DailyBriefSubscriber(email='chronic@example.com', status='active')
        db.session.add(sub)
        db.session.commit()

        for i in range(3):
            EmailAnalytics.record_from_webhook(
                _payload(
                    'email.bounced',
                    email='chronic@example.com',
                    email_id=f're_soft_{i}',
                    bounce={'type': 'Transient'},
                )
            )

        db.session.expire_all()
        refreshed = DailyBriefSubscriber.query.filter_by(
            email='chronic@example.com'
        ).first()
        assert refreshed.status == 'bounced'


def test_discussion_mail_skipped_when_brief_bounced(app, db):
    from app.email_utils import user_accepts_discussion_notification_email
    from app.models import DailyBriefSubscriber, User

    with app.app_context():
        user = User(email='host@example.com', username='hostbounce')
        user.set_password('x')
        db.session.add(user)
        db.session.flush()
        db.session.add(DailyBriefSubscriber(email='host@example.com', status='bounced'))
        db.session.commit()
        assert user_accepts_discussion_notification_email(user, 'new_participant') is False
