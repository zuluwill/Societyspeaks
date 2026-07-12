"""Tests for the stable unsubscribe_token pattern.

The headline weekend feature: email unsubscribe links must keep working even
after ``magic_token`` rotates (the daily-question batch rotates it before every
send; the brief rotates it when a user clicks an expired magic link). These
tests lock in three guarantees:

1. ``ensure_unsubscribe_token()`` is set-once / idempotent on all three models.
2. The unsubscribe routes look up ``unsubscribe_token`` first and fall back to
   ``magic_token`` for links sent before the column existed.
3. RFC 8058 one-click ``POST`` always returns an empty ``200`` and never errors
   to the mail client — including for unknown tokens.

See adr / .agents/memory/brief-unsubscribe-token.md for the rationale.
"""

import pytest

from app.models import (
    BriefRecipient,
    Briefing,
    DailyBriefSubscriber,
    DailyQuestionSubscriber,
)


@pytest.fixture
def client(app, db):
    return app.test_client()


def _make_brief_subscriber(db, email='brief@example.com', **kwargs):
    kwargs.setdefault('status', 'active')
    sub = DailyBriefSubscriber(email=email, **kwargs)
    sub.generate_magic_token()
    sub.ensure_unsubscribe_token()
    db.session.add(sub)
    db.session.commit()
    return sub


def _make_question_subscriber(db, email='dq@example.com', **kwargs):
    sub = DailyQuestionSubscriber(email=email, is_active=True, **kwargs)
    sub.generate_magic_token()
    sub.ensure_unsubscribe_token()
    db.session.add(sub)
    db.session.commit()
    return sub


def _make_brief_recipient(db, email='recipient@example.com'):
    briefing = Briefing(owner_type='user', owner_id=1, name='Test Briefing')
    db.session.add(briefing)
    db.session.commit()
    recipient = BriefRecipient(briefing_id=briefing.id, email=email, status='active')
    recipient.generate_magic_token()
    recipient.ensure_unsubscribe_token()
    db.session.add(recipient)
    db.session.commit()
    return briefing, recipient


# ---------------------------------------------------------------------------
# Model: ensure_unsubscribe_token() is set-once and idempotent
# ---------------------------------------------------------------------------

class TestEnsureUnsubscribeTokenIdempotency:
    def test_brief_subscriber_sets_once(self, app, db):
        with app.app_context():
            sub = DailyBriefSubscriber(email='once_brief@example.com', status='active')
            assert sub.unsubscribe_token is None
            token = sub.ensure_unsubscribe_token()
            assert token
            # Second call must NOT rotate the token.
            assert sub.ensure_unsubscribe_token() == token
            assert sub.unsubscribe_token == token

    def test_question_subscriber_sets_once(self, app, db):
        with app.app_context():
            sub = DailyQuestionSubscriber(email='once_dq@example.com', is_active=True)
            assert sub.unsubscribe_token is None
            token = sub.ensure_unsubscribe_token()
            assert token
            assert sub.ensure_unsubscribe_token() == token

    def test_brief_recipient_sets_once(self, app, db):
        with app.app_context():
            recipient = BriefRecipient(briefing_id=1, email='once_recip@example.com')
            assert recipient.unsubscribe_token is None
            token = recipient.ensure_unsubscribe_token()
            assert token
            assert recipient.ensure_unsubscribe_token() == token

    def test_unsubscribe_token_independent_of_magic_token(self, app, db):
        """The whole point: unsubscribe_token never rotates with magic_token."""
        with app.app_context():
            sub = DailyQuestionSubscriber(email='stable_dq@example.com', is_active=True)
            sub.generate_magic_token()
            stable = sub.ensure_unsubscribe_token()
            assert stable != sub.magic_token

            # Rotate magic_token several times (mimics daily batch sends).
            for _ in range(3):
                sub.generate_magic_token()
            assert sub.unsubscribe_token == stable


# ---------------------------------------------------------------------------
# Brief unsubscribe route
# ---------------------------------------------------------------------------

class TestBriefUnsubscribe:
    def test_get_shows_confirm_page_without_unsubscribing(self, app, db, client):
        """GET must never change state: unsubscribe links are prefetched by
        corporate mail scanners, which would silently unsubscribe recipients."""
        with app.app_context():
            sub = _make_brief_subscriber(db)
            token = sub.unsubscribe_token

        resp = client.get(f'/brief/unsubscribe/{token}')
        assert resp.status_code == 200
        assert b'Confirm Unsubscribe' in resp.data

        with app.app_context():
            refreshed = DailyBriefSubscriber.query.filter_by(email='brief@example.com').first()
            assert refreshed.status == 'active'

    def test_confirm_form_post_unsubscribes(self, app, db, client):
        with app.app_context():
            sub = _make_brief_subscriber(db)
            token = sub.unsubscribe_token

        resp = client.post(f'/brief/unsubscribe/{token}', data={'confirm': '1'})
        assert resp.status_code == 200

        with app.app_context():
            refreshed = DailyBriefSubscriber.query.filter_by(email='brief@example.com').first()
            assert refreshed.status == 'unsubscribed'
            assert refreshed.unsubscribed_at is not None

    def test_falls_back_to_magic_token_for_legacy_links(self, app, db, client):
        """Links sent before the column existed carry the magic_token."""
        with app.app_context():
            sub = DailyBriefSubscriber(email='legacy_brief@example.com', status='active')
            sub.generate_magic_token()  # no unsubscribe_token (pre-migration row)
            db.session.add(sub)
            db.session.commit()
            magic = sub.magic_token

        resp = client.post(f'/brief/unsubscribe/{magic}', data={'confirm': '1'})
        assert resp.status_code == 200
        with app.app_context():
            refreshed = DailyBriefSubscriber.query.filter_by(email='legacy_brief@example.com').first()
            assert refreshed.status == 'unsubscribed'

    def test_stable_token_survives_magic_token_rotation(self, app, db, client):
        """Regression: the bug this feature fixes."""
        with app.app_context():
            sub = _make_brief_subscriber(db, email='rotate_brief@example.com')
            token = sub.unsubscribe_token
            # Simulate magic-link rotation after the email was sent.
            sub.generate_magic_token()
            db.session.commit()
            assert sub.unsubscribe_token == token

        resp = client.post(f'/brief/unsubscribe/{token}', data={'confirm': '1'})
        assert resp.status_code == 200
        with app.app_context():
            refreshed = DailyBriefSubscriber.query.filter_by(email='rotate_brief@example.com').first()
            assert refreshed.status == 'unsubscribed'

    def test_one_click_post_returns_empty_200(self, app, db, client):
        with app.app_context():
            sub = _make_brief_subscriber(db, email='oneclick_brief@example.com')
            token = sub.unsubscribe_token

        resp = client.post(f'/brief/unsubscribe/{token}')
        assert resp.status_code == 200
        assert resp.data == b''
        with app.app_context():
            refreshed = DailyBriefSubscriber.query.filter_by(email='oneclick_brief@example.com').first()
            assert refreshed.status == 'unsubscribed'

    def test_post_unknown_token_silently_accepts(self, app, db, client):
        """RFC 8058: never surface an error to the mail client."""
        resp = client.post('/brief/unsubscribe/does-not-exist')
        assert resp.status_code == 200
        assert resp.data == b''

    def test_get_unknown_token_redirects(self, app, db, client):
        resp = client.get('/brief/unsubscribe/does-not-exist', follow_redirects=False)
        assert resp.status_code == 302

    def test_already_unsubscribed_is_idempotent(self, app, db, client):
        with app.app_context():
            sub = _make_brief_subscriber(db, email='idem_brief@example.com', status='unsubscribed')
            token = sub.unsubscribe_token

        # Human GET still shows a page; one-click POST still returns 200.
        assert client.get(f'/brief/unsubscribe/{token}').status_code == 200
        post_resp = client.post(f'/brief/unsubscribe/{token}')
        assert post_resp.status_code == 200
        assert post_resp.data == b''


# ---------------------------------------------------------------------------
# Daily question unsubscribe route
# ---------------------------------------------------------------------------

class TestDailyQuestionUnsubscribe:
    def test_get_active_shows_confirm_without_unsubscribing(self, app, db, client):
        with app.app_context():
            sub = _make_question_subscriber(db)
            token = sub.unsubscribe_token

        resp = client.get(f'/daily/unsubscribe/{token}')
        assert resp.status_code == 200
        with app.app_context():
            refreshed = DailyQuestionSubscriber.query.filter_by(email='dq@example.com').first()
            # GET only shows the confirmation form; it must not unsubscribe.
            assert refreshed.is_active is True

    def test_one_click_post_unsubscribes_empty_200(self, app, db, client):
        with app.app_context():
            sub = _make_question_subscriber(db, email='oneclick_dq@example.com')
            token = sub.unsubscribe_token

        resp = client.post(
            f'/daily/unsubscribe/{token}',
            data={'List-Unsubscribe': 'One-Click'},
        )
        assert resp.status_code == 200
        assert resp.data == b''
        with app.app_context():
            refreshed = DailyQuestionSubscriber.query.filter_by(email='oneclick_dq@example.com').first()
            assert refreshed.is_active is False

    def test_form_post_with_reason_unsubscribes(self, app, db, client):
        with app.app_context():
            sub = _make_question_subscriber(db, email='reason_dq@example.com')
            token = sub.unsubscribe_token

        resp = client.post(
            f'/daily/unsubscribe/{token}',
            data={'reason': 'too_frequent'},
        )
        assert resp.status_code == 200
        with app.app_context():
            refreshed = DailyQuestionSubscriber.query.filter_by(email='reason_dq@example.com').first()
            assert refreshed.is_active is False
            assert refreshed.unsubscribe_reason == 'too_frequent'

    def test_falls_back_to_magic_token(self, app, db, client):
        with app.app_context():
            sub = DailyQuestionSubscriber(email='legacy_dq@example.com', is_active=True)
            sub.generate_magic_token()  # pre-migration row, no unsubscribe_token
            db.session.add(sub)
            db.session.commit()
            magic = sub.magic_token

        resp = client.post(
            f'/daily/unsubscribe/{magic}',
            data={'List-Unsubscribe': 'One-Click'},
        )
        assert resp.status_code == 200
        with app.app_context():
            refreshed = DailyQuestionSubscriber.query.filter_by(email='legacy_dq@example.com').first()
            assert refreshed.is_active is False

    def test_post_unknown_token_silently_accepts(self, app, db, client):
        resp = client.post(
            '/daily/unsubscribe/nope',
            data={'List-Unsubscribe': 'One-Click'},
        )
        assert resp.status_code == 200
        assert resp.data == b''

    def test_already_unsubscribed_one_click_returns_200(self, app, db, client):
        with app.app_context():
            sub = _make_question_subscriber(db, email='idem_dq@example.com')
            sub.is_active = False
            db.session.commit()
            token = sub.unsubscribe_token

        resp = client.post(
            f'/daily/unsubscribe/{token}',
            data={'List-Unsubscribe': 'One-Click'},
        )
        assert resp.status_code == 200
        assert resp.data == b''


# ---------------------------------------------------------------------------
# Briefing (BriefRecipient) unsubscribe route
# ---------------------------------------------------------------------------

class TestBriefingUnsubscribe:
    def test_get_shows_confirm_without_unsubscribing(self, app, db, client):
        """GET must never change state: scanners prefetch unsubscribe links."""
        with app.app_context():
            briefing, recipient = _make_brief_recipient(db, email='confirm_recip@example.com')
            briefing_id = briefing.id
            token = recipient.unsubscribe_token

        resp = client.get(f'/briefings/{briefing_id}/unsubscribe/{token}')
        assert resp.status_code == 200
        assert b'Confirm Unsubscribe' in resp.data
        with app.app_context():
            refreshed = BriefRecipient.query.filter_by(briefing_id=briefing_id).first()
            assert refreshed.status == 'active'

    def test_confirm_form_post_unsubscribes(self, app, db, client):
        with app.app_context():
            briefing, recipient = _make_brief_recipient(db, email='form_recip@example.com')
            briefing_id = briefing.id
            token = recipient.unsubscribe_token

        resp = client.post(
            f'/briefings/{briefing_id}/unsubscribe/{token}',
            data={'confirm': '1'},
        )
        assert resp.status_code == 200
        assert b'Unsubscribed' in resp.data
        with app.app_context():
            refreshed = BriefRecipient.query.filter_by(briefing_id=briefing_id).first()
            assert refreshed.status == 'unsubscribed'

    def test_one_click_post_unsubscribes_empty_200(self, app, db, client):
        with app.app_context():
            briefing, recipient = _make_brief_recipient(db)
            briefing_id = briefing.id
            token = recipient.unsubscribe_token

        resp = client.post(
            f'/briefings/{briefing_id}/unsubscribe/{token}',
            data={'List-Unsubscribe': 'One-Click'},
        )
        assert resp.status_code == 200
        assert resp.data == b''
        with app.app_context():
            refreshed = BriefRecipient.query.filter_by(briefing_id=briefing_id).first()
            assert refreshed.status == 'unsubscribed'

    def test_falls_back_to_magic_token_on_confirm_post(self, app, db, client):
        with app.app_context():
            briefing = Briefing(owner_type='user', owner_id=1, name='Legacy Briefing')
            db.session.add(briefing)
            db.session.commit()
            recipient = BriefRecipient(briefing_id=briefing.id, email='legacy_recip@example.com', status='active')
            recipient.generate_magic_token()  # no unsubscribe_token
            db.session.add(recipient)
            db.session.commit()
            briefing_id = briefing.id
            magic = recipient.magic_token

        # GET shows confirm; must not unsubscribe yet
        get_resp = client.get(f'/briefings/{briefing_id}/unsubscribe/{magic}')
        assert get_resp.status_code == 200
        with app.app_context():
            assert BriefRecipient.query.filter_by(briefing_id=briefing_id).first().status == 'active'

        resp = client.post(
            f'/briefings/{briefing_id}/unsubscribe/{magic}',
            data={'confirm': '1'},
        )
        assert resp.status_code == 200
        with app.app_context():
            refreshed = BriefRecipient.query.filter_by(briefing_id=briefing_id).first()
            assert refreshed.status == 'unsubscribed'

    def test_post_unknown_token_silently_accepts(self, app, db, client):
        with app.app_context():
            briefing, _ = _make_brief_recipient(db, email='probe_recip@example.com')
            briefing_id = briefing.id

        resp = client.post(f'/briefings/{briefing_id}/unsubscribe/unknown-token')
        assert resp.status_code == 200
        assert resp.data == b''


# ---------------------------------------------------------------------------
# Journey reminder unsubscribe (RFC 8058 + prefetch-safe GET)
# ---------------------------------------------------------------------------

class TestJourneyReminderUnsubscribe:
    def _make_sub(self, db, email='journey@example.com'):
        from app.models import JourneyReminderSubscription, Programme, User, generate_slug

        u = User(username='jrs_owner', email='jrs_owner@example.com', password='pw')
        db.session.add(u)
        db.session.flush()
        programme = Programme(
            name='JRS Prog',
            slug=generate_slug('jrs-prog'),
            creator_id=u.id,
            visibility='public',
            status='active',
        )
        db.session.add(programme)
        db.session.flush()
        sub = JourneyReminderSubscription(
            programme_id=programme.id,
            email=email,
            cadence='weekly',
            timezone='UTC',
        )
        sub.generate_resume_token()
        sub.ensure_unsubscribe_token()
        db.session.add(sub)
        db.session.commit()
        return programme, sub

    def test_get_shows_confirm_without_unsubscribing(self, app, db, client):
        with app.app_context():
            programme, sub = self._make_sub(db)
            slug = programme.slug
            token = sub.unsubscribe_token

        resp = client.get(f'/programmes/{slug}/journey-reminder/unsubscribe?token={token}')
        assert resp.status_code == 200
        assert b'Stop journey reminders' in resp.data
        with app.app_context():
            from app.models import JourneyReminderSubscription
            refreshed = JourneyReminderSubscription.query.filter_by(email='journey@example.com').first()
            assert refreshed.unsubscribed_at is None

    def test_one_click_post_unsubscribes_empty_200(self, app, db, client):
        with app.app_context():
            programme, sub = self._make_sub(db, email='jrs_oneclick@example.com')
            slug = programme.slug
            token = sub.unsubscribe_token

        resp = client.post(
            f'/programmes/{slug}/journey-reminder/unsubscribe?token={token}',
            data={'List-Unsubscribe': 'One-Click'},
        )
        assert resp.status_code == 200
        assert resp.data == b''
        with app.app_context():
            from app.models import JourneyReminderSubscription
            refreshed = JourneyReminderSubscription.query.filter_by(
                email='jrs_oneclick@example.com'
            ).first()
            assert refreshed.unsubscribed_at is not None

    def test_legacy_resume_token_still_unsubscribes(self, app, db, client):
        """Emails sent before jrs004 used resume_token in the unsubscribe URL."""
        with app.app_context():
            programme, sub = self._make_sub(db, email='jrs_legacy@example.com')
            slug = programme.slug
            legacy = sub.resume_token

        resp = client.post(
            f'/programmes/{slug}/journey-reminder/unsubscribe?token={legacy}',
            data={'List-Unsubscribe': 'One-Click'},
        )
        assert resp.status_code == 200
        with app.app_context():
            from app.models import JourneyReminderSubscription
            refreshed = JourneyReminderSubscription.query.filter_by(
                email='jrs_legacy@example.com'
            ).first()
            assert refreshed.unsubscribed_at is not None

    def test_confirm_form_post_unsubscribes(self, app, db, client):
        with app.app_context():
            programme, sub = self._make_sub(db, email='jrs_form@example.com')
            slug = programme.slug
            token = sub.unsubscribe_token

        resp = client.post(
            f'/programmes/{slug}/journey-reminder/unsubscribe?token={token}',
            data={'confirm': '1', 'token': token},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        with app.app_context():
            from app.models import JourneyReminderSubscription
            refreshed = JourneyReminderSubscription.query.filter_by(
                email='jrs_form@example.com'
            ).first()
            assert refreshed.unsubscribed_at is not None

    def test_unsubscribe_token_survives_resume_rotation(self, app, db):
        with app.app_context():
            from app.models import JourneyReminderSubscription
            _, sub = self._make_sub(db, email='jrs_stable@example.com')
            stable = sub.unsubscribe_token
            sub.generate_resume_token()
            db.session.commit()
            assert sub.unsubscribe_token == stable
            assert JourneyReminderSubscription.find_by_unsubscribe_token(stable) is sub
