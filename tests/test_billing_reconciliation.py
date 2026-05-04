"""Stripe briefing subscription batch reconciliation."""

import pytest
import stripe
from werkzeug.security import generate_password_hash


class TestBriefingReconciliationBatch:
    def test_syncs_stripe_row_and_uses_flush_only(self, app, db, monkeypatch):
        from app.models import User, Subscription, PricingPlan
        from app.billing import reconciliation as recon

        monkeypatch.setattr(recon, '_redis_cursor_get', lambda: 0)
        monkeypatch.setattr(recon, '_redis_cursor_set', lambda _pk: None)

        sync_calls = []

        def fake_sync(stripe_sub, user_id=None, org_id=None, *, commit=True):
            sync_calls.append(commit)

        monkeypatch.setattr(recon, 'sync_subscription_from_stripe', fake_sync)
        monkeypatch.setattr(
            recon,
            '_stripe_call',
            lambda fn, sub_id, **kwargs: {'id': sub_id, 'status': 'active', 'customer': 'cus_r'},
        )

        with app.app_context():
            plan = PricingPlan(code='starter_rec', name='Starter', price_monthly=499)
            db.session.add(plan)
            db.session.flush()
            user = User(
                username='rec_u',
                email='rec_u@example.com',
                password=generate_password_hash('x'),
            )
            db.session.add(user)
            db.session.flush()
            sub = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                stripe_subscription_id='sub_rec_test',
                stripe_customer_id='cus_r',
                status='trialing',
            )
            db.session.add(sub)
            db.session.commit()

            app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
            app.config['STRIPE_BRIEFING_RECONCILE_BATCH_SIZE'] = 50
            app.config['STRIPE_BRIEFING_RECONCILE_MAX_PER_RUN'] = 10

            stats = recon.reconcile_briefing_subscriptions_batch()

        assert stats['examined'] == 1
        assert stats['synced'] == 1
        assert sync_calls == [False]

    def test_marks_missing_stripe_subscription_canceled(self, app, db, monkeypatch):
        from app.models import User, Subscription, PricingPlan
        from app.billing import reconciliation as recon

        monkeypatch.setattr(recon, '_redis_cursor_get', lambda: 0)
        monkeypatch.setattr(recon, '_redis_cursor_set', lambda _pk: None)

        def boom(fn, sub_id, **kwargs):
            raise stripe.error.InvalidRequestError(
                message='No such subscription: xxx',
                param=None,
                code='resource_missing',
            )

        monkeypatch.setattr(recon, '_stripe_call', boom)

        with app.app_context():
            plan = PricingPlan(code='starter_rec2', name='Starter', price_monthly=499)
            db.session.add(plan)
            db.session.flush()
            user = User(
                username='rec_u2',
                email='rec_u2@example.com',
                password=generate_password_hash('x'),
            )
            db.session.add(user)
            db.session.flush()
            sub = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                stripe_subscription_id='sub_deleted',
                stripe_customer_id='cus_r2',
                status='active',
            )
            db.session.add(sub)
            db.session.commit()
            sub_pk = sub.id

            app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
            app.config['STRIPE_BRIEFING_RECONCILE_MAX_PER_RUN'] = 10

            stats = recon.reconcile_briefing_subscriptions_batch()

            row = db.session.get(Subscription, sub_pk)

        assert stats['marked_canceled'] == 1
        assert row.status == 'canceled'
        assert row.canceled_at is not None

    def test_aborts_in_production_when_redis_unavailable(self, app, db, monkeypatch):
        from app.billing import reconciliation as recon

        monkeypatch.setattr(recon, '_production_requires_redis_cursor', lambda _cfg: True)
        monkeypatch.setattr(recon, '_redis_client_available', lambda: False)

        with app.app_context():
            app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'

            stats = recon.reconcile_briefing_subscriptions_batch()

        assert stats == {'skipped': True, 'reason': 'redis_required'}
