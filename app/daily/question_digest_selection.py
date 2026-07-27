"""
Scored selection of published daily questions for digest emails.

The Tuesday weekly question digest (``DailyQuestionSubscriber.email_frequency='weekly'``)
does **not** include every question the reader missed — it picks the top *N* by an
engagement score from a rolling window. The weekly **brief** participation CTA reuses
the same scorer but scopes to the edition's ``week_start`` / ``week_end`` bounds.

See ``select_questions_for_weekly_digest`` in ``app.daily.auto_selection`` (re-exported
for backwards compatibility) and ``app.scheduler._run_weekly_digest_in_thread``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from flask import current_app

from app.lib.time import utcnow_naive
from app.models import DailyQuestion, DailyQuestionResponse, StatementVote


@dataclass(frozen=True)
class DigestScoringProfile:
    """Weights for ranking questions inside a date window."""

    discussion_boost: float = 0.4
    activity_boost: float = 0.2
    activity_window: timedelta = timedelta(hours=24)
    recency_weight: float = 0.2
    recency_decay: float = 0.3
    response_cap: float = 0.2
    response_divisor: float = 50.0
    high_engagement_threshold: int = 0
    high_engagement_boost: float = 0.0


WEEKLY_DIGEST_PROFILE = DigestScoringProfile()

MONTHLY_DIGEST_PROFILE = DigestScoringProfile(
    discussion_boost=0.3,
    activity_window=timedelta(days=7),
    recency_weight=0.15,
    recency_decay=0.2,
    response_cap=0.25,
    response_divisor=100.0,
    high_engagement_threshold=20,
    high_engagement_boost=0.1,
)


def score_question_for_digest(
    question: DailyQuestion,
    *,
    window_start: date,
    window_end: date,
    reference_date: Optional[date] = None,
    profile: DigestScoringProfile = WEEKLY_DIGEST_PROFILE,
) -> float:
    """Return a higher-is-better engagement score for *question* in the window."""
    ref = reference_date or date.today()
    window_days = max((window_end - window_start).days, 1)

    score = 0.0

    if question.source_discussion_id:
        score += profile.discussion_boost

        activity_cutoff = utcnow_naive() - profile.activity_window
        recent_activity = StatementVote.query.filter(
            StatementVote.discussion_id == question.source_discussion_id,
            StatementVote.created_at >= activity_cutoff,
        ).first()
        if recent_activity:
            score += profile.activity_boost

    days_old = max((ref - question.question_date).days, 0)
    recency_score = 1.0 - (days_old / window_days) * profile.recency_decay
    score += recency_score * profile.recency_weight

    response_count = DailyQuestionResponse.query.filter_by(
        daily_question_id=question.id,
    ).count()
    if response_count > 0:
        score += min(response_count / profile.response_divisor, profile.response_cap)

    if profile.high_engagement_threshold and response_count > profile.high_engagement_threshold:
        score += profile.high_engagement_boost

    return score


def select_questions_in_date_range(
    start_date: date,
    end_date: date,
    *,
    count: int = 5,
    reference_date: Optional[date] = None,
    profile: DigestScoringProfile = WEEKLY_DIGEST_PROFILE,
) -> List[DailyQuestion]:
    """
    Top *count* published questions between *start_date* and *end_date* inclusive.

    Returns an empty list when no published questions exist in the window.
    """
    if count < 1:
        return []

    questions = DailyQuestion.query.filter(
        DailyQuestion.question_date >= start_date,
        DailyQuestion.question_date <= end_date,
        DailyQuestion.status == 'published',
    ).order_by(DailyQuestion.question_date.desc()).all()

    if not questions:
        current_app.logger.warning(
            "No published questions found between %s and %s",
            start_date,
            end_date,
        )
        return []

    ref = reference_date or date.today()
    scored = [
        (
            question,
            score_question_for_digest(
                question,
                window_start=start_date,
                window_end=end_date,
                reference_date=ref,
                profile=profile,
            ),
        )
        for question in questions
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    selected = [question for question, _score in scored[:count]]

    current_app.logger.info(
        "Selected %d question(s) for digest (%s to %s, from %d available)",
        len(selected),
        start_date,
        end_date,
        len(questions),
    )
    return selected


def select_questions_for_weekly_digest(days_back: int = 7, count: int = 5) -> List[DailyQuestion]:
    """Rolling weekly digest window ending today (Tuesday send job)."""
    end = date.today()
    start = end - timedelta(days=days_back)
    return select_questions_in_date_range(start, end, count=count, profile=WEEKLY_DIGEST_PROFILE)


def select_questions_for_monthly_digest(days_back: int = 30, count: int = 10) -> List[DailyQuestion]:
    """Rolling monthly digest window ending today."""
    end = date.today()
    start = end - timedelta(days=days_back)
    return select_questions_in_date_range(start, end, count=count, profile=MONTHLY_DIGEST_PROFILE)


def select_best_question_for_week(
    week_start: date,
    week_end: date,
) -> Optional[DailyQuestion]:
    """Single best question for a weekly brief edition's participation CTA."""
    selected = select_questions_in_date_range(
        week_start,
        week_end,
        count=1,
        reference_date=week_end,
        profile=WEEKLY_DIGEST_PROFILE,
    )
    return selected[0] if selected else None
