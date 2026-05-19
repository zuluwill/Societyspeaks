"""
Tests for start_self_serve_trial (Block B of the world-class paid briefings build).

Covers:
  - happy path: creates trialing Subscription + Briefing + fires PostHog event
  - idempotency: existing self-serve trial returns existing pair, no event
  - idempotency: existing Stripe-backed active sub returns existing pair
  - abuse: invalid email, disposable domain, blocked → TrialStartError
  - missing template / missing plan → TrialStartError
  - rollback on briefing-creation exception (no orphan Subscription row)
  - UTMs from session attach to event and persist on extra_data
  - locale stored on extra_data
"""
from unittest.mock import MagicMock, patch

import pytest

from app.briefing.onboarding import (
    DEFAULT_PLAN_CODE,
    TRIAL_LENGTH_DAYS,
    TrialStartError,
    start_self_serve_trial,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _seed_plan(db):
    from app.models.billing import PricingPlan
    plan = PricingPlan(
        code=DEFAULT_PLAN_CODE,
        name='Personal',
        price_monthly=499,
        price_yearly=4900,
        currency='GBP',
        is_organisation=False,
        is_active=True,
    )
    db.session.add(plan)
    db.session.flush()
    return plan


def _seed_template(db, slug='technology-ai-regulation', name='AI & Technology'):
    from app.models.briefing import BriefTemplate
    tpl = BriefTemplate(
        slug=slug,
        name=name,
        description='AI & tech news from sources you trust',
        category='core_insight',
        audience_type='all',
        is_featured=True,
        is_active=True,
        default_sources=[],  # empty so we don't depend on NewsSource seed data
        default_cadence='daily',
        default_tone='balanced',
        custom_prompt_prefix='Focus on AI and technology developments.',
        configurable_options={},
        guardrails={'max_items': 8},
    )
    db.session.add(tpl)
    db.session.flush()
    return tpl


def _seed_user(db, username='alice', email='alice@example.com'):
    from app.models import User
    user = User(
        username=username,
        email=email,
        password='hashed-placeholder',
        email_verified=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_start_self_serve_trial_creates_sub_and_briefing(app, db):
    from app.models.billing import Subscription
    from app.models.briefing import Briefing

    with app.app_context():
        _seed_plan(db)
        tpl = _seed_template(db)
        user = _seed_user(db)
        db.session.commit()

        fake_posthog = MagicMock()
        with app.test_request_context():  # session needed by pop_utms_for_event
            result = start_self_serve_trial(
                user,
                template_slug=tpl.slug,
                locale='en-GB',
                ip='10.0.0.1',
                posthog=fake_posthog,
            )

        assert result.already_existed is False
        assert isinstance(result.subscription, Subscription)
        assert isinstance(result.briefing, Briefing)
        # Subscription correctness.
        assert result.subscription.status == 'trialing'
        assert result.subscription.stripe_subscription_id is None
        assert result.subscription.user_id == user.id
        assert result.subscription.billing_interval == 'month'
        assert result.subscription.trial_end is not None
        delta = (result.subscription.trial_end - result.subscription.current_period_start).days
        assert delta == TRIAL_LENGTH_DAYS
        # extra_data carries trial_source + locale.
        extra = result.subscription.extra_data
        assert extra.get('trial_source') == 'self_serve'
        assert extra.get('locale') == 'en-GB'
        # Briefing correctness.
        assert result.briefing.owner_type == 'user'
        assert result.briefing.owner_id == user.id
        assert result.briefing.theme_template_id == tpl.id
        assert result.briefing.cadence == 'daily'
        assert result.briefing.status == 'active'

        # PostHog event fired with the new self-serve cohort name.
        fake_posthog.capture.assert_called_once()
        call_kwargs = fake_posthog.capture.call_args.kwargs
        assert call_kwargs['event'] == 'paid_briefing_trial_started_self_serve'
        assert call_kwargs['distinct_id'] == str(user.id)
        props = call_kwargs['properties']
        assert props['template_slug'] == tpl.slug
        assert props['plan_code'] == DEFAULT_PLAN_CODE


def test_start_self_serve_trial_attaches_utms_from_session(app, db):
    with app.app_context():
        _seed_plan(db)
        tpl = _seed_template(db)
        user = _seed_user(db, username='bob', email='bob@example.com')
        db.session.commit()

        fake_posthog = MagicMock()
        with app.test_request_context() as ctx:
            from flask import session
            session['utm'] = {'utm_source': 'daily_brief', 'utm_campaign': 'personal_briefs_cta'}
            result = start_self_serve_trial(
                user, template_slug=tpl.slug, ip='10.0.0.2', posthog=fake_posthog,
            )

        # UTMs persisted on extra_data and on the event.
        assert result.subscription.extra_data['utm']['utm_source'] == 'daily_brief'
        props = fake_posthog.capture.call_args.kwargs['properties']
        assert props.get('utm_source') == 'daily_brief'
        assert props.get('utm_campaign') == 'personal_briefs_cta'


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_start_self_serve_trial_idempotent_for_existing_self_serve(app, db):
    with app.app_context():
        _seed_plan(db)
        tpl = _seed_template(db)
        user = _seed_user(db, username='carol', email='carol@example.com')
        db.session.commit()

        fake_posthog = MagicMock()
        with app.test_request_context():
            first = start_self_serve_trial(
                user, template_slug=tpl.slug, ip='10.0.0.3', posthog=fake_posthog,
            )
            second = start_self_serve_trial(
                user, template_slug=tpl.slug, ip='10.0.0.3', posthog=fake_posthog,
            )

        assert first.subscription.id == second.subscription.id
        assert first.briefing.id == second.briefing.id
        assert second.already_existed is True
        # Event fires only once — on the first creation.
        assert fake_posthog.capture.call_count == 1


def test_start_self_serve_trial_idempotent_for_paying_stripe_user(app, db):
    """A user already on a Stripe subscription should get their existing setup back."""
    from app.models.billing import Subscription

    with app.app_context():
        plan = _seed_plan(db)
        tpl = _seed_template(db)
        user = _seed_user(db, username='dave', email='dave@example.com')
        # Existing Stripe sub + briefing.
        sub = Subscription(
            user_id=user.id, plan_id=plan.id,
            stripe_subscription_id='sub_xyz',
            status='active', billing_interval='month',
            extra_data={'trial_source': 'stripe'},
        )
        db.session.add(sub)
        db.session.flush()

        from app.models.briefing import Briefing
        existing_briefing = Briefing(
            owner_type='user', owner_id=user.id,
            name='Existing brief', theme_template_id=tpl.id,
            cadence='daily', timezone='UTC', preferred_send_hour=7,
            mode='auto_send', visibility='private', status='active',
        )
        db.session.add(existing_briefing)
        db.session.commit()

        fake_posthog = MagicMock()
        with app.test_request_context():
            result = start_self_serve_trial(
                user, template_slug=tpl.slug, ip='10.0.0.4', posthog=fake_posthog,
            )

        assert result.already_existed is True
        assert result.subscription.id == sub.id
        assert result.briefing.id == existing_briefing.id
        # No double-trial subscription created.
        all_subs = Subscription.query.filter_by(user_id=user.id).all()
        assert len(all_subs) == 1
        # No event for an already-existing user.
        fake_posthog.capture.assert_not_called()


# ---------------------------------------------------------------------------
# Abuse / validation errors
# ---------------------------------------------------------------------------

def test_start_self_serve_trial_raises_for_disposable_email(app, db):
    with app.app_context():
        _seed_plan(db)
        tpl = _seed_template(db)
        user = _seed_user(db, username='eve', email='eve@mailinator.com')
        db.session.commit()

        with app.test_request_context():
            with pytest.raises(TrialStartError) as exc_info:
                start_self_serve_trial(user, template_slug=tpl.slug, ip='10.0.0.5')

        assert exc_info.value.reason == 'disposable_domain'


def test_start_self_serve_trial_raises_for_missing_template(app, db):
    with app.app_context():
        _seed_plan(db)
        user = _seed_user(db, username='frank', email='frank@example.com')
        db.session.commit()

        with app.test_request_context():
            with pytest.raises(TrialStartError) as exc_info:
                start_self_serve_trial(user, template_slug='nonexistent-slug')

        assert exc_info.value.reason == 'template_not_found'


def test_start_self_serve_trial_raises_for_missing_plan(app, db):
    """If PricingPlan code='starter' isn't seeded, we fail fast."""
    with app.app_context():
        tpl = _seed_template(db)
        user = _seed_user(db, username='grace', email='grace@example.com')
        db.session.commit()
        # Note: no _seed_plan() call.

        with app.test_request_context():
            with pytest.raises(TrialStartError) as exc_info:
                start_self_serve_trial(user, template_slug=tpl.slug)

        assert exc_info.value.reason == 'plan_not_found'


def test_start_self_serve_trial_rolls_back_on_briefing_failure(app, db):
    """If briefing creation throws, the subscription row must also roll back."""
    from app.models.billing import Subscription

    with app.app_context():
        _seed_plan(db)
        tpl = _seed_template(db)
        user = _seed_user(db, username='hank', email='hank@example.com')
        db.session.commit()

        # Force a failure inside the transaction by making
        # populate_briefing_sources_from_template raise.
        with patch(
            'app.briefing.routes.populate_briefing_sources_from_template',
            side_effect=RuntimeError('boom'),
        ):
            with app.test_request_context():
                with pytest.raises(TrialStartError) as exc_info:
                    start_self_serve_trial(user, template_slug=tpl.slug)

        assert exc_info.value.reason == 'db_error'
        # No orphan subscription should remain.
        assert Subscription.query.filter_by(user_id=user.id).count() == 0


def test_start_self_serve_trial_raises_when_paid_sub_has_no_briefing(app, db):
    """Stripe/manual access without a briefing must not mint a second subscription."""
    from app.models.billing import Subscription

    with app.app_context():
        plan = _seed_plan(db)
        tpl = _seed_template(db)
        user = _seed_user(db, username='jen', email='jen@example.com')
        sub = Subscription(
            user_id=user.id, plan_id=plan.id,
            stripe_subscription_id='sub_paid',
            status='active', billing_interval='month',
            extra_data={'trial_source': 'stripe'},
        )
        db.session.add(sub)
        db.session.commit()

        with app.test_request_context():
            with pytest.raises(TrialStartError) as exc_info:
                start_self_serve_trial(user, template_slug=tpl.slug, ip='10.0.0.50')

        assert exc_info.value.reason == 'already_subscribed'
        assert Subscription.query.filter_by(user_id=user.id).count() == 1


def test_start_self_serve_trial_recovers_briefing_for_existing_self_serve_sub(app, db):
    """Self-serve sub without a briefing should create the briefing only."""
    from app.models.billing import Subscription
    from app.models.briefing import Briefing

    with app.app_context():
        plan = _seed_plan(db)
        tpl = _seed_template(db)
        user = _seed_user(db, username='kai', email='kai@example.com')
        sub = Subscription(
            user_id=user.id, plan_id=plan.id,
            status='trialing', billing_interval='month',
            extra_data={'trial_source': 'self_serve'},
        )
        db.session.add(sub)
        db.session.commit()

        fake_posthog = MagicMock()
        with app.test_request_context():
            result = start_self_serve_trial(
                user, template_slug=tpl.slug, ip='10.0.0.51', posthog=fake_posthog,
            )

        assert result.subscription.id == sub.id
        assert result.briefing.owner_id == user.id
        assert Subscription.query.filter_by(user_id=user.id).count() == 1
        assert Briefing.query.filter_by(owner_id=user.id).count() == 1
        fake_posthog.capture.assert_not_called()


def test_start_self_serve_trial_records_ip_only_after_commit(app, db):
    """record_trial_start(ip) must NOT fire when the transaction rolls back."""
    with app.app_context():
        _seed_plan(db)
        tpl = _seed_template(db)
        user = _seed_user(db, username='iris', email='iris@example.com')
        db.session.commit()

        with patch('app.briefing.onboarding.record_trial_start') as record_mock, \
             patch(
                 'app.briefing.routes.populate_briefing_sources_from_template',
                 side_effect=RuntimeError('boom'),
             ):
            with app.test_request_context():
                with pytest.raises(TrialStartError):
                    start_self_serve_trial(user, template_slug=tpl.slug, ip='10.0.0.99')

        # Rollback path means we never reached the post-commit record_trial_start.
        record_mock.assert_not_called()
