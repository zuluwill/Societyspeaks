"""
Tests for the day-45 winback eligibility logic.

Uses the shared predicates in app.lib.self_serve_trial_lifecycle so tests
cannot drift from send_self_serve_winback_job.
"""
from datetime import timedelta

from app.lib.self_serve_trial_lifecycle import self_serve_winback_eligible
from app.lib.time import utcnow_naive
from app.models import User
from app.models.billing import PricingPlan, Subscription


def _seed_plan(db):
    plan = PricingPlan(
        code='starter', name='Personal',
        price_monthly=499, price_yearly=4900,
        currency='GBP', is_organisation=False, is_active=True,
    )
    db.session.add(plan)
    db.session.flush()
    return plan


def _seed_user(db, username, email):
    u = User(username=username, email=email, password='hashed', email_verified=True)
    db.session.add(u)
    db.session.flush()
    return u


def _seed_paused_self_serve(db, plan, user, *, days_ago, source='self_serve'):
    now = utcnow_naive()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        stripe_subscription_id=None,
        status='canceled',
        billing_interval='month',
        extra_data={
            'trial_source': source,
            'paused_at': (now - timedelta(days=days_ago)).isoformat(),
        },
        canceled_at=now - timedelta(days=days_ago),
    )
    db.session.add(sub)
    db.session.flush()
    return sub


def test_winback_eligible_in_window(app, db):
    with app.app_context():
        plan = _seed_plan(db)
        user = _seed_user(db, 'alice', 'alice@example.com')
        sub = _seed_paused_self_serve(db, plan, user, days_ago=15)
        db.session.commit()
        assert self_serve_winback_eligible(sub) is True


def test_winback_skipped_when_too_recent(app, db):
    with app.app_context():
        plan = _seed_plan(db)
        user = _seed_user(db, 'bob', 'bob@example.com')
        sub = _seed_paused_self_serve(db, plan, user, days_ago=5)
        db.session.commit()
        assert self_serve_winback_eligible(sub) is False


def test_winback_skipped_when_too_old(app, db):
    with app.app_context():
        plan = _seed_plan(db)
        user = _seed_user(db, 'carol', 'carol@example.com')
        sub = _seed_paused_self_serve(db, plan, user, days_ago=60)
        db.session.commit()
        assert self_serve_winback_eligible(sub) is False


def test_winback_skipped_when_user_now_has_stripe_active(app, db):
    with app.app_context():
        plan = _seed_plan(db)
        user = _seed_user(db, 'dave', 'dave@example.com')
        paused = _seed_paused_self_serve(db, plan, user, days_ago=15)
        stripe_sub = Subscription(
            user_id=user.id, plan_id=plan.id,
            stripe_subscription_id='sub_xyz',
            status='active', billing_interval='month',
            extra_data={'trial_source': 'stripe'},
        )
        db.session.add(stripe_sub)
        db.session.commit()
        assert self_serve_winback_eligible(paused) is False


def test_winback_skipped_when_not_self_serve(app, db):
    with app.app_context():
        plan = _seed_plan(db)
        user = _seed_user(db, 'eve', 'eve@example.com')
        sub = _seed_paused_self_serve(db, plan, user, days_ago=15, source='admin')
        db.session.commit()
        assert self_serve_winback_eligible(sub) is False


def test_winback_skipped_when_paused_at_missing(app, db):
    with app.app_context():
        plan = _seed_plan(db)
        user = _seed_user(db, 'frank', 'frank@example.com')
        now = utcnow_naive()
        sub = Subscription(
            user_id=user.id, plan_id=plan.id,
            stripe_subscription_id=None,
            status='canceled',
            billing_interval='month',
            extra_data={'trial_source': 'self_serve'},
            canceled_at=now - timedelta(days=15),
        )
        db.session.add(sub)
        db.session.commit()
        assert self_serve_winback_eligible(sub) is False
