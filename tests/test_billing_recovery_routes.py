"""Billing URLs used by Stripe Revenue recovery and transactional email."""

from datetime import datetime, timezone

import pytest
from types import SimpleNamespace

from app.billing.routes import handle_payment_failed


@pytest.fixture
def client(app, db):
    return app.test_client()


class TestStripeRecoveryCardUpdate:
    def test_anonymous_redirects_to_login_with_next_portal(self, client):
        resp = client.get('/billing/card-update', follow_redirects=False)
        assert resp.status_code == 302
        loc = resp.headers.get('Location', '')
        assert '/auth/login' in loc
        assert 'next=%2Fbilling%2Fportal' in loc or 'next=/billing/portal' in loc

    def test_authenticated_redirects_to_portal_session(self, app, client, db, monkeypatch):
        from app.models import User
        from werkzeug.security import generate_password_hash

        monkeypatch.setattr(
            'app.billing.routes.create_portal_session',
            lambda user: SimpleNamespace(url='https://billing.stripe.test/session'),
        )

        with app.app_context():
            u = User(
                username='recoverytest',
                email='recoverytest@example.com',
                password=generate_password_hash('pw', method='pbkdf2:sha256'),
            )
            u.stripe_customer_id = 'cus_test_recovery'
            db.session.add(u)
            db.session.commit()

        login = client.post(
            '/auth/login',
            data={'email': 'recoverytest@example.com', 'password': 'pw'},
            follow_redirects=False,
        )
        assert login.status_code == 302

        hop = client.get('/billing/card-update', follow_redirects=False)
        assert hop.status_code == 302
        assert hop.headers['Location'].endswith('/billing/portal')

        resp = client.get('/billing/portal', follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers['Location'] == 'https://billing.stripe.test/session'


class TestHandlePaymentFailed:
    """invoice.payment_failed reconciles from Stripe (ordering-safe)."""

    @pytest.fixture
    def billing_user_with_sub(self, db):
        from app.models import User, Subscription, PricingPlan
        from werkzeug.security import generate_password_hash

        plan = PricingPlan(code='starter_pf', name='Starter', price_monthly=499)
        db.session.add(plan)
        db.session.flush()
        user = User(
            username='payfailuser',
            email='payfailuser@example.com',
            password=generate_password_hash('pw', method='pbkdf2:sha256'),
        )
        db.session.add(user)
        db.session.flush()
        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            stripe_subscription_id='sub_payfail_unit',
            stripe_customer_id='cus_pf_unit',
            status='past_due',
        )
        db.session.add(sub)
        db.session.commit()
        return {'user_id': user.id, 'sub_id': sub.id, 'stripe_sub_id': 'sub_payfail_unit'}

    def test_skips_posthog_when_stripe_subscription_already_active(
        self, db, monkeypatch, billing_user_with_sub
    ):
        captured = []
        monkeypatch.setattr(
            'app.billing.routes._track_posthog',
            lambda *args, **kwargs: captured.append((args, kwargs)),
        )

        def fake_call(fn, sub_id, **kwargs):
            return {'id': sub_id, 'status': 'active'}

        def fake_sync(stripe_sub, user_id=None, org_id=None):
            from app.models import Subscription

            sub = Subscription.query.filter_by(stripe_subscription_id=stripe_sub['id']).first()
            sub.status = stripe_sub['status']
            db.session.commit()
            return sub

        monkeypatch.setattr('app.billing.routes._stripe_call', fake_call)
        monkeypatch.setattr('app.billing.routes.sync_subscription_from_stripe', fake_sync)

        handle_payment_failed(
            {'subscription': billing_user_with_sub['stripe_sub_id'], 'attempt_count': 1}
        )

        from app.models import Subscription

        sub = db.session.get(Subscription, billing_user_with_sub['sub_id'])
        assert sub.status == 'active'
        assert captured == []

    def test_tracks_posthog_when_subscription_past_due(self, db, monkeypatch, billing_user_with_sub):
        captured = []
        monkeypatch.setattr(
            'app.billing.routes._track_posthog',
            lambda event, user_id, props=None: captured.append((event, user_id, props)),
        )

        def fake_call(fn, sub_id, **kwargs):
            return {'id': sub_id, 'status': 'past_due'}

        def fake_sync(stripe_sub, user_id=None, org_id=None):
            from app.models import Subscription

            sub = Subscription.query.filter_by(stripe_subscription_id=stripe_sub['id']).first()
            sub.status = stripe_sub['status']
            db.session.commit()
            return sub

        monkeypatch.setattr('app.billing.routes._stripe_call', fake_call)
        monkeypatch.setattr('app.billing.routes.sync_subscription_from_stripe', fake_sync)

        next_ts = 1715000000
        handle_payment_failed(
            {
                'subscription': billing_user_with_sub['stripe_sub_id'],
                'attempt_count': 2,
                'next_payment_attempt': next_ts,
            }
        )

        assert len(captured) == 1
        assert captured[0][0] == 'paid_briefing_payment_failed'
        assert captured[0][1] == billing_user_with_sub['user_id']
        assert captured[0][2]['attempt_count'] == 2
        assert captured[0][2]['next_retry'] == datetime.fromtimestamp(
            next_ts, tz=timezone.utc
        ).strftime('%Y-%m-%d %H:%M UTC')
