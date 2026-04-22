"""
Analytics event stream and daily rollup tables.

AnalyticsEvent is an immutable raw event log; AnalyticsDailyAggregate is
the pre-aggregated dashboard view. Moved here from app/models.py as
part of the models-split refactor. All foreign keys (User, Programme,
Discussion, Statement) are plain table-name strings, so this submodule
has no cross-submodule imports.
"""

from app import db
from app.lib.time import utcnow_naive


class AnalyticsEvent(db.Model):
    """Immutable raw analytics event stream for warehouse-style processing."""
    __tablename__ = 'analytics_event'
    __table_args__ = (
        db.Index('idx_analytics_event_name_created', 'event_name', 'created_at'),
        db.Index('idx_analytics_event_programme_created', 'programme_id', 'created_at'),
        # Covers the funnel COUNT(DISTINCT user_id) queries that filter on both
        # programme_id and event_name — avoids full-programme table scans at scale.
        db.Index('idx_analytics_event_programme_name_user', 'programme_id', 'event_name', 'user_id'),
        db.Index('idx_analytics_event_discussion_created', 'discussion_id', 'created_at'),
        db.Index('idx_analytics_event_user_created', 'user_id', 'created_at'),
        db.Index('idx_analytics_event_cohort_created', 'cohort_slug', 'created_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    event_name = db.Column(db.String(64), nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id'), nullable=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=True)
    cohort_slug = db.Column(db.String(80), nullable=True)
    country = db.Column(db.String(80), nullable=True)

    source = db.Column(db.String(50), nullable=True)
    event_metadata = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)


class AnalyticsDailyAggregate(db.Model):
    """Curated aggregate table for NSP dashboard queries."""
    __tablename__ = 'analytics_daily_aggregate'
    __table_args__ = (
        db.Index('idx_analytics_daily_lookup', 'event_date', 'event_name', 'programme_id'),
        db.Index('idx_analytics_daily_discussion', 'discussion_id', 'event_date'),
        db.UniqueConstraint(
            'event_date',
            'event_name',
            'programme_id',
            'discussion_id',
            'cohort_slug',
            'country',
            name='uq_analytics_daily_dims'
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    event_date = db.Column(db.Date, nullable=False)
    event_name = db.Column(db.String(64), nullable=False)

    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id'), nullable=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    cohort_slug = db.Column(db.String(80), nullable=True)
    country = db.Column(db.String(80), nullable=True)

    event_count = db.Column(db.Integer, nullable=False, default=0)
    unique_users = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)
