"""Aggregate counts for the consultation product.

Counts and money only. A customer's question, organisation, statements and
report are not loaded: site admins do not open someone else's consultation.
"""
from datetime import timedelta

from flask import render_template
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.admin import admin_bp
from app.decorators import admin_required
from app.lib.time import utcnow_naive
from app.models import (
    Consultation,
    ConsultationPlan,
    ConsultationPurchase,
    ConsultationReport,
    ConsultationTrial,
    LLMUsage,
)

# A live trial is reviewed only after this many days, so a late payment is
# not counted as a miss.
_PAYMENT_WINDOW_DAYS = 60
_REVIEW_COHORT = 30


def consultation_metrics() -> dict:
    """The numbers the admin dashboard shows. No consultation text."""
    now = utcnow_naive()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def _count(query):
        return query.scalar() or 0

    def _hosts_since(since):
        first_started = (
            db.session.query(
                Consultation.owner_user_id,
                func.min(Consultation.created_at).label('started'),
            )
            .group_by(Consultation.owner_user_id)
            .subquery()
        )
        return _count(
            db.session.query(func.count())
            .select_from(first_started)
            .filter(first_started.c.started >= since)
        )

    def _status(status):
        return _count(
            db.session.query(func.count(Consultation.id)).filter(Consultation.status == status)
        )

    paid = ConsultationPurchase.STATUS_PAID
    revenue_30d = (
        db.session.query(func.coalesce(func.sum(ConsultationPurchase.amount_pence), 0))
        .filter(
            ConsultationPurchase.status == paid,
            ConsultationPurchase.created_at >= month_ago,
        )
        .scalar()
    ) or 0

    review = _trial_review(now)
    usage = (
        db.session.query(
            func.coalesce(func.sum(LLMUsage.input_tokens), 0),
            func.coalesce(func.sum(LLMUsage.output_tokens), 0),
            func.count(LLMUsage.id),
        )
        .filter(
            LLMUsage.consultation_id.isnot(None),
            LLMUsage.created_at >= month_ago,
        )
        .one()
    )

    return {
        'hosts_7d': _hosts_since(week_ago),
        'hosts_30d': _hosts_since(month_ago),
        'hosts': _count(db.session.query(func.count(func.distinct(Consultation.owner_user_id)))),
        'drafts': _status(Consultation.STATUS_DRAFT),
        'live': _status(Consultation.STATUS_LIVE),
        'closed': _status(Consultation.STATUS_CLOSED),
        'went_live_7d': _count(
            db.session.query(func.count(Consultation.id)).filter(Consultation.published_at >= week_ago)
        ),
        'went_live_30d': _count(
            db.session.query(func.count(Consultation.id)).filter(Consultation.published_at >= month_ago)
        ),
        'passes_30d': _count(
            db.session.query(func.count(ConsultationPurchase.id)).filter(
                ConsultationPurchase.status == paid,
                ConsultationPurchase.created_at >= month_ago,
            )
        ),
        'revenue_30d_pence': int(revenue_30d),
        'refunds_30d': _count(
            db.session.query(func.count(ConsultationPurchase.id)).filter(
                ConsultationPurchase.status == ConsultationPurchase.STATUS_REFUNDED,
                ConsultationPurchase.refunded_at >= month_ago,
            )
        ),
        'active_plans': _count(
            db.session.query(func.count(ConsultationPlan.id)).filter(
                ConsultationPlan.status.in_(ConsultationPlan.ACCESS_STATUSES)
            )
        ),
        'plans_started_30d': _count(
            db.session.query(func.count(ConsultationPlan.id)).filter(
                ConsultationPlan.created_at >= month_ago,
            )
        ),
        'open_trials': _count(
            db.session.query(func.count(ConsultationTrial.id)).filter(ConsultationTrial.ends_at > now)
        ),
        'completed': _count(
            db.session.query(func.count(Consultation.id)).filter(
                Consultation.status == Consultation.STATUS_CLOSED,
            )
        ),
        'reports': _count(
            db.session.query(func.count(ConsultationReport.id)).filter(
                ConsultationReport.kind == ConsultationReport.KIND_FINAL,
            )
        ),
        'returning_hosts': _returning_hosts(),
        'llm_input_tokens_30d': int(usage[0] or 0),
        'llm_output_tokens_30d': int(usage[1] or 0),
        'llm_calls_30d': int(usage[2] or 0),
        **review,
    }


def _returning_hosts() -> int:
    """Hosts who have taken a second consultation live."""
    published = (
        db.session.query(
            Consultation.owner_user_id,
            func.count(Consultation.id).label('n'),
        )
        .filter(Consultation.published_at.isnot(None))
        .group_by(Consultation.owner_user_id)
        .subquery()
    )
    return (
        db.session.query(func.count())
        .select_from(published)
        .filter(published.c.n >= 2)
        .scalar()
    ) or 0


def _trial_review(now) -> dict:
    """The first live trials, judged only after each one has had 60 days.

    Rows are ids, dates and the campaign source. The email address on a trial
    is not loaded.
    """
    cutoff = now - timedelta(days=_PAYMENT_WINDOW_DAYS)
    window = timedelta(days=_PAYMENT_WINDOW_DAYS)
    trials = db.session.query(
        ConsultationTrial.user_id,
        ConsultationTrial.started_at,
        ConsultationTrial.domain,
        ConsultationTrial.acquisition_source,
    ).all()
    payments = {}
    for user_id, paid_at in db.session.query(
        ConsultationPurchase.user_id, ConsultationPurchase.created_at,
    ).filter(ConsultationPurchase.status == ConsultationPurchase.STATUS_PAID):
        payments.setdefault(user_id, []).append(paid_at)
    for user_id, started in db.session.query(
        ConsultationPlan.user_id, ConsultationPlan.created_at,
    ):
        payments.setdefault(user_id, []).append(started)

    mature = paid = window_open = 0
    domains: dict = {}
    sources: dict = {}
    for user_id, started_at, domain, source in trials:
        sources[source or 'direct'] = sources.get(source or 'direct', 0) + 1
        if domain:
            domains[domain] = domains.get(domain, 0) + 1
        if started_at > cutoff:
            window_open += 1
            continue
        mature += 1
        if any(started_at <= when <= started_at + window for when in payments.get(user_id, [])):
            paid += 1
    ranked = sorted(sources.items(), key=lambda item: (-item[1], item[0]))[:8]
    return {
        'trials_started': len(trials),
        'review_cohort': _REVIEW_COHORT,
        'trials_window_open': window_open,
        'trials_window_complete': mature,
        'paid_within_60': paid,
        'repeated_domains': sum(1 for count in domains.values() if count > 1),
        'acquisition': [{'source': source, 'trials': count} for source, count in ranked],
    }


@admin_bp.route('/consultations')
@login_required
@admin_required
def consultation_metrics_page():
    return render_template(
        'admin/consultations.html',
        now=utcnow_naive(),
        **consultation_metrics(),
    )
