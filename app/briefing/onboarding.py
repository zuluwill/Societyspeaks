"""
Self-serve paid briefings trial onboarding.

Single entry point for creating a DB-only (no Stripe) 30-day trial subscription
plus the user's first briefing, behind ``SELF_SERVE_TRIAL_ENABLED``. Wired into
``/briefings/start/complete`` after a successful magic-link consume.

Idempotent, transactional, abuse-aware. See
``docs/PAID_BRIEFINGS_WORLD_CLASS_BUILD.md`` for the full design.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from flask import current_app

from app import db
from app.billing.service import get_active_subscription
from app.lib.posthog_utils import safe_posthog_capture
from app.lib.time import utcnow_naive
from app.lib.trial_abuse import can_start_trial, record_trial_start
from app.lib.utm import pop_utms_for_event
from app.models import PricingPlan, Subscription, User
from app.models.briefing import BriefTemplate, Briefing


TRIAL_LENGTH_DAYS = 30
DEFAULT_PLAN_CODE = 'starter'


class TrialStartError(Exception):
    """Raised when a self-serve trial cannot be created.

    The ``reason`` attribute uses the same vocabulary as
    :func:`app.lib.trial_abuse.can_start_trial` plus a few service-level codes
    (e.g. ``'template_not_found'``, ``'plan_not_found'``). Surface a single
    generic message in the UI — don't leak which check failed.
    """

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


@dataclass
class TrialStartResult:
    """Outcome of :func:`start_self_serve_trial`."""

    subscription: Subscription
    briefing: Briefing
    already_existed: bool


def _active_briefing_for_user(user_id: int) -> Briefing | None:
    return (
        Briefing.query.filter_by(owner_type='user', owner_id=user_id, status='active')
        .order_by(Briefing.created_at.asc())
        .first()
    )


def _create_briefing_from_template(
    user: User,
    template: BriefTemplate,
    *,
    timezone: str,
    preferred_send_hour: int,
) -> tuple[Briefing, int, int]:
    """Create briefing + recipient + sources. Returns (briefing, sources_added, sources_failed)."""
    from app.briefing.routes import (
        add_auto_recipient_for_user,
        populate_briefing_sources_from_template,
    )

    guardrails = template.guardrails or {}
    briefing = Briefing(
        owner_type='user',
        owner_id=user.id,
        name=f"My {template.name}",
        description=template.description,
        theme_template_id=template.id,
        cadence=template.default_cadence or 'daily',
        timezone=timezone,
        preferred_send_hour=preferred_send_hour,
        preferred_send_minute=0,
        mode='auto_send',
        visibility='private',
        tone=template.default_tone,
        max_items=guardrails.get('max_items', 10),
        custom_prompt=template.custom_prompt_prefix,
        guardrails=guardrails or None,
        accent_color=template.default_accent_color or '#3B82F6',
        status='active',
    )
    db.session.add(briefing)
    db.session.flush()

    add_auto_recipient_for_user(briefing, user)
    sources_added, sources_failed, _missing = populate_briefing_sources_from_template(
        briefing, template.default_sources, user,
    )
    template.times_used = (template.times_used or 0) + 1
    return briefing, sources_added, sources_failed


def start_self_serve_trial(
    user: User,
    template_slug: str,
    *,
    locale: Optional[str] = None,
    ip: Optional[str] = None,
    timezone: str = 'UTC',
    preferred_send_hour: int = 7,
    posthog=None,
) -> TrialStartResult:
    """Create a DB-only trial subscription + first briefing for ``user``.

    Idempotent: if ``user`` already has a self-serve trial subscription
    (active or trialing) plus a briefing, the existing pair is returned with
    ``already_existed=True`` and no events fire.

    Args:
        user:                 Authenticated user (magic-link consumed).
        template_slug:        Slug of the :class:`BriefTemplate` to seed.
        locale:               Optional locale hint (e.g. ``'en-GB'``); stored on
                              ``extra_data`` for analytics.
        ip:                   Client IP for abuse rate limiting. Pass ``None``
                              to skip (e.g. from internal callers / tests).
        timezone:             IANA timezone for the briefing's send schedule.
        preferred_send_hour:  Hour of day (0–23) for daily brief delivery.
        posthog:              Optional PostHog client override (used by tests).

    Returns:
        :class:`TrialStartResult` containing the subscription, briefing, and
        ``already_existed`` flag.

    Raises:
        TrialStartError: When abuse rules block the start, the template is
            missing/inactive, the Personal plan isn't seeded, or the DB write
            fails. ``reason`` carries a machine-readable code.
    """
    # 1. Idempotency — return the existing pair when both are present.
    existing_sub = get_active_subscription(user)
    existing_briefing = _active_briefing_for_user(user.id)
    if existing_sub and existing_briefing:
        return TrialStartResult(
            subscription=existing_sub,
            briefing=existing_briefing,
            already_existed=True,
        )

    # Active access but no briefing: only recover for an in-flight self-serve trial.
    # Stripe/manual subscribers (e.g. paid with zero briefings) must not get a
    # second subscription row from this path.
    recover_briefing_only = False
    if existing_sub:
        extra = existing_sub.extra_data or {}
        if existing_sub.stripe_subscription_id or extra.get('trial_source') != 'self_serve':
            raise TrialStartError(
                'already_subscribed',
                'User already has subscription access',
            )
        recover_briefing_only = True

    # 2. Resolve template — no point doing abuse checks if the slug is invalid.
    template = BriefTemplate.query.filter_by(slug=template_slug, is_active=True).first()
    if not template:
        raise TrialStartError('template_not_found',
                              f"BriefTemplate slug='{template_slug}' not found or inactive")

    # 3. Resolve plan — Personal/starter is the only self-serve plan in v1.
    plan = PricingPlan.query.filter_by(code=DEFAULT_PLAN_CODE).first()
    if not plan:
        raise TrialStartError('plan_not_found',
                              f"PricingPlan code='{DEFAULT_PLAN_CODE}' not seeded")

    # 4. TOCTOU re-check — skip when we're only recovering a missing briefing
    # for an in-flight self-serve trial (abuse was satisfied on the original start).
    if not recover_briefing_only:
        ok, reason = can_start_trial(user.email, ip)
        if not ok:
            raise TrialStartError(reason or 'blocked')

    # 5. Build subscription + briefing inside a single transaction. Rollback
    # on any error so we never leave half-state behind.
    now = utcnow_naive()
    trial_end = now + timedelta(days=TRIAL_LENGTH_DAYS)
    utms = pop_utms_for_event()
    extra_data = {'trial_source': 'self_serve'}
    if utms:
        extra_data['utm'] = utms
    if locale:
        extra_data['locale'] = locale

    try:
        if recover_briefing_only:
            sub = existing_sub
        else:
            sub = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                status='trialing',
                billing_interval='month',
                trial_end=trial_end,
                current_period_start=now,
                current_period_end=trial_end,
                extra_data=extra_data,
            )
            db.session.add(sub)
            db.session.flush()

        briefing, sources_added, sources_failed = _create_briefing_from_template(
            user,
            template,
            timezone=timezone,
            preferred_send_hour=preferred_send_hour,
        )

        db.session.commit()
    except TrialStartError:
        db.session.rollback()
        raise
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(
            f"start_self_serve_trial failed for user {user.id}, template={template_slug}: {exc}",
            exc_info=True,
        )
        raise TrialStartError('db_error', str(exc)) from exc

    # 6. Post-commit side effects (skip duplicate abuse accounting on recovery).
    if not recover_briefing_only:
        record_trial_start(ip)

    if recover_briefing_only:
        return TrialStartResult(
            subscription=sub,
            briefing=briefing,
            already_existed=False,
        )

    safe_posthog_capture(
        posthog_client=posthog,
        distinct_id=str(user.id),
        event='paid_briefing_trial_started_self_serve',
        properties={
            'subscription_id': sub.id,
            'briefing_id': briefing.id,
            'plan_code': plan.code,
            'template_slug': template_slug,
            'sources_added': sources_added,
            'sources_failed': sources_failed,
            **utms,
        },
    )

    current_app.logger.info(
        "Self-serve trial started: user=%s sub=%s briefing=%s template=%s sources=%s",
        user.id, sub.id, briefing.id, template_slug, sources_added,
    )

    return TrialStartResult(
        subscription=sub,
        briefing=briefing,
        already_existed=False,
    )
