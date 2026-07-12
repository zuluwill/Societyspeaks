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
