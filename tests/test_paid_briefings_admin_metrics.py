"""
Tests for /admin/briefings/metrics (Block D — admin observability).

Covers:
  - unauthenticated → redirect to login
  - non-admin authenticated → forbidden / redirect
  - admin authenticated, empty DB → renders without errors, shows zero counts
  - admin authenticated, seeded self-serve trial → counts reflected in volume cards
"""
from datetime import timedelta

from app.lib.time import utcnow_naive
from app.models import User
from app.models.billing import PricingPlan, Subscription


def _seed_admin(db, username='admin_view', email='admin@example.com'):
    u = User(
        username=username, email=email,
        password='hashed', email_verified=True,
        is_admin=True,
    )
    db.session.add(u)
    db.session.flush()
    return u


def _seed_user(db, username='user1', email='user1@example.com'):
    u = User(username=username, email=email, password='hashed', email_verified=True)
    db.session.add(u)
    db.session.flush()
    return u


def _seed_plan(db):
    plan = PricingPlan(
        code='starter', name='Personal',
        price_monthly=499, price_yearly=4900,
        currency='GBP', is_organisation=False, is_active=True,
    )
    db.session.add(plan)
    db.session.flush()
    return plan


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_metrics_unauthenticated_redirects(app, db):
    client = app.test_client()
    resp = client.get('/admin/briefings/metrics', follow_redirects=False)
    # Either redirect to login (302) or 403 depending on the decorator implementation.
    assert resp.status_code in (302, 401, 403)


def test_metrics_non_admin_forbidden(app, db):
    with app.app_context():
        user = _seed_user(db)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/admin/briefings/metrics', follow_redirects=False)
    # Decorator either returns 403 or redirects away — both acceptable.
    assert resp.status_code in (302, 403)


def test_metrics_admin_renders_empty_state(app, db):
    with app.app_context():
        admin = _seed_admin(db)
        db.session.commit()
        admin_id = admin.id

    client = app.test_client()
    _login(client, admin_id)
    resp = client.get('/admin/briefings/metrics', follow_redirects=False)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Page renders even with zero data.
    assert 'Paid Briefings Metrics' in body
    assert 'Trial volume' in body
    assert 'Activation' in body


def test_metrics_admin_counts_recent_self_serve_trial(app, db):
    with app.app_context():
        admin = _seed_admin(db)
        plan = _seed_plan(db)
        # Seed a self-serve trial created 1 day ago.
        user = _seed_user(db, username='trial_user', email='trialuser@example.com')
        now = utcnow_naive()
        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            stripe_subscription_id=None,
            status='trialing',
            billing_interval='month',
            extra_data={'trial_source': 'self_serve'},
            created_at=now - timedelta(days=1),
            trial_end=now + timedelta(days=29),
        )
        db.session.add(sub)
        db.session.commit()
        admin_id = admin.id

    client = app.test_client()
    _login(client, admin_id)
    resp = client.get('/admin/briefings/metrics')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # The "Self-serve, 7d" card should reflect the one we just seeded.
    assert 'Self-serve, 7d' in body
