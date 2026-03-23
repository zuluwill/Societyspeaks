"""
Tests for auto_publish_daily two-pass ordering and related filtering logic.

Coverage:
- _build_ordered_candidates: pure unit tests (no DB required)
- TrendingTopic.should_auto_publish: DB integration tests
- Political leaning balance logic: unit tests via mock objects
- Title-similarity deduplication logic: unit tests via mock objects
"""

import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers — lightweight stand-ins for TrendingTopic used in pure unit tests
# ---------------------------------------------------------------------------

def make_topic(id, primary_topic, civic_score=0.7, risk_flag=False, title="Topic"):
    """Return a SimpleNamespace that mimics the fields read by _build_ordered_candidates."""
    return SimpleNamespace(
        id=id,
        primary_topic=primary_topic,
        civic_score=civic_score,
        risk_flag=risk_flag,
        title=title,
        should_auto_publish=(civic_score >= 0.5 and not risk_flag),
        articles=[],
    )


PRIORITY_CATEGORIES = [
    'Politics', 'Economy', 'Geopolitics', 'Healthcare',
    'Technology', 'Society', 'Environment', 'Culture',
    'Education', 'Business', 'Infrastructure',
]


# ---------------------------------------------------------------------------
# Tests for _build_ordered_candidates (pure function — no DB needed)
# ---------------------------------------------------------------------------

class TestBuildOrderedCandidates:
    """Unit tests for the two-pass ordering helper."""

    def _call(self, eligible, categories=None):
        from app.trending.pipeline import _build_ordered_candidates
        return _build_ordered_candidates(eligible, categories or PRIORITY_CATEGORIES)

    def test_empty_input_returns_empty(self):
        assert self._call([]) == []

    def test_single_topic_is_returned(self):
        t = make_topic(1, 'Politics')
        result = self._call([t])
        assert result == [t]

    def test_each_topic_appears_exactly_once(self):
        topics = [make_topic(i, 'Politics') for i in range(5)]
        result = self._call(topics)
        assert len(result) == len(topics)
        assert len({t.id for t in result}) == len(topics)

    def test_pass1_guarantees_one_per_category(self):
        """The first item from each category must appear before any fill topics."""
        politics = [make_topic(1, 'Politics', civic_score=0.9),
                    make_topic(2, 'Politics', civic_score=0.8)]
        economy  = [make_topic(3, 'Economy',  civic_score=0.7)]

        result = self._call(politics + economy)

        categories_seen = [t.primary_topic for t in result]
        politics_first = next(i for i, c in enumerate(categories_seen) if c == 'Politics')
        economy_first  = next(i for i, c in enumerate(categories_seen) if c == 'Economy')

        assert politics_first < len(PRIORITY_CATEGORIES), "Politics should appear in Pass 1 position"
        assert economy_first  < len(PRIORITY_CATEGORIES), "Economy should appear in Pass 1 position"

    def test_pass1_picks_best_topic_per_category(self):
        """When topics arrive sorted score-descending, the first per category is the best."""
        # Sorted descending — first is best
        topics = [
            make_topic(1, 'Politics', civic_score=0.9),
            make_topic(2, 'Politics', civic_score=0.7),
            make_topic(3, 'Politics', civic_score=0.5),
        ]
        result = self._call(topics)
        # Topic 1 (0.9) must be the Politics representative
        politics_rep = next(t for t in result if t.primary_topic == 'Politics')
        assert politics_rep.id == 1

    def test_pass2_fills_remaining_slots_in_score_order(self):
        """After Pass 1, leftover topics appear in their original (score) order."""
        topics = [
            make_topic(1, 'Politics', civic_score=0.9),   # Pass 1: Politics slot
            make_topic(2, 'Economy',  civic_score=0.85),  # Pass 1: Economy slot
            make_topic(3, 'Politics', civic_score=0.80),  # Pass 2: fill
            make_topic(4, 'Politics', civic_score=0.70),  # Pass 2: fill
        ]
        result = self._call(topics)

        pass2_topics = [t for t in result if t.id in {3, 4}]
        assert pass2_topics[0].id == 3, "Higher-score fill topic should come first"
        assert pass2_topics[1].id == 4

    def test_unknown_category_appended_in_pass2(self):
        """Topics whose primary_topic is not in PRIORITY_CATEGORIES go into Pass 2."""
        guaranteed = make_topic(1, 'Politics')
        unknown    = make_topic(2, 'Sport')   # Not in PRIORITY_CATEGORIES

        result = self._call([guaranteed, unknown])

        assert result[0].id == 1, "Known category topic should be first (Pass 1)"
        assert result[1].id == 2, "Unknown category topic should be last (Pass 2)"

    def test_none_primary_topic_treated_as_unknown(self):
        t = make_topic(1, None)
        result = self._call([t])
        assert len(result) == 1

    def test_category_order_respects_priority_list(self):
        """Pass 1 must emit categories in the order specified by priority_categories."""
        categories = ['Economy', 'Politics']  # Economy first in this test
        economy = make_topic(1, 'Economy')
        politics = make_topic(2, 'Politics')

        result = self._call([economy, politics], categories=categories)
        assert result[0].primary_topic == 'Economy'
        assert result[1].primary_topic == 'Politics'

    def test_no_duplicates_across_passes(self):
        """A topic selected in Pass 1 must not appear again in Pass 2."""
        t = make_topic(1, 'Politics')
        result = self._call([t])
        ids = [x.id for x in result]
        assert ids.count(1) == 1


# ---------------------------------------------------------------------------
# Tests for TrendingTopic.should_auto_publish (DB integration)
# ---------------------------------------------------------------------------

class TestShouldAutoPublish:
    """Integration tests for the should_auto_publish property on the real model."""

    def test_high_civic_no_flag_is_publishable(self, db):
        from app.models import TrendingTopic
        t = TrendingTopic(title="Test topic", civic_score=0.7, risk_flag=False, status='pending_review')
        db.session.add(t)
        db.session.commit()
        assert t.should_auto_publish is True

    def test_exact_threshold_is_publishable(self, db):
        from app.models import TrendingTopic
        t = TrendingTopic(title="Edge case", civic_score=0.5, risk_flag=False, status='pending_review')
        db.session.add(t)
        db.session.commit()
        assert t.should_auto_publish is True

    def test_below_threshold_not_publishable(self, db):
        from app.models import TrendingTopic
        t = TrendingTopic(title="Low civic", civic_score=0.49, risk_flag=False, status='pending_review')
        db.session.add(t)
        db.session.commit()
        assert t.should_auto_publish is False

    def test_risk_flagged_not_publishable(self, db):
        from app.models import TrendingTopic
        t = TrendingTopic(title="Risky topic", civic_score=0.9, risk_flag=True, status='pending_review')
        db.session.add(t)
        db.session.commit()
        assert t.should_auto_publish is False

    def test_null_civic_score_not_publishable(self, db):
        from app.models import TrendingTopic
        t = TrendingTopic(title="No score", civic_score=None, risk_flag=False, status='pending_review')
        db.session.add(t)
        db.session.commit()
        assert t.should_auto_publish is False

    def test_both_failing_conditions_not_publishable(self, db):
        from app.models import TrendingTopic
        t = TrendingTopic(title="Both bad", civic_score=0.3, risk_flag=True, status='pending_review')
        db.session.add(t)
        db.session.commit()
        assert t.should_auto_publish is False


# ---------------------------------------------------------------------------
# Tests for political leaning balance logic (via inline simulation)
# ---------------------------------------------------------------------------

class TestPoliticalLeaningBalance:
    """
    The balance check inside auto_publish_daily prevents one side from
    exceeding the other by more than 2. These tests exercise the rule
    directly without hitting the database.
    """

    def _check_balance(self, topic_leaning, left_count, right_count, tolerance=2):
        """Return True if publishing this topic's leaning would stay in balance."""
        if topic_leaning in ('left', 'centre-left'):
            return (left_count + 1) <= right_count + tolerance
        elif topic_leaning in ('right', 'centre-right'):
            return (right_count + 1) <= left_count + tolerance
        return True  # centre always allowed

    def test_centre_always_allowed(self):
        assert self._check_balance('centre', 10, 0) is True

    def test_left_allowed_within_tolerance(self):
        # (left_count + 1) <= right_count + 2  must hold
        assert self._check_balance('left', 0, 0) is True   # would be 1:0 — allowed
        assert self._check_balance('left', 1, 0) is True   # would be 2:0 — at the limit
        assert self._check_balance('centre-left', 1, 0) is True

    def test_left_blocked_when_exceeds_tolerance(self):
        # (left_count + 1) > right_count + 2  triggers the skip
        assert self._check_balance('left', 2, 0) is False   # would be 3:0 — over limit
        assert self._check_balance('centre-left', 4, 1) is False

    def test_right_allowed_within_tolerance(self):
        assert self._check_balance('right', 0, 0) is True   # would be 0:1 — allowed
        assert self._check_balance('right', 0, 1) is True   # would be 0:2 — at the limit

    def test_right_blocked_when_exceeds_tolerance(self):
        assert self._check_balance('right', 0, 2) is False  # would be 0:3 — over limit

    def test_balanced_publication_stays_balanced(self):
        """Alternating left/right never trips the balance check."""
        left_count = 0
        right_count = 0
        for leaning in ['left', 'right', 'left', 'right', 'left', 'right']:
            assert self._check_balance(leaning, left_count, right_count) is True
            if leaning in ('left', 'centre-left'):
                left_count += 1
            else:
                right_count += 1


# ---------------------------------------------------------------------------
# Tests for title-similarity deduplication logic
# ---------------------------------------------------------------------------

STOPWORDS = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by'}


class TestTitleSimilarityDeduplication:
    """
    The deduplication rule: if a new topic shares 3+ non-stopword title
    words with already-published keywords, skip it.
    """

    def _meaningful_words(self, title):
        return set(title.lower().split()) - STOPWORDS

    def _would_skip(self, new_title, published_keywords, threshold=3):
        words = self._meaningful_words(new_title)
        return len(words & published_keywords) >= threshold

    def test_identical_title_is_duplicate(self):
        published = self._meaningful_words("Government raises minimum wage threshold")
        assert self._would_skip("Government raises minimum wage threshold", published)

    def test_three_shared_words_is_duplicate(self):
        published = {'government', 'raises', 'minimum', 'wage'}
        assert self._would_skip("Government raises minimum tax", published)

    def test_two_shared_words_is_not_duplicate(self):
        published = {'government', 'raises'}
        assert not self._would_skip("Government raises funding for schools", published)

    def test_completely_different_title_not_duplicate(self):
        published = {'inflation', 'rate', 'falls'}
        assert not self._would_skip("Scientists discover new vaccine", published)

    def test_stopwords_not_counted(self):
        """Stopwords are excluded so common words like 'the' never trigger dedup."""
        published = {'the', 'a', 'is', 'of'}
        assert not self._would_skip("The government is a problem", published)

    def test_empty_published_keywords_never_duplicate(self):
        assert not self._would_skip("Any title at all", set())

    def test_short_title_with_few_meaningful_words(self):
        published = {'ai', 'risks'}
        assert not self._would_skip("AI risks", published)


# ---------------------------------------------------------------------------
# Tests for _get_topic_political_leaning (pure logic, mocked articles)
# ---------------------------------------------------------------------------

class TestGetTopicPoliticalLeaning:
    """Tests for the leaning classifier used to enforce balance."""

    def _make_topic_with_leanings(self, leaning_values):
        """Build a topic mock with articles whose sources have the given political leanings."""
        articles = []
        for pl in leaning_values:
            source = SimpleNamespace(political_leaning=pl)
            article = SimpleNamespace(source=source)
            ta = SimpleNamespace(article=article)
            articles.append(ta)
        return SimpleNamespace(articles=articles)

    def _call(self, topic):
        from app.trending.pipeline import _get_topic_political_leaning
        return _get_topic_political_leaning(topic)

    def test_no_articles_returns_centre(self):
        topic = SimpleNamespace(articles=[])
        assert self._call(topic) == 'centre'

    def test_far_left_source(self):
        topic = self._make_topic_with_leanings([-2.0])
        assert self._call(topic) == 'left'

    def test_centre_left_source(self):
        topic = self._make_topic_with_leanings([-0.8])
        assert self._call(topic) == 'centre-left'

    def test_centre_source(self):
        topic = self._make_topic_with_leanings([0.0])
        assert self._call(topic) == 'centre'

    def test_centre_right_source(self):
        topic = self._make_topic_with_leanings([0.8])
        assert self._call(topic) == 'centre-right'

    def test_far_right_source(self):
        topic = self._make_topic_with_leanings([2.0])
        assert self._call(topic) == 'right'

    def test_majority_leaning_wins(self):
        topic = self._make_topic_with_leanings([-2.0, -2.0, 2.0])
        assert self._call(topic) == 'left'

    def test_none_leaning_source_skipped(self):
        source = SimpleNamespace(political_leaning=None)
        article = SimpleNamespace(source=source)
        ta = SimpleNamespace(article=article)
        topic = SimpleNamespace(articles=[ta])
        assert self._call(topic) == 'centre'

    def test_article_without_source_skipped(self):
        ta = SimpleNamespace(article=SimpleNamespace(source=None))
        topic = SimpleNamespace(articles=[ta])
        assert self._call(topic) == 'centre'
