"""
Admin views for the paid briefings product.

Separate from brief/admin.py (which manages the admin-curated Daily Brief).
This module covers user-created briefings: subscriptions, billing, and briefing activity.
"""
from flask import Blueprint, render_template, request
from datetime import timedelta
from sqlalchemy import func
from sqlalchemy.orm import contains_eager
from app import db
from app.decorators import admin_required
from app.admin.utils import escape_like as _escape_like
from app.lib.time import utcnow_naive
from app.models import (
    Subscription, PricingPlan, Briefing, BriefRun,
    BriefRecipient, BriefingSource, User, CompanyProfile,
)

briefings_admin_bp = Blueprint('briefings_admin', __name__, url_prefix='/admin/briefings')


def _subscription_query():
    """Base query for Subscription rows with plan, user, and org eagerly loaded.

    Centralises the join/options pattern so every view in this module stays DRY.
    """
    return (
        db.session.query(Subscription)
        .join(PricingPlan, Subscription.plan_id == PricingPlan.id)
        .outerjoin(User, Subscription.user_id == User.id)
        .outerjoin(CompanyProfile, Subscription.org_id == CompanyProfile.id)
        .options(
            contains_eager(Subscription.plan),
            contains_eager(Subscription.user),
            contains_eager(Subscription.org),
        )
    )


@briefings_admin_bp.route('/metrics')
@admin_required
def metrics():
    """Self-serve trial cohort metrics — pure DB queries, no PostHog dependency.

    Each row is a single SQL count; refresh-on-load. Numbers come straight
    from ``Subscription``/``Briefing`` so the source of truth matches what
    the billing system actually sees.
    """
    now = utcnow_naive()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    forty_eight_ago = now - timedelta(hours=48)

    # ---- Helpers -----------------------------------------------------------

    def _count(query):
        return query.scalar() or 0

    def _trials_in_window(since=None, until=None, source=None):
        """Count Subscription rows matching the (window, source) cohort."""
        q = db.session.query(func.count(Subscription.id))
        if since is not None:
            q = q.filter(Subscription.created_at >= since)
        if until is not None:
            q = q.filter(Subscription.created_at < until)
        if source is not None:
            # trial_source lives in extra_data JSON. SQLAlchemy's JSON op
            # works on Postgres + SQLite via the compat shim in conftest.
            q = q.filter(Subscription.extra_data['trial_source'].as_string() == source)
        return _count(q)

    # ---- Top-line trial volume --------------------------------------------

    trials_total_week = _trials_in_window(since=week_ago)
    trials_total_month = _trials_in_window(since=month_ago)
    trials_self_serve_week = _trials_in_window(since=week_ago, source='self_serve')
    trials_self_serve_month = _trials_in_window(since=month_ago, source='self_serve')
    trials_stripe_month = _trials_in_window(since=month_ago, source='stripe')

    # ---- Activation: ≥1 briefing within 48h of trial start ----------------
    # Restrict the cohort denominator to "had at least 48h to activate" so we
    # don't pollute the rate with users who just signed up.
    eligible_for_activation_30d = (
        db.session.query(Subscription)
        .filter(Subscription.created_at >= month_ago)
        .filter(Subscription.created_at <= forty_eight_ago)
    )
    eligible_count = eligible_for_activation_30d.count()

    activated_count = (
        db.session.query(func.count(func.distinct(Subscription.id)))
        .join(User, Subscription.user_id == User.id)
        .join(Briefing, db.and_(
            Briefing.owner_type == 'user',
            Briefing.owner_id == User.id,
        ))
        .filter(Subscription.created_at >= month_ago)
        .filter(Subscription.created_at <= forty_eight_ago)
        .filter(Briefing.created_at <= Subscription.created_at + timedelta(hours=48))
    ).scalar() or 0

    activation_pct = (
        round((activated_count / eligible_count) * 100, 1) if eligible_count else None
    )

    # ---- First-brief delivery: % of new trials with a generated BriefRun -
    first_brief_eligible = (
        db.session.query(Subscription)
        .filter(Subscription.created_at >= month_ago)
    ).count()
    first_brief_delivered = (
        db.session.query(func.count(func.distinct(Subscription.id)))
        .join(User, Subscription.user_id == User.id)
        .join(Briefing, db.and_(
            Briefing.owner_type == 'user',
            Briefing.owner_id == User.id,
        ))
        .join(BriefRun, BriefRun.briefing_id == Briefing.id)
        .filter(Subscription.created_at >= month_ago)
    ).scalar() or 0
    first_brief_pct = (
        round((first_brief_delivered / first_brief_eligible) * 100, 1)
        if first_brief_eligible else None
    )

    # ---- Conversion: self-serve trials that landed a Stripe sub ----------
    conversion_count = (
        db.session.query(func.count(func.distinct(User.id)))
        .join(Subscription, Subscription.user_id == User.id)
        .filter(Subscription.stripe_subscription_id.isnot(None))
        .filter(Subscription.status == 'active')
        .filter(
            User.id.in_(
                db.session.query(Subscription.user_id)
                .filter(Subscription.extra_data['trial_source'].as_string() == 'self_serve')
                .filter(Subscription.created_at >= month_ago)
            )
        )
    ).scalar() or 0
    conversion_pct = (
        round((conversion_count / trials_self_serve_month) * 100, 1)
        if trials_self_serve_month else None
    )

    # ---- Pause / resume ---------------------------------------------------
    paused_count = (
        db.session.query(func.count(Subscription.id))
        .filter(Subscription.extra_data['paused_at'].as_string().isnot(None))
    ).scalar() or 0

    return render_template(
        'admin/briefings/metrics.html',
        now=now,
        trials_total_week=trials_total_week,
        trials_total_month=trials_total_month,
        trials_self_serve_week=trials_self_serve_week,
        trials_self_serve_month=trials_self_serve_month,
        trials_stripe_month=trials_stripe_month,
        eligible_count=eligible_count,
        activated_count=activated_count,
        activation_pct=activation_pct,
        first_brief_eligible=first_brief_eligible,
        first_brief_delivered=first_brief_delivered,
        first_brief_pct=first_brief_pct,
        conversion_count=conversion_count,
        conversion_pct=conversion_pct,
        paused_count=paused_count,
    )


@briefings_admin_bp.route('/')
@admin_required
def subscriptions():
    """Subscriptions overview: who signed up, plan, billing status, trial health."""
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 50

    search_query = request.args.get('q', '').strip()[:255]
    status_filter = request.args.get('status', '')
    plan_filter = request.args.get('plan', '')

    query = _subscription_query()

    if search_query:
        query = query.filter(User.email.ilike(f'%{_escape_like(search_query)}%', escape='\\'))

    if status_filter:
        if status_filter == 'at_risk':
            query = query.filter(Subscription.status.in_(('past_due', 'unpaid')))
        else:
            query = query.filter(Subscription.status == status_filter)

    if plan_filter:
        query = query.filter(PricingPlan.code == plan_filter)

    pagination = query.order_by(Subscription.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Stats — always unfiltered so the cards reflect the full picture
    status_counts = dict(
        db.session.query(Subscription.status, func.count(Subscription.id))
        .group_by(Subscription.status).all()
    )
    stats = {
        'total': sum(status_counts.values()),
        'trialing': status_counts.get('trialing', 0),
        'active': status_counts.get('active', 0),
        # 'past_due' and 'unpaid' are both revenue-at-risk
        'at_risk': status_counts.get('past_due', 0) + status_counts.get('unpaid', 0),
        'canceled': status_counts.get('canceled', 0),
    }

    # Trials expiring within 7 days — surface as an alert
    now = utcnow_naive()
    expiring_soon = (
        _subscription_query()
        .filter(
            Subscription.status == 'trialing',
            Subscription.trial_end.isnot(None),
            Subscription.trial_end > now,
            Subscription.trial_end <= now + timedelta(days=7),
        )
        .order_by(Subscription.trial_end.asc())
        .all()
    )

    plans = PricingPlan.query.filter_by(is_active=True).order_by(PricingPlan.display_order).all()

    return render_template(
        'admin/briefings/subscriptions.html',
        subscriptions=pagination.items,
        pagination=pagination,
        stats=stats,
        expiring_soon=expiring_soon,
        plans=plans,
        search_query=search_query,
        status_filter=status_filter,
        plan_filter=plan_filter,
    )


@briefings_admin_bp.route('/briefings')
@admin_required
def briefings():
    """All user-created briefings: activity, sources, recipients, send history."""
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 50

    search_query = request.args.get('q', '').strip()[:255]
    status_filter = request.args.get('status', '')
    cadence_filter = request.args.get('cadence', '')
    owner_type_filter = request.args.get('owner_type', '')

    query = Briefing.query

    if search_query:
        query = query.filter(Briefing.name.ilike(f'%{_escape_like(search_query)}%', escape='\\'))

    if status_filter:
        query = query.filter(Briefing.status == status_filter)

    if cadence_filter:
        query = query.filter(Briefing.cadence == cadence_filter)

    if owner_type_filter:
        query = query.filter(Briefing.owner_type == owner_type_filter)

    pagination = query.order_by(Briefing.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    briefing_list = pagination.items

    # Batch-fetch all per-briefing data to avoid N+1 queries
    if briefing_list:
        briefing_ids = [b.id for b in briefing_list]

        source_counts = dict(
            db.session.query(BriefingSource.briefing_id, func.count())
            .filter(BriefingSource.briefing_id.in_(briefing_ids))
            .group_by(BriefingSource.briefing_id).all()
        )

        recipient_counts = dict(
            db.session.query(BriefRecipient.briefing_id, func.count())
            .filter(
                BriefRecipient.briefing_id.in_(briefing_ids),
                BriefRecipient.status == 'active',
            )
            .group_by(BriefRecipient.briefing_id).all()
        )

        run_stat_rows = db.session.query(
            BriefRun.briefing_id,
            func.count(BriefRun.id).label('total_runs'),
            func.count(BriefRun.sent_at).label('sent_runs'),
            func.max(BriefRun.sent_at).label('last_sent_at'),
        ).filter(BriefRun.briefing_id.in_(briefing_ids)).group_by(BriefRun.briefing_id).all()
        run_stats = {r.briefing_id: r for r in run_stat_rows}

        user_owner_ids = [b.owner_id for b in briefing_list if b.owner_type == 'user']
        org_owner_ids = [b.owner_id for b in briefing_list if b.owner_type == 'org']

        users_by_id = (
            {u.id: u for u in User.query.filter(User.id.in_(user_owner_ids)).all()}
            if user_owner_ids else {}
        )
        orgs_by_id = (
            {o.id: o for o in CompanyProfile.query.filter(CompanyProfile.id.in_(org_owner_ids)).all()}
            if org_owner_ids else {}
        )

        for b in briefing_list:
            b._source_count = source_counts.get(b.id, 0)
            b._recipient_count = recipient_counts.get(b.id, 0)
            rs = run_stats.get(b.id)
            b._run_count = rs.total_runs if rs else 0
            b._sent_count = rs.sent_runs if rs else 0
            b._last_sent_at = rs.last_sent_at if rs else None
            b._owner = (
                users_by_id.get(b.owner_id) if b.owner_type == 'user'
                else orgs_by_id.get(b.owner_id)
            )

    # Stats — always unfiltered
    status_counts = dict(
        db.session.query(Briefing.status, func.count(Briefing.id))
        .group_by(Briefing.status).all()
    )
    stats = {
        'total': sum(status_counts.values()),
        'active': status_counts.get('active', 0),
        'paused': status_counts.get('paused', 0),
    }

    return render_template(
        'admin/briefings/briefings.html',
        briefings=briefing_list,
        pagination=pagination,
        stats=stats,
        search_query=search_query,
        status_filter=status_filter,
        cadence_filter=cadence_filter,
        owner_type_filter=owner_type_filter,
    )
