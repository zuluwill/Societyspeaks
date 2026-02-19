"""
Daily Question Analytics Service.

Centralized analytics helpers for admin reporting to keep routes/templates DRY.
"""

from datetime import datetime, timedelta
from app.lib.time import utcnow_naive
from typing import Dict, Any, List

from sqlalchemy import func, case

from app import db
from app.models import DailyQuestion, DailyQuestionResponse


class DailyQuestionAnalytics:
    """Analytics service for daily question engagement quality."""

    VALID_PERIODS = {7, 14, 30, 90}
    CONFIDENCE_LEVELS = ('low', 'medium', 'high')
    REASON_TAGS = (
        'evidence', 'fairness', 'cost', 'feasibility', 'rights',
        'safety', 'trust', 'long_term_impact', 'other'
    )

    @classmethod
    def normalize_days(cls, days: int) -> int:
        """Clamp analytics periods to known safe defaults."""
        return days if days in cls.VALID_PERIODS else 30

    @staticmethod
    def _pct(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round((numerator / denominator) * 100, 1)

    @classmethod
    def _base_query(cls, days: int):
        cutoff = utcnow_naive() - timedelta(days=days)
        return DailyQuestionResponse.query.join(
            DailyQuestion, DailyQuestionResponse.daily_question_id == DailyQuestion.id
        ).filter(
            DailyQuestionResponse.created_at >= cutoff
        )

    @classmethod
    def get_dashboard_stats(cls, days: int = 30) -> Dict[str, Any]:
        """
        Return daily-question quality and engagement stats for admin dashboard.
        """
        days = cls.normalize_days(days)
        base = cls._base_query(days)

        total_responses = base.count()
        responses_with_reason = base.filter(
            DailyQuestionResponse.reason.isnot(None),
            DailyQuestionResponse.reason != ''
        ).count()
        unsure_responses = base.filter(DailyQuestionResponse.vote == 0).count()
        context_expanded_count = base.filter(DailyQuestionResponse.context_expanded.is_(True)).count()

        avg_source_clicks = db.session.query(
            func.avg(DailyQuestionResponse.source_link_click_count)
        ).join(
            DailyQuestion, DailyQuestionResponse.daily_question_id == DailyQuestion.id
        ).filter(
            DailyQuestionResponse.created_at >= utcnow_naive() - timedelta(days=days)
        ).scalar() or 0.0

        # Confidence distribution
        confidence_raw = db.session.query(
            DailyQuestionResponse.confidence_level,
            func.count(DailyQuestionResponse.id)
        ).join(
            DailyQuestion, DailyQuestionResponse.daily_question_id == DailyQuestion.id
        ).filter(
            DailyQuestionResponse.created_at >= utcnow_naive() - timedelta(days=days),
            DailyQuestionResponse.confidence_level.isnot(None)
        ).group_by(DailyQuestionResponse.confidence_level).all()
        confidence_map = {level: count for level, count in confidence_raw if level}

        confidence = []
        confidence_total = sum(confidence_map.values())
        for level in cls.CONFIDENCE_LEVELS:
            count = confidence_map.get(level, 0)
            confidence.append({
                'level': level,
                'count': count,
                'pct_of_confidence_responses': cls._pct(count, confidence_total),
                'pct_of_all_responses': cls._pct(count, total_responses),
            })

        # Reason tag distribution
        tag_raw = db.session.query(
            DailyQuestionResponse.reason_tag,
            func.count(DailyQuestionResponse.id)
        ).join(
            DailyQuestion, DailyQuestionResponse.daily_question_id == DailyQuestion.id
        ).filter(
            DailyQuestionResponse.created_at >= utcnow_naive() - timedelta(days=days),
            DailyQuestionResponse.reason_tag.isnot(None)
        ).group_by(DailyQuestionResponse.reason_tag).all()
        tag_map = {tag: count for tag, count in tag_raw if tag}
        tags = []
        tags_total = sum(tag_map.values())
        for tag in cls.REASON_TAGS:
            count = tag_map.get(tag, 0)
            tags.append({
                'tag': tag,
                'count': count,
                'pct': cls._pct(count, tags_total)
            })
        tags.sort(key=lambda x: x['count'], reverse=True)

        # Context impact: unsure rate by context engagement
        context_rows = db.session.query(
            DailyQuestionResponse.context_expanded,
            func.count(DailyQuestionResponse.id).label('total'),
            func.sum(case((DailyQuestionResponse.vote == 0, 1), else_=0)).label('unsure_count')
        ).join(
            DailyQuestion, DailyQuestionResponse.daily_question_id == DailyQuestion.id
        ).filter(
            DailyQuestionResponse.created_at >= utcnow_naive() - timedelta(days=days)
        ).group_by(DailyQuestionResponse.context_expanded).all()

        context_impact = {
            'expanded': {'total': 0, 'unsure': 0, 'unsure_rate': 0.0},
            'not_expanded': {'total': 0, 'unsure': 0, 'unsure_rate': 0.0}
        }
        for expanded, total, unsure_count in context_rows:
            key = 'expanded' if expanded else 'not_expanded'
            unsure_count = unsure_count or 0
            context_impact[key] = {
                'total': total,
                'unsure': unsure_count,
                'unsure_rate': cls._pct(unsure_count, total)
            }

        # Source type performance
        source_rows = db.session.query(
            DailyQuestion.source_type,
            func.count(DailyQuestionResponse.id).label('responses'),
            func.sum(case((DailyQuestionResponse.vote == 0, 1), else_=0)).label('unsure_count'),
            func.avg(case((DailyQuestionResponse.reason.isnot(None), 1), else_=0)).label('reason_rate')
        ).join(
            DailyQuestionResponse, DailyQuestionResponse.daily_question_id == DailyQuestion.id
        ).filter(
            DailyQuestionResponse.created_at >= utcnow_naive() - timedelta(days=days)
        ).group_by(DailyQuestion.source_type).all()
        source_type_stats: List[Dict[str, Any]] = []
        for source_type, responses, unsure_count, reason_rate in source_rows:
            unsure_count = unsure_count or 0
            source_type_stats.append({
                'source_type': source_type or 'unknown',
                'responses': responses,
                'unsure_rate': cls._pct(unsure_count, responses),
                'reason_rate': round((reason_rate or 0) * 100, 1)
            })
        source_type_stats.sort(key=lambda x: x['responses'], reverse=True)

        return {
            'days': days,
            'overview': {
                'total_responses': total_responses,
                'responses_with_reason': responses_with_reason,
                'reason_rate': cls._pct(responses_with_reason, total_responses),
                'unsure_rate': cls._pct(unsure_responses, total_responses),
                'context_expanded_rate': cls._pct(context_expanded_count, total_responses),
                'avg_source_link_clicks': round(float(avg_source_clicks), 2),
            },
            'confidence': confidence,
            'tags': tags,
            'context_impact': context_impact,
            'source_type_stats': source_type_stats,
        }
