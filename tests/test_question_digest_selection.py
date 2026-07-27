"""Question digest selection: scoring and top-N picks from a date window."""

from datetime import date, timedelta

from app.daily.question_digest_selection import (
    score_question_for_digest,
    select_best_question_for_week,
    select_questions_for_weekly_digest,
    select_questions_in_date_range,
)
from app.models import DailyQuestion, DailyQuestionResponse, Discussion, StatementVote
from app.lib.time import utcnow_naive


def _question(db, qdate, *, number, text='Should we test?', discussion_id=None, status='published'):
    q = DailyQuestion(
        question_date=qdate,
        question_number=number,
        question_text=text,
        status=status,
        source_type='discussion',
        source_discussion_id=discussion_id,
    )
    db.session.add(q)
    db.session.flush()
    return q


def _discussion(db, title='Test discussion'):
    d = Discussion(
        title=title,
        slug=title.lower().replace(' ', '-'),
        geographic_scope='global',
    )
    db.session.add(d)
    db.session.flush()
    return d


def _responses(db, question, count):
    for i in range(count):
        db.session.add(
            DailyQuestionResponse(
                daily_question_id=question.id,
                vote=1,
                session_fingerprint=f'fp-{question.id}-{i}',
            )
        )
    db.session.flush()


# --------------------------------------------------------------------------
# Top-N behaviour (not "all missed questions")
# --------------------------------------------------------------------------

def test_weekly_digest_returns_at_most_count(db):
    """Seven questions in the window → only five ship in the digest."""
    start = date(2026, 7, 20)
    for i in range(7):
        _question(db, start + timedelta(days=i), number=100 + i, text=f'Q{i}')
    db.session.commit()

    selected = select_questions_for_weekly_digest(days_back=7, count=5)
    assert len(selected) == 5


def test_weekly_digest_prefers_discussion_linked(db):
    start = date(2026, 7, 20)
    disc = _discussion(db)
    plain = _question(db, start, number=1, text='Plain')
    linked = _question(db, start + timedelta(days=1), number=2, text='Linked', discussion_id=disc.id)
    db.session.commit()

    selected = select_questions_in_date_range(start, start + timedelta(days=6), count=1)
    assert selected[0].id == linked.id
    assert selected[0].id != plain.id


def test_weekly_digest_prefers_more_responses(db):
    start = date(2026, 7, 20)
    low = _question(db, start, number=1, text='Low engagement')
    high = _question(db, start + timedelta(days=1), number=2, text='High engagement')
    _responses(db, high, 40)
    db.session.commit()

    selected = select_questions_in_date_range(start, start + timedelta(days=6), count=1)
    assert selected[0].id == high.id


def test_weekly_digest_boosts_recent_discussion_activity(db):
    start = date(2026, 7, 20)
    disc = _discussion(db)
    quiet = _question(db, start, number=1, text='Quiet linked', discussion_id=disc.id)
    active_disc = _discussion(db, title='Active')
    active = _question(
        db, start + timedelta(days=1), number=2, text='Active linked', discussion_id=active_disc.id,
    )

    from app.models import Statement, StatementVote

    stmt = Statement(discussion_id=active_disc.id, content='A claim with enough length here.')
    db.session.add(stmt)
    db.session.flush()
    db.session.add(
        StatementVote(
            discussion_id=active_disc.id,
            statement_id=stmt.id,
            vote=1,
            session_fingerprint='recent-voter',
            created_at=utcnow_naive(),
        )
    )
    db.session.commit()

    selected = select_questions_in_date_range(start, start + timedelta(days=6), count=1)
    assert selected[0].id == active.id
    assert selected[0].id != quiet.id


def test_best_question_for_week_uses_edition_bounds_not_rolling_today(db):
    """Weekly brief stance must not pull from outside the edition week."""
    week_start = date(2026, 7, 20)
    week_end = date(2026, 7, 26)

    older = _question(db, week_start - timedelta(days=1), number=1, text='Before week')
    in_week = _question(db, week_start + timedelta(days=2), number=2, text='In week')
    db.session.commit()

    best = select_best_question_for_week(week_start, week_end)
    assert best is not None
    assert best.id == in_week.id
    assert best.id != older.id


def test_score_question_is_deterministic(db):
    qdate = date(2026, 7, 21)
    q = _question(db, qdate, number=1)
    db.session.commit()

    window_start = date(2026, 7, 20)
    window_end = date(2026, 7, 26)
    a = score_question_for_digest(q, window_start=window_start, window_end=window_end)
    b = score_question_for_digest(q, window_start=window_start, window_end=window_end)
    assert a == b


# --------------------------------------------------------------------------
# Refactor equivalence
#
# This module replaced ~150 lines of inline scoring in app/daily/auto_selection.py
# that drive live Tuesday sends. The weights below are transcribed from that
# original implementation; if a profile value drifts, the digest silently starts
# picking different questions with nothing else to catch it.
# --------------------------------------------------------------------------

import pytest

from app.daily.question_digest_selection import (
    MONTHLY_DIGEST_PROFILE,
    WEEKLY_DIGEST_PROFILE,
)


def test_weekly_profile_matches_the_original_inline_weights():
    p = WEEKLY_DIGEST_PROFILE
    assert p.discussion_boost == 0.4
    assert p.activity_boost == 0.2
    assert p.activity_window == timedelta(hours=24)
    assert p.recency_weight == 0.2
    assert p.recency_decay == 0.3
    assert p.response_divisor == 50.0
    assert p.response_cap == 0.2
    # The weekly path had no high-engagement bonus; a falsey threshold disables it.
    assert not p.high_engagement_threshold


def test_monthly_profile_matches_the_original_inline_weights():
    p = MONTHLY_DIGEST_PROFILE
    assert p.discussion_boost == 0.3
    assert p.activity_boost == 0.2
    assert p.activity_window == timedelta(days=7)
    assert p.recency_weight == 0.15
    assert p.recency_decay == 0.2
    assert p.response_divisor == 100.0
    assert p.response_cap == 0.25
    assert p.high_engagement_threshold == 20
    assert p.high_engagement_boost == 0.1


def test_weekly_score_reproduces_the_original_formula(db):
    """Recomputes the pre-refactor arithmetic by hand and compares."""
    window_start, window_end = date(2026, 7, 20), date(2026, 7, 27)
    q = _question(db, date(2026, 7, 24), number=200)
    _responses(db, q, 10)
    db.session.commit()

    actual = score_question_for_digest(
        q, window_start=window_start, window_end=window_end,
        reference_date=window_end,
    )

    # Original: no discussion → no 0.4/0.2; recency 1-(days_old/7)*0.3 weighted 0.2;
    # responses min(10/50, 0.2).
    days_old = (window_end - q.question_date).days       # 3
    expected = (1.0 - (days_old / 7) * 0.3) * 0.2 + min(10 / 50, 0.2)
    assert actual == pytest.approx(expected)


def test_monthly_high_engagement_bonus_applies_above_the_threshold(db):
    """daily_question.question_date is UNIQUE, so this scores one question twice
    across the threshold rather than comparing two same-day questions."""
    window_start, window_end = date(2026, 7, 1), date(2026, 7, 31)
    q = _question(db, date(2026, 7, 15), number=201)
    _responses(db, q, 20)          # not > 20
    db.session.commit()

    kwargs = dict(
        window_start=window_start, window_end=window_end,
        reference_date=window_end, profile=MONTHLY_DIGEST_PROFILE,
    )
    below = score_question_for_digest(q, **kwargs)

    db.session.add(DailyQuestionResponse(
        daily_question_id=q.id, vote=1, session_fingerprint='fp-extra',
    ))                             # 21 responses → > 20
    db.session.commit()
    above = score_question_for_digest(q, **kwargs)

    # 0.1 bonus plus the extra response (1/100, well under the 0.25 cap).
    assert above - below == pytest.approx(0.1 + 0.01)


def test_weekly_profile_has_no_high_engagement_bonus(db):
    """The weekly path must not inherit the monthly bonus via the shared scorer."""
    window_start, window_end = date(2026, 7, 20), date(2026, 7, 27)
    q = _question(db, date(2026, 7, 24), number=203)
    _responses(db, q, 20)
    db.session.commit()

    kwargs = dict(window_start=window_start, window_end=window_end, reference_date=window_end)
    below = score_question_for_digest(q, **kwargs)

    db.session.add(DailyQuestionResponse(
        daily_question_id=q.id, vote=1, session_fingerprint='fp-extra',
    ))
    db.session.commit()
    above = score_question_for_digest(q, **kwargs)

    # Zero movement is the proof: crossing the monthly threshold (20 → 21)
    # adds nothing under the weekly profile, and its response term is already
    # pinned at the 0.2 cap (saturated from 10 responses at divisor 50).
    assert above - below == pytest.approx(0.0)
    assert above == pytest.approx(below)


# --------------------------------------------------------------------------
# Window bounds — "last 7 days", not "everything you missed"
# --------------------------------------------------------------------------

def test_questions_older_than_the_window_are_excluded(db):
    """Nothing is backfilled: a question that fell out of the window is gone for good."""
    today = date.today()
    inside = _question(db, today - timedelta(days=3), number=300, text='Inside window')
    _question(db, today - timedelta(days=30), number=301, text='Long past')
    db.session.commit()

    selected = select_questions_for_weekly_digest(days_back=7, count=5)

    assert [q.id for q in selected] == [inside.id]


def test_unpublished_questions_are_excluded(db):
    today = date.today()
    published = _question(db, today - timedelta(days=1), number=302)
    _question(db, today - timedelta(days=2), number=303, status='draft')
    db.session.commit()

    selected = select_questions_for_weekly_digest(days_back=7, count=5)
    assert [q.id for q in selected] == [published.id]


def test_future_dated_questions_are_excluded(db):
    today = date.today()
    current = _question(db, today - timedelta(days=1), number=304)
    _question(db, today + timedelta(days=2), number=305, text='Scheduled ahead')
    db.session.commit()

    selected = select_questions_for_weekly_digest(days_back=7, count=5)
    assert [q.id for q in selected] == [current.id]


def test_empty_window_returns_empty_list_not_an_error(db):
    assert select_questions_for_weekly_digest(days_back=7, count=5) == []
    assert select_best_question_for_week(date(2026, 1, 1), date(2026, 1, 7)) is None


def test_count_below_one_selects_nothing(db):
    _question(db, date.today(), number=306)
    db.session.commit()
    assert select_questions_in_date_range(
        date.today() - timedelta(days=7), date.today(), count=0
    ) == []
