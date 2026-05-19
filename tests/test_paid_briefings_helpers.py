"""
Tests for Block B foundation helpers of the world-class paid briefings build.

Covers:
  - normalize_trial_email: gmail dots/plus aliases, googlemail rewrite, edge cases
  - can_start_trial: invalid / disposable / one-per-email
  - subscription_allows_sending: status gate + paused_at gate
"""
from unittest.mock import patch

import pytest

from app.lib.email_normalize import normalize_trial_email


# ---------------------------------------------------------------------------
# normalize_trial_email
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw, expected', [
    ('foo@gmail.com', 'foo@gmail.com'),
    ('FOO@gmail.com', 'foo@gmail.com'),
    ('foo.bar@gmail.com', 'foobar@gmail.com'),
    ('foo+tag@gmail.com', 'foo@gmail.com'),
    ('foo.bar+xyz@gmail.com', 'foobar@gmail.com'),
    ('foo@googlemail.com', 'foo@gmail.com'),
    ('foo.bar+x@googlemail.com', 'foobar@gmail.com'),
    ('  Foo@Example.COM  ', 'foo@example.com'),
    # Non-Gmail: dots and + are preserved as-is.
    ('foo.bar@protonmail.com', 'foo.bar@protonmail.com'),
    ('foo+tag@protonmail.com', 'foo+tag@protonmail.com'),
])
def test_normalize_trial_email_canonicalizes(raw, expected):
    assert normalize_trial_email(raw) == expected


@pytest.mark.parametrize('raw', [None, '', '   ', 'no-at-sign', '@nodomain.com', 'nolocal@', '+@gmail.com', '...@gmail.com'])
def test_normalize_trial_email_rejects_malformed(raw):
    assert normalize_trial_email(raw) is None


# ---------------------------------------------------------------------------
# can_start_trial
# ---------------------------------------------------------------------------

def test_can_start_trial_rejects_invalid_email(app):
    from app.lib.trial_abuse import can_start_trial
    with app.app_context():
        ok, reason = can_start_trial('', '1.2.3.4')
    assert ok is False
    assert reason == 'invalid_email'


def test_can_start_trial_rejects_disposable_domain(app):
    from app.lib.trial_abuse import can_start_trial
    with app.app_context():
        ok, reason = can_start_trial('throwaway@mailinator.com', '1.2.3.4')
    assert ok is False
    assert reason == 'disposable_domain'


def test_can_start_trial_allows_legit_email(app, db):
    from app.lib.trial_abuse import can_start_trial
    with app.app_context():
        ok, reason = can_start_trial('alice@example.com', '1.2.3.4')
    assert ok is True
    assert reason is None


def test_can_start_trial_blocks_second_self_serve_trial_for_same_canonical_email(app, db):
    from app.lib.trial_abuse import can_start_trial
    from app.models import User
    from app.models.billing import Subscription, PricingPlan

    with app.app_context():
        # Seed a plan + user + self-serve trial subscription.
        plan = PricingPlan(
            code='starter', name='Personal', price_monthly=499, price_yearly=4900,
            currency='GBP', is_organisation=False,
        )
        db.session.add(plan)
        db.session.flush()

        user = User(
            username='trial_alice', email='alice.test+a@gmail.com',
            password='hashed', email_verified=True,
        )
        db.session.add(user)
        db.session.flush()

        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status='trialing',
            billing_interval='month',
            extra_data={'trial_source': 'self_serve'},
        )
        db.session.add(sub)
        db.session.commit()

        # Same canonical address but different surface form — must be blocked.
        ok, reason = can_start_trial('AliceTest@gmail.com', '1.2.3.4')

    assert ok is False
    assert reason == 'email_already_used'


def test_can_start_trial_does_not_block_when_only_stripe_sub_exists(app, db):
    """Stripe-backed subs don't count against the one-trial-per-email rule —
    the user is already paying. (Edge case: a paying user trying to start a
    new self-serve trial; we shouldn't lock them out, get_active_subscription
    is the check for that.)"""
    from app.lib.trial_abuse import can_start_trial
    from app.models import User
    from app.models.billing import Subscription, PricingPlan

    with app.app_context():
        plan = PricingPlan(
            code='starter', name='Personal', price_monthly=499, price_yearly=4900,
            currency='GBP', is_organisation=False,
        )
        db.session.add(plan)
        db.session.flush()

        user = User(
            username='paying_bob', email='bob@example.com',
            password='hashed', email_verified=True,
        )
        db.session.add(user)
        db.session.flush()

        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            stripe_subscription_id='sub_abc',
            status='active',
            billing_interval='month',
            extra_data={'trial_source': 'stripe'},
        )
        db.session.add(sub)
        db.session.commit()

        ok, reason = can_start_trial('bob@example.com', '1.2.3.4')

    # Not blocked by abuse — caller is expected to check get_active_subscription separately.
    assert ok is True
    assert reason is None


# ---------------------------------------------------------------------------
# subscription_allows_sending
# ---------------------------------------------------------------------------

class _FakeSub:
    def __init__(self, status='active', extra_data=None):
        self.status = status
        self.extra_data = extra_data or {}


def test_subscription_allows_sending_none_returns_false():
    from app.billing.service import subscription_allows_sending
    assert subscription_allows_sending(None) is False


@pytest.mark.parametrize('status', ['trialing', 'active', 'past_due'])
def test_subscription_allows_sending_for_sending_statuses(status):
    from app.billing.service import subscription_allows_sending
    assert subscription_allows_sending(_FakeSub(status=status)) is True


@pytest.mark.parametrize('status', ['canceled', 'unpaid', 'incomplete', 'superseded'])
def test_subscription_allows_sending_rejects_non_sending_statuses(status):
    from app.billing.service import subscription_allows_sending
    assert subscription_allows_sending(_FakeSub(status=status)) is False


def test_subscription_allows_sending_paused_at_blocks_active():
    from app.billing.service import subscription_allows_sending
    sub = _FakeSub(status='active', extra_data={'paused_at': '2026-05-01T00:00:00'})
    assert subscription_allows_sending(sub) is False


def test_subscription_allows_sending_empty_extra_data_does_not_pause():
    from app.billing.service import subscription_allows_sending
    sub = _FakeSub(status='trialing', extra_data={})
    assert subscription_allows_sending(sub) is True


def test_can_start_trial_ip_rate_limit_blocks_after_threshold(app):
    from app.lib.trial_abuse import _IP_RATE_LIMIT_COUNT, can_start_trial

    class _FakeRedis:
        def __init__(self):
            self._counts = {}

        def get(self, key):
            return str(self._counts.get(key, 0))

        def incr(self, key):
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

        def expire(self, key, ttl):
            pass

    fake = _FakeRedis()
    # Simulate prior starts at the cap.
    fake._counts['trial_start_ip:9.9.9.9'] = _IP_RATE_LIMIT_COUNT

    with app.app_context():
        with patch('app.lib.redis_client.get_client', return_value=fake):
            ok, reason = can_start_trial('newuser@example.com', '9.9.9.9')

    assert ok is False
    assert reason == 'ip_rate_limit'
