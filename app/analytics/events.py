from datetime import timedelta
import logging

from sqlalchemy import and_, distinct, func

from app import db
from app.lib.time import utcnow_naive
from app.models import AnalyticsDailyAggregate, AnalyticsEvent, Discussion

logger = logging.getLogger(__name__)

CANONICAL_EVENT_NAMES = {
    'account_created',
    'discussion_viewed',
    'statement_voted',
    'response_created',
    'cohort_assigned',
    'analysis_generated',
}


def record_event(event_name, **kwargs):
    """Append-only analytics event write. Never raises into caller path."""
    if event_name not in CANONICAL_EVENT_NAMES:
        return None
    try:
        event = AnalyticsEvent(
            event_name=event_name,
            user_id=kwargs.get('user_id'),
            programme_id=kwargs.get('programme_id'),
            discussion_id=kwargs.get('discussion_id'),
            statement_id=kwargs.get('statement_id'),
            cohort_slug=kwargs.get('cohort_slug'),
            country=kwargs.get('country'),
            source=kwargs.get('source'),
            event_metadata=kwargs.get('event_metadata') or {},
        )
        db.session.add(event)
        db.session.commit()
        return event
    except Exception as exc:
        db.session.rollback()
        logger.warning(f"Failed to record analytics event '{event_name}': {exc}")
        return None


def rollup_analytics_daily(days_back=14):
    """
    Rebuild daily aggregates for recent window from raw immutable events.
    Deterministic delete+insert by date window to avoid drift.
    """
    end_time = utcnow_naive()
    start_time = end_time - timedelta(days=max(1, days_back))
    start_date = start_time.date()

    db.session.query(AnalyticsDailyAggregate).filter(
        AnalyticsDailyAggregate.event_date >= start_date
    ).delete(synchronize_session=False)
    db.session.flush()

    rows = db.session.query(
        func.date(AnalyticsEvent.created_at).label('event_date'),
        AnalyticsEvent.event_name,
        AnalyticsEvent.programme_id,
        AnalyticsEvent.discussion_id,
        AnalyticsEvent.cohort_slug,
        AnalyticsEvent.country,
        func.count(AnalyticsEvent.id).label('event_count'),
        func.count(distinct(AnalyticsEvent.user_id)).label('unique_users'),
    ).filter(
        and_(
            AnalyticsEvent.created_at >= start_time,
            AnalyticsEvent.event_name.in_(list(CANONICAL_EVENT_NAMES))
        )
    ).group_by(
        func.date(AnalyticsEvent.created_at),
        AnalyticsEvent.event_name,
        AnalyticsEvent.programme_id,
        AnalyticsEvent.discussion_id,
        AnalyticsEvent.cohort_slug,
        AnalyticsEvent.country,
    ).all()

    for row in rows:
        aggregate = AnalyticsDailyAggregate(
            event_date=row.event_date,
            event_name=row.event_name,
            programme_id=row.programme_id,
            discussion_id=row.discussion_id,
            cohort_slug=row.cohort_slug,
            country=row.country,
            event_count=int(row.event_count or 0),
            unique_users=int(row.unique_users or 0),
        )
        db.session.add(aggregate)

    db.session.commit()
    return len(rows)


def event_context_for_discussion(discussion_id):
    discussion = db.session.get(Discussion, discussion_id) if discussion_id else None
    return {
        'discussion_id': discussion.id if discussion else None,
        'programme_id': discussion.programme_id if discussion else None,
        'country': discussion.country if discussion else None,
    }
