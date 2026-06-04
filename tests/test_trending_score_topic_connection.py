"""
Tests for score_topic's connection-hygiene behaviour.

score_topic snapshots the data it needs, calls db.session.rollback() to release
the DB connection, then makes a slow LLM call, then writes scores back onto the
(now expired) in-session topic for the caller to commit. These tests pin that
contract against a real session so the mid-function rollback can never silently
drop the score writes or leave the connection unusable.
"""

import pytest
from unittest.mock import patch

from app.models import NewsSource, NewsArticle, TrendingTopic, TrendingTopicArticle
from app.trending.scorer import score_topic


def _make_topic_with_article(db, *, title="Should the council expand cycle lanes?",
                             article_title="City council debates new cycle lane budget"):
    """Create a persisted TrendingTopic linked to one real article + source."""
    source = NewsSource(name="Test Source", feed_url="https://src.test/rss",
                        source_type="rss", country="United Kingdom")
    db.session.add(source)
    db.session.flush()

    article = NewsArticle(source_id=source.id, title=article_title,
                          url="https://src.test/a/1", relevance_score=0.8)
    db.session.add(article)
    db.session.flush()

    topic = TrendingTopic(title=title, status="pending")
    db.session.add(topic)
    db.session.flush()

    db.session.add(TrendingTopicArticle(topic_id=topic.id, article_id=article.id))
    db.session.commit()
    return topic, article


def test_scores_persist_after_internal_rollback(db):
    """score_topic rollback()s mid-call; scores must still survive the caller commit."""
    topic, _ = _make_topic_with_article(db)
    topic_id = topic.id

    llm_json = (
        '{"civic_score": 0.82, "quality_score": 0.71, "audience_score": 0.66, '
        '"risk_flag": false, "primary_topic": "Infrastructure", '
        '"canonical_tags": ["transport", "cycling"]}'
    )

    with patch("app.trending.scorer.get_system_api_key", return_value=("fake", "openai")), \
         patch("app.trending.scorer._call_openai", return_value=llm_json):
        returned = score_topic(topic)

    # Caller commits, exactly as process_held_topics / rescore_topic do.
    db.session.commit()

    # Read back from a fresh identity-map state to prove it actually persisted.
    db.session.expire_all()
    reloaded = db.session.get(TrendingTopic, topic_id)
    assert reloaded is returned
    assert reloaded.civic_score == pytest.approx(0.82)
    assert reloaded.quality_score == pytest.approx(0.71)
    assert reloaded.audience_score == pytest.approx(0.66)
    assert reloaded.risk_flag is False
    assert reloaded.primary_topic == "Infrastructure"
    assert reloaded.topic_slug == "transport_cycling"


def test_article_title_snapshotted_before_rollback(db):
    """The article title must be lazy-loaded into the prompt before the connection is released."""
    _make_topic_with_article(db, article_title="Unique headline marker 4815")
    topic = db.session.query(TrendingTopic).first()

    captured = {}

    def fake_call(api_key, prompt):
        captured["prompt"] = prompt
        return '{"civic_score": 0.5, "primary_topic": "Society"}'

    with patch("app.trending.scorer.get_system_api_key", return_value=("fake", "openai")), \
         patch("app.trending.scorer._call_openai", side_effect=fake_call):
        score_topic(topic)
    db.session.commit()

    assert "Unique headline marker 4815" in captured["prompt"]


def test_llm_failure_leaves_session_usable(db):
    """If the LLM call raises after the rollback, score_topic falls back to defaults
    and the session must still be committable (no wedged connection)."""
    topic, _ = _make_topic_with_article(db)
    topic_id = topic.id

    with patch("app.trending.scorer.get_system_api_key", return_value=("fake", "openai")), \
         patch("app.trending.scorer._call_openai", side_effect=RuntimeError("boom")):
        score_topic(topic)

    # The caller's commit must succeed against a healthy session.
    db.session.commit()

    db.session.expire_all()
    reloaded = db.session.get(TrendingTopic, topic_id)
    assert reloaded.civic_score == pytest.approx(0.5)
    assert reloaded.primary_topic == "Society"
    assert reloaded.risk_flag is False


def test_no_api_key_returns_defaults_without_rollback(db):
    """The no-key early return sets defaults and never touches the connection."""
    topic, _ = _make_topic_with_article(db)
    topic_id = topic.id

    with patch("app.trending.scorer.get_system_api_key", return_value=(None, "")):
        score_topic(topic)
    db.session.commit()

    db.session.expire_all()
    reloaded = db.session.get(TrendingTopic, topic_id)
    assert reloaded.civic_score == pytest.approx(0.5)
    assert reloaded.primary_topic == "Society"


def test_recount_counts_distinct_sources_across_all_links(db):
    """recount_topic_source_count must count DISTINCT sources across ALL of a
    topic's article links (not per-cluster), and reflect freshly-flushed links."""
    from app.trending.clustering import recount_topic_source_count

    src_a = NewsSource(name="A", feed_url="https://a.test/rss", source_type="rss")
    src_b = NewsSource(name="B", feed_url="https://b.test/rss", source_type="rss")
    db.session.add_all([src_a, src_b])
    db.session.flush()

    # Three articles, two sources (src_a appears twice).
    arts = [
        NewsArticle(source_id=src_a.id, title="a1", url="https://a.test/1"),
        NewsArticle(source_id=src_a.id, title="a2", url="https://a.test/2"),
        NewsArticle(source_id=src_b.id, title="b1", url="https://b.test/1"),
    ]
    db.session.add_all(arts)
    db.session.flush()

    topic = TrendingTopic(title="Recount topic", status="pending")
    db.session.add(topic)
    db.session.flush()
    for a in arts:
        db.session.add(TrendingTopicArticle(topic_id=topic.id, article_id=a.id))
    db.session.flush()

    # Distinct sources = 2, even though there are 3 article links.
    assert recount_topic_source_count(topic.id) == 2
    assert recount_topic_source_count(-1) == 0  # no links -> 0, not None


def test_process_held_topics_persists_scores_and_seeds(db):
    """End-to-end orchestration: score_topic rollback()s, scores stay uncommitted
    across a second LLM call (seed generation), then one deferred commit must
    persist BOTH the scores and the seeds and flip the topic to pending_review."""
    from datetime import timedelta
    from app.lib.time import utcnow_naive
    from app.trending.pipeline import process_held_topics

    topic, _ = _make_topic_with_article(db)
    topic.hold_until = utcnow_naive() - timedelta(minutes=5)
    db.session.commit()
    topic_id = topic.id

    llm_json = ('{"civic_score": 0.77, "primary_topic": "Infrastructure", '
                '"risk_flag": false}')
    fake_seeds = [{"content": "A clearly substantive pro statement about cycle lanes.",
                   "position": "pro"}]

    with patch("app.trending.scorer.get_system_api_key", return_value=("fake", "openai")), \
         patch("app.trending.scorer._call_openai", return_value=llm_json), \
         patch("app.trending.pipeline.generate_seed_statements", return_value=fake_seeds):
        ready = process_held_topics()

    assert ready == 1

    db.session.expire_all()
    reloaded = db.session.get(TrendingTopic, topic_id)
    assert reloaded.status == "pending_review"
    assert reloaded.civic_score == pytest.approx(0.77)
    assert reloaded.primary_topic == "Infrastructure"
    assert reloaded.seed_statements == fake_seeds
