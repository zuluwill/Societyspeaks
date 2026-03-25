"""
Tests for daily question eligibility filtering.

Coverage:
- DAILY_QUESTION_CATEGORIES: correct set of civic categories, no Sport
- MIN_CIVIC_SCORE_FOR_CULTURE: higher than the general MIN_CIVIC_SCORE
- PRIORITY_TOPICS: civic categories outrank Culture
- Scoring helpers: calculate_timeliness_score, calculate_clarity_score,
  calculate_controversy_potential (pure functions, no DB needed)
- get_topic_priority_boost: correct multipliers
- get_eligible_discussions: DB query respects category allowlist
- get_eligible_trending_topics: DB query applies per-category civic thresholds
- get_eligible_statements: DB query excludes non-civic discussion categories
"""

import math
import pytest
from datetime import timedelta
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Constants contract tests
# ---------------------------------------------------------------------------

class TestDailyQuestionCategoriesConstant:
    """DAILY_QUESTION_CATEGORIES must contain all civic topics and exclude Sport."""

    def _categories(self):
        from app.daily.auto_selection import DAILY_QUESTION_CATEGORIES
        return DAILY_QUESTION_CATEGORIES

    def test_contains_all_civic_categories(self):
        cats = self._categories()
        for expected in ('Politics', 'Geopolitics', 'Economy', 'Society',
                         'Healthcare', 'Environment', 'Education',
                         'Technology', 'Infrastructure', 'Business'):
            assert expected in cats, f"Expected civic category '{expected}' to be in DAILY_QUESTION_CATEGORIES"

    def test_contains_culture(self):
        assert 'Culture' in self._categories()

    def test_excludes_sport(self):
        assert 'Sport' not in self._categories()

    def test_all_entries_are_valid_discussion_topics(self):
        """Every category in the allowlist must be a valid Discussion.topic value."""
        from app.daily.auto_selection import DAILY_QUESTION_CATEGORIES
        from app.models import Discussion
        for cat in DAILY_QUESTION_CATEGORIES:
            assert cat in Discussion.TOPICS, (
                f"'{cat}' is in DAILY_QUESTION_CATEGORIES but not in Discussion.TOPICS"
            )

    def test_is_a_set_or_set_like(self):
        cats = self._categories()
        assert hasattr(cats, '__contains__'), "DAILY_QUESTION_CATEGORIES must support 'in' operator"

    def test_no_duplicates(self):
        cats = self._categories()
        as_list = list(cats)
        assert len(as_list) == len(set(as_list)), "DAILY_QUESTION_CATEGORIES must not have duplicates"


class TestCivicScoreThresholds:
    """Culture's civic threshold must be stricter than the general threshold."""

    def test_culture_threshold_is_higher_than_general(self):
        from app.daily.auto_selection import MIN_CIVIC_SCORE, MIN_CIVIC_SCORE_FOR_CULTURE
        assert MIN_CIVIC_SCORE_FOR_CULTURE > MIN_CIVIC_SCORE, (
            "Culture requires a higher civic score than the general minimum"
        )

    def test_general_threshold_is_half(self):
        from app.daily.auto_selection import MIN_CIVIC_SCORE
        assert MIN_CIVIC_SCORE == 0.5


class TestPriorityTopicsConfig:
    """Civic categories must outrank Culture and not include Sport."""

    def _boosts(self):
        from app.daily.auto_selection import PRIORITY_TOPICS
        return PRIORITY_TOPICS

    def test_politics_outranks_culture(self):
        b = self._boosts()
        assert b['Politics'] > b['Culture']

    def test_geopolitics_outranks_culture(self):
        b = self._boosts()
        assert b['Geopolitics'] > b['Culture']

    def test_economy_outranks_culture(self):
        b = self._boosts()
        assert b['Economy'] > b['Culture']

    def test_sport_not_in_priority_topics(self):
        assert 'Sport' not in self._boosts()

    def test_all_priorities_are_positive(self):
        for category, boost in self._boosts().items():
            assert boost > 0, f"Priority boost for '{category}' must be positive"

    def test_no_category_above_two(self):
        """Multipliers above 2.0 would over-weight a single category."""
        for category, boost in self._boosts().items():
            assert boost <= 2.0, f"Priority boost for '{category}' ({boost}) is unreasonably large"


# ---------------------------------------------------------------------------
# Pure scoring function tests (no DB required)
# ---------------------------------------------------------------------------

class TestGetTopicPriorityBoost:
    """get_topic_priority_boost must return the configured multiplier."""

    def _boost(self, topic):
        from app.daily.auto_selection import get_topic_priority_boost
        return get_topic_priority_boost(topic)

    def test_none_returns_one(self):
        assert self._boost(None) == 1.0

    def test_politics_returns_high_boost(self):
        assert self._boost('Politics') > 1.0

    def test_culture_returns_below_one(self):
        assert self._boost('Culture') < 1.0

    def test_unknown_category_returns_one(self):
        assert self._boost('NotARealCategory') == 1.0

    def test_returns_float(self):
        assert isinstance(self._boost('Economy'), float)


class TestCalculateTimelinessScore:
    """Timeliness decays from 1.0 (today) toward 0 over time."""

    def _score(self, days_ago):
        from app.lib.time import utcnow_naive
        from app.daily.auto_selection import calculate_timeliness_score
        created_at = utcnow_naive() - timedelta(days=days_ago)
        return calculate_timeliness_score(created_at)

    def test_none_returns_default(self):
        from app.daily.auto_selection import calculate_timeliness_score
        assert calculate_timeliness_score(None) == 0.5

    def test_today_is_near_one(self):
        score = self._score(0)
        assert score > 0.95

    def test_seven_days_is_approx_point_37(self):
        score = self._score(7)
        assert abs(score - math.exp(-1)) < 0.01

    def test_fourteen_days_is_lower_than_seven(self):
        assert self._score(14) < self._score(7)

    def test_older_content_decays_further(self):
        assert self._score(30) < self._score(14) < self._score(7) < self._score(1)

    def test_score_is_between_zero_and_one(self):
        for days in (0, 1, 7, 14, 30, 90):
            s = self._score(days)
            assert 0.0 <= s <= 1.0, f"Score out of range for {days} days: {s}"


class TestCalculateClarityScore:
    """Optimal statement length is 50-100 chars; shorter and longer are penalised."""

    def _score(self, text):
        from app.daily.auto_selection import calculate_clarity_score
        return calculate_clarity_score(text)

    def test_none_returns_default(self):
        assert self._score(None) == 0.5

    def test_empty_returns_default(self):
        assert self._score('') == 0.5

    def test_optimal_length_returns_one(self):
        text = 'x' * 75  # within 50-100
        assert self._score(text) == 1.0

    def test_50_chars_returns_one(self):
        assert self._score('x' * 50) == 1.0

    def test_100_chars_returns_one(self):
        assert self._score('x' * 100) == 1.0

    def test_very_short_penalised(self):
        assert self._score('Hi') < 1.0

    def test_very_long_penalised(self):
        assert self._score('x' * 400) < 0.7

    def test_longer_is_worse_than_optimal(self):
        assert self._score('x' * 200) < self._score('x' * 75)

    def test_score_bounded_above_zero(self):
        assert self._score('x' * 1000) > 0.0


class TestCalculateControversyPotential:
    """Strong position words raise the score; hedging words lower it."""

    def _score(self, text):
        from app.daily.auto_selection import calculate_controversy_potential
        return calculate_controversy_potential(text)

    def test_none_returns_default(self):
        assert self._score(None) == 0.5

    def test_empty_returns_default(self):
        assert self._score('') == 0.5

    def test_should_raises_score(self):
        assert self._score('Governments should ban all fossil fuels') > 0.5

    def test_must_raises_score(self):
        assert self._score('We must act now on climate change') > 0.5

    def test_hedging_lowers_score(self):
        assert self._score('Some experts may sometimes possibly consider this') < 0.5

    def test_strong_claim_beats_hedged_claim(self):
        strong = self._score('We must ban fossil fuels immediately')
        hedged = self._score('Some countries might possibly consider reducing emissions')
        assert strong > hedged

    def test_score_clamped_between_0_2_and_1(self):
        for text in ('', 'should must ban require mandatory', 'may might could possibly sometimes'):
            s = self._score(text)
            assert 0.2 <= s <= 1.0, f"Score out of range: {s}"


# ---------------------------------------------------------------------------
# DB integration tests for eligibility query functions
# ---------------------------------------------------------------------------

def _make_discussion(db, title, topic, partner_env='live'):
    """Create and persist a minimal Discussion for testing."""
    from app.models import Discussion
    d = Discussion(title=title, topic=topic, partner_env=partner_env)
    db.session.add(d)
    db.session.flush()
    return d


def _make_trending_topic(db, title, status, civic_score, primary_topic, seed_statements=None):
    """Create and persist a minimal TrendingTopic for testing."""
    from app.models import TrendingTopic
    t = TrendingTopic(
        title=title,
        status=status,
        civic_score=civic_score,
        primary_topic=primary_topic,
        risk_flag=False,
        seed_statements=seed_statements or [],
    )
    db.session.add(t)
    db.session.flush()
    return t


def _make_statement(db, content, discussion, is_seed=True):
    """Create and persist a Statement for testing."""
    from app.models import Statement
    s = Statement(
        content=content,
        discussion_id=discussion.id,
        is_seed=is_seed,
    )
    db.session.add(s)
    db.session.flush()
    return s


class TestGetEligibleDiscussions:
    """get_eligible_discussions must only return civic-category discussions."""

    def test_civic_discussion_is_included(self, db):
        from app.daily.auto_selection import get_eligible_discussions
        _make_discussion(db, 'Minimum wage policy', 'Economy')
        db.session.commit()
        results = get_eligible_discussions()
        topics = [d.topic for d in results]
        assert 'Economy' in topics

    def test_sport_discussion_excluded(self, db):
        from app.daily.auto_selection import get_eligible_discussions
        _make_discussion(db, 'Football season preview', 'Sport')
        db.session.commit()
        results = get_eligible_discussions()
        topics = [d.topic for d in results]
        assert 'Sport' not in topics

    def test_test_partner_env_excluded(self, db):
        from app.daily.auto_selection import get_eligible_discussions
        _make_discussion(db, 'Test discussion', 'Politics', partner_env='test')
        db.session.commit()
        results = get_eligible_discussions()
        titles = [d.title for d in results]
        assert 'Test discussion' not in titles

    def test_all_civic_categories_are_eligible(self, db):
        from app.daily.auto_selection import get_eligible_discussions, DAILY_QUESTION_CATEGORIES
        for i, cat in enumerate(DAILY_QUESTION_CATEGORIES):
            _make_discussion(db, f'Discussion {i} about {cat}', cat)
        db.session.commit()
        results = get_eligible_discussions()
        returned_topics = {d.topic for d in results}
        for cat in DAILY_QUESTION_CATEGORIES:
            assert cat in returned_topics, f"Category '{cat}' should be eligible for daily questions"

    def test_returns_empty_when_no_eligible(self, db):
        from app.daily.auto_selection import get_eligible_discussions
        _make_discussion(db, 'Only sport', 'Sport')
        db.session.commit()
        results = get_eligible_discussions()
        assert results == []


class TestGetEligibleTrendingTopics:
    """get_eligible_trending_topics must enforce per-category civic thresholds."""

    def test_politics_above_threshold_included(self, db):
        from app.daily.auto_selection import get_eligible_trending_topics
        _make_trending_topic(db, 'Tax reform debate', 'published', 0.7, 'Politics')
        db.session.commit()
        results = get_eligible_trending_topics()
        assert any(t.primary_topic == 'Politics' for t in results)

    def test_politics_below_threshold_excluded(self, db):
        from app.daily.auto_selection import get_eligible_trending_topics, MIN_CIVIC_SCORE
        score = MIN_CIVIC_SCORE - 0.01
        _make_trending_topic(db, 'Low-score politics', 'published', score, 'Politics')
        db.session.commit()
        results = get_eligible_trending_topics()
        assert not any(t.title == 'Low-score politics' for t in results)

    def test_culture_above_culture_threshold_included(self, db):
        from app.daily.auto_selection import get_eligible_trending_topics, MIN_CIVIC_SCORE_FOR_CULTURE
        score = MIN_CIVIC_SCORE_FOR_CULTURE + 0.05
        _make_trending_topic(db, 'Arts funding debate', 'published', score, 'Culture')
        db.session.commit()
        results = get_eligible_trending_topics()
        assert any(t.title == 'Arts funding debate' for t in results)

    def test_culture_between_thresholds_excluded(self, db):
        """A Culture topic with 0.5 <= score < 0.6 must not pass the stricter floor."""
        from app.daily.auto_selection import (
            get_eligible_trending_topics, MIN_CIVIC_SCORE, MIN_CIVIC_SCORE_FOR_CULTURE
        )
        score = (MIN_CIVIC_SCORE + MIN_CIVIC_SCORE_FOR_CULTURE) / 2
        _make_trending_topic(db, 'Mid-score culture', 'published', score, 'Culture')
        db.session.commit()
        results = get_eligible_trending_topics()
        assert not any(t.title == 'Mid-score culture' for t in results)

    def test_culture_below_general_threshold_excluded(self, db):
        from app.daily.auto_selection import get_eligible_trending_topics, MIN_CIVIC_SCORE
        score = MIN_CIVIC_SCORE - 0.1
        _make_trending_topic(db, 'Very low culture', 'published', score, 'Culture')
        db.session.commit()
        results = get_eligible_trending_topics()
        assert not any(t.title == 'Very low culture' for t in results)

    def test_sport_topic_excluded_regardless_of_score(self, db):
        from app.daily.auto_selection import get_eligible_trending_topics
        _make_trending_topic(db, 'Champion league preview', 'published', 0.95, 'Sport')
        db.session.commit()
        results = get_eligible_trending_topics()
        assert not any(t.primary_topic == 'Sport' for t in results)

    def test_unpublished_topic_excluded(self, db):
        from app.daily.auto_selection import get_eligible_trending_topics
        _make_trending_topic(db, 'Draft topic', 'pending_review', 0.9, 'Politics')
        db.session.commit()
        results = get_eligible_trending_topics()
        assert not any(t.title == 'Draft topic' for t in results)

    def test_returns_empty_when_nothing_eligible(self, db):
        from app.daily.auto_selection import get_eligible_trending_topics
        results = get_eligible_trending_topics()
        assert results == []


class TestGetEligibleStatements:
    """get_eligible_statements must only surface statements from civic discussions."""

    def test_statement_from_civic_discussion_included(self, db):
        from app.daily.auto_selection import get_eligible_statements
        disc = _make_discussion(db, 'Climate policy', 'Environment')
        _make_statement(db, 'Governments must act on climate', disc)
        db.session.commit()
        results = get_eligible_statements()
        contents = [s.content for s in results]
        assert 'Governments must act on climate' in contents

    def test_statement_from_sport_discussion_excluded(self, db):
        from app.daily.auto_selection import get_eligible_statements
        disc = _make_discussion(db, 'Football season preview', 'Sport')
        _make_statement(db, 'The best team should win the league', disc)
        db.session.commit()
        results = get_eligible_statements()
        contents = [s.content for s in results]
        assert 'The best team should win the league' not in contents

    def test_non_seed_statement_excluded(self, db):
        from app.daily.auto_selection import get_eligible_statements
        disc = _make_discussion(db, 'Trade policy', 'Economy')
        _make_statement(db, 'Not a seed statement', disc, is_seed=False)
        db.session.commit()
        results = get_eligible_statements()
        contents = [s.content for s in results]
        assert 'Not a seed statement' not in contents

    def test_returns_only_seed_statements(self, db):
        from app.daily.auto_selection import get_eligible_statements
        disc = _make_discussion(db, 'Education reform', 'Education')
        seed = _make_statement(db, 'Schools should be publicly funded', disc, is_seed=True)
        non_seed = _make_statement(db, 'Teachers disagree', disc, is_seed=False)
        db.session.commit()
        results = get_eligible_statements()
        ids = [s.id for s in results]
        assert seed.id in ids
        assert non_seed.id not in ids

    def test_returns_empty_when_only_sport_statements(self, db):
        from app.daily.auto_selection import get_eligible_statements
        disc = _make_discussion(db, 'Premier League', 'Sport')
        _make_statement(db, 'Best team wins', disc)
        db.session.commit()
        results = get_eligible_statements()
        assert results == []
