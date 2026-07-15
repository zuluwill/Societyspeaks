"""
Independent acceptance tests for brief-sourced daily-question selection.

Contract: docs/analysis/brief-sourced-daily-question-acceptance.md

Context: the trending-source path existed for the platform's whole life and
produced zero production questions because it only ran when the discussion pool
was empty (it never is). The risk being guarded is not a wrong diff — it is a
DORMANT path. So these tests assert observable behaviour of the real production
entry points, not implementation details.

Design note (reconciled with the shipped implementation): the brief path is
CLOCK-CONSTRAINED — tomorrow's question is drawn from today's brief. It fires
only when a ``question_date`` is supplied (``select_next_question_source`` skips
briefs when called bare), and the production wiring goes through
``schedule_question_from_brief(brief_date=today)``. These tests therefore drive
the same seam production does: a brief on day D must produce a labelled,
brief-sourced question for day D+1.
"""

from datetime import date, timedelta

import pytest

from app import db as _db_singleton
from app.lib.time import utcnow_naive


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_discussion(db, title, topic='Politics', partner_env='live'):
    from app.models import Discussion
    d = Discussion(title=title, topic=topic, partner_env=partner_env)
    db.session.add(d)
    db.session.flush()
    return d


def _make_seed_statement(db, content, discussion):
    from app.models import Statement
    s = Statement(content=content, discussion_id=discussion.id, is_seed=True)
    db.session.add(s)
    db.session.flush()
    return s


def _make_published_topic(db, title, *, civic_score=0.8, primary_topic='Politics',
                          seed_statements=None):
    from app.models import TrendingTopic
    t = TrendingTopic(
        title=title,
        status='published',
        civic_score=civic_score,
        quality_score=0.7,
        primary_topic=primary_topic,
        risk_flag=False,
        seed_statements=seed_statements or [
            {'content': f'The government should act decisively on {title}.',
             'position': 'pro'},
        ],
        created_at=utcnow_naive(),
    )
    db.session.add(t)
    db.session.flush()
    return t


def _make_brief_item_for_topic(db, topic, *, coverage_imbalance=0.8,
                               is_underreported=False, brief_date=None, position=1):
    """Promote a topic into a published brief item carrying coverage metadata."""
    from app.models import DailyBrief, BriefItem
    brief_date = brief_date or date.today()
    brief = DailyBrief.query.filter_by(date=brief_date, brief_type='daily').first()
    if brief is None:
        brief = DailyBrief(date=brief_date, brief_type='daily', status='published',
                           title="Test brief")
        db.session.add(brief)
        db.session.flush()
    item = BriefItem(
        brief_id=brief.id,
        position=position,
        section='lead',
        depth='full',
        trending_topic_id=topic.id,
        headline=topic.title,
        coverage_imbalance=coverage_imbalance,
        coverage_distribution={'left': 0.8, 'center': 0.15, 'right': 0.05},
        source_count=2,
        is_underreported=is_underreported,
    )
    db.session.add(item)
    db.session.flush()
    return brief, item


def _seed_eligible_discussion_pool(db):
    """Guarantee the discussion path is non-empty, so 'chose a discussion' is a
    real alternative the brief path must beat (not 'chose nothing')."""
    disc = _make_discussion(db, 'Baseline civic discussion about tax policy', 'Economy')
    _make_seed_statement(db, 'Taxes on high earners should rise to fund services.', disc)
    return disc


# ---------------------------------------------------------------------------
# 5. Fallback preserved — no brief items → existing behaviour intact
# ---------------------------------------------------------------------------

def test_fallback_to_discussion_when_no_brief_items(db):
    from app.daily.auto_selection import select_next_question_source

    _seed_eligible_discussion_pool(db)
    db.session.commit()

    tomorrow = date.today() + timedelta(days=1)
    source_info = select_next_question_source(question_date=tomorrow)
    assert source_info is not None, "selection must still produce a question with no briefs"
    assert source_info['source_type'] in ('discussion', 'statement', 'trending')
    assert source_info.get('question_text')


# ---------------------------------------------------------------------------
# 1 + 2. Preference and labelling via the real production hook
# ---------------------------------------------------------------------------

def test_brief_promoted_topic_is_preferred_over_discussions(db):
    """A brief on day D must drive day D+1's question to its topic, not the
    discussion pool."""
    from app.daily.auto_selection import select_next_question_source

    _seed_eligible_discussion_pool(db)
    today = date.today()
    topic = _make_published_topic(db, 'National grid investment')
    _make_brief_item_for_topic(db, topic, coverage_imbalance=0.85, brief_date=today)
    db.session.commit()

    source_info = select_next_question_source(question_date=today + timedelta(days=1))
    assert source_info is not None
    assert source_info['source_type'] == 'brief', (
        f"expected brief-sourced selection, got {source_info['source_type']} "
        "(dormant-path regression)"
    )
    assert source_info['source_trending_topic_id'] == topic.id


def test_schedule_from_brief_labels_tomorrows_question(db):
    """The production hook: today's brief wires tomorrow's question with full
    provenance (source_trending_topic_id + source_brief_item_id + coverage_frame_json).
    This is the field set the dormancy monitor keys on."""
    from app.daily.auto_selection import schedule_question_from_brief

    today = date.today()
    topic = _make_published_topic(db, 'Water regulation overhaul')
    _brief, item = _make_brief_item_for_topic(db, topic, coverage_imbalance=0.9, brief_date=today)
    db.session.commit()

    question = schedule_question_from_brief(brief_date=today)
    assert question is not None, "brief hook must wire a question when eligible items exist"

    _db_singleton.session.expire_all()
    from app.models import DailyQuestion
    reloaded = _db_singleton.session.get(DailyQuestion, question.id)
    assert reloaded.question_date == today + timedelta(days=1)
    assert reloaded.source_type == 'brief'
    assert reloaded.source_trending_topic_id == topic.id
    assert reloaded.source_brief_item_id == item.id
    assert reloaded.coverage_frame_json, "coverage frame snapshot must be persisted"


# ---------------------------------------------------------------------------
# 3. Commensurability snapshot carries the axis the question was posed against
# ---------------------------------------------------------------------------

def test_selection_captures_coverage_frame(db):
    from app.daily.auto_selection import select_next_question_source

    _seed_eligible_discussion_pool(db)
    today = date.today()
    topic = _make_published_topic(db, 'Housing supply reform')
    _make_brief_item_for_topic(db, topic, coverage_imbalance=0.77, brief_date=today)
    db.session.commit()

    source_info = select_next_question_source(question_date=today + timedelta(days=1))
    frame = source_info.get('coverage_frame')
    assert frame, "selection must carry a coverage_frame snapshot (acceptance doc §4)"
    assert frame.get('coverage_imbalance') == pytest.approx(0.77)
    assert 'dominant_frame' in frame


# ---------------------------------------------------------------------------
# 4. Ranking — higher imbalance is preferred (weighted, not deterministic)
# ---------------------------------------------------------------------------

def test_higher_imbalance_topic_wins_majority(db):
    import random
    from app.daily.auto_selection import select_next_question_source

    _seed_eligible_discussion_pool(db)
    today = date.today()
    high = _make_published_topic(db, 'High imbalance story')
    low = _make_published_topic(db, 'Low imbalance story')
    _make_brief_item_for_topic(db, high, coverage_imbalance=0.95, position=1, brief_date=today)
    _make_brief_item_for_topic(db, low, coverage_imbalance=0.15, position=2, brief_date=today)
    db.session.commit()

    random.seed(1234)
    runs = 25
    high_wins = 0
    for _ in range(runs):
        info = select_next_question_source(question_date=today + timedelta(days=1))
        if info and info.get('source_trending_topic_id') == high.id:
            high_wins += 1

    assert high_wins > runs * 0.6, (
        f"high-imbalance topic won only {high_wins}/{runs}; expected a clear majority"
    )


# ---------------------------------------------------------------------------
# The dormancy guard itself must raise when eligible items exist but the
# question is not brief-sourced (the exact failure that hid for a year).
# ---------------------------------------------------------------------------

def test_wiring_guard_raises_on_dormant_question(db):
    from app.models import DailyQuestion
    from app.daily.auto_selection import (
        verify_brief_sourced_question_wiring, BriefQuestionWiringError,
    )

    today = date.today()
    topic = _make_published_topic(db, 'Rail fare policy')
    _make_brief_item_for_topic(db, topic, coverage_imbalance=0.8, brief_date=today)

    # Simulate the dormant path: tomorrow's question exists but is discussion-sourced.
    stale = DailyQuestion(
        question_date=today + timedelta(days=1),
        question_number=1,
        question_text='A stale, non-brief question',
        source_type='discussion',
        status='scheduled',
    )
    db.session.add(stale)
    db.session.commit()

    with pytest.raises(BriefQuestionWiringError):
        verify_brief_sourced_question_wiring(brief_date=today)


def test_wiring_guard_ok_when_no_eligible_items(db):
    """No eligible brief items → guard is a no-op (skipped), not a failure."""
    from app.daily.auto_selection import verify_brief_sourced_question_wiring

    result = verify_brief_sourced_question_wiring(brief_date=date.today())
    assert result['ok'] is True
    assert result.get('skipped') is True
