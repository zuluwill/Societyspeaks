"""Subscription entitlement (grace period) and checkout session binding."""

import pytest
from types import SimpleNamespace
from werkzeug.security import generate_password_hash


@pytest.fixture
def client(app, db):
    return app.test_client()


class TestGetActiveSubscriptionPastDue:
    def test_user_stripe_past_due_counts_as_entitled(self, app, db):
        from app.models import User, Subscription, PricingPlan
        from app.billing.service import get_active_subscription

        with app.app_context():
            plan = PricingPlan(code='starter_ent', name='Starter', price_monthly=499)
            db.session.add(plan)
            db.session.flush()
            user = User(
                username='pastdue_ent',
                email='pastdue_ent@example.com',
                password=generate_password_hash('x'),
            )
            user.stripe_customer_id = 'cus_ent_test'
            db.session.add(user)
            db.session.flush()
            sub = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                stripe_subscription_id='sub_past_due_ent',
                stripe_customer_id='cus_ent_test',
                status='past_due',
            )
            db.session.add(sub)
            db.session.commit()
            uid = user.id

        with app.app_context():
            user = db.session.get(User, uid)
            got = get_active_subscription(user)
            assert got is not None
            assert got.status == 'past_due'


class TestCheckoutSuccessSessionBinding:
    def test_rejects_metadata_user_mismatch(self, app, db, client, monkeypatch):
        from app.models import User

        with app.app_context():
            user = User(
                username='checkout_bind',
                email='checkout_bind@example.com',
                password=generate_password_hash('pw', method='pbkdf2:sha256'),
            )
            user.stripe_customer_id = 'cus_bind_same'
            db.session.add(user)
            db.session.commit()
            uid = user.id

        login = client.post(
            '/auth/login',
            data={'email': 'checkout_bind@example.com', 'password': 'pw'},
            follow_redirects=False,
        )
        assert login.status_code == 302

        def fake_stripe_call(fn, *args, **kwargs):
            return SimpleNamespace(
                metadata={'user_id': str(uid + 999), 'billing_interval': 'month'},
                customer='cus_bind_same',
                subscription=None,
            )

        monkeypatch.setattr('app.billing.routes._stripe_call', fake_stripe_call)

        resp = client.get('/billing/success?session_id=cs_test_bind', follow_redirects=False)
        assert resp.status_code == 302
        loc = resp.headers.get('Location', '')
        assert '/briefings/landing' in loc
