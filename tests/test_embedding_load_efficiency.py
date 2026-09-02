"""Guards against re-downloading embedding vectors from Postgres.

The three JSON embedding columns (news_article.title_embedding,
trending_topic.topic_embedding, polymarket_market.question_embedding) are
13-21 KB each. Loading them on queries that never read them, or reloading an
unchanged pool once per loop iteration, was the dominant source of Neon
egress on this project. These tests pin the fixes in place.
"""

from datetime import timedelta

import pytest
from sqlalchemy import inspect as sa_inspect

from app.lib.time import utcnow_naive


# ---------------------------------------------------------------------------
# Deferred columns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "model_name, column",
    [
        ("NewsArticle", "title_embedding"),
        ("TrendingTopic", "topic_embedding"),
        ("PolymarketMarket", "question_embedding"),
    ],
)
def test_embedding_columns_are_deferred(db, model_name, column):
    """A plain query must not pull the vector into the SELECT list."""
    import app.models as models

    model = getattr(models, model_name)
    assert model.__mapper__.attrs[column].deferred, (
        f"{model_name}.{column} must stay deferred — undeferring it puts a "
        f"multi-KB JSON vector on every query that touches the table."
    )


def test_polymarket_query_does_not_load_embedding(db):
    from app.models import PolymarketMarket

    market = PolymarketMarket(
        condition_id="c-defer",
        slug="defer-test",
        question="Will the deferred column stay deferred?",
        probability=0.5,
        volume_24h=20_000,
        liquidity=9_000,
        is_active=True,
        question_embedding=[0.1, 0.2, 0.3],
    )
    db.session.add(market)
    db.session.commit()
    db.session.expunge_all()

    loaded = PolymarketMarket.query.filter_by(condition_id="c-defer").one()
    assert "question_embedding" in sa_inspect(loaded).unloaded
    # Still reachable when something genuinely needs it.
    assert loaded.question_embedding == [0.1, 0.2, 0.3]


# ---------------------------------------------------------------------------
# Batch matching: one candidate pool per run, not per topic
# ---------------------------------------------------------------------------

def _make_market(db, condition_id="c-batch"):
    from app.models import PolymarketMarket

    market = PolymarketMarket(
        condition_id=condition_id,
        slug="batch-market",
        event_slug="batch-event",
        question="Will the UK pass net zero legislation in 2026?",
        category="climate",
        tags=["climate", "energy", "uk"],
        probability=0.4,
        volume_24h=15_000,
        liquidity=6_000,
        is_active=True,
        end_date=utcnow_naive() + timedelta(days=60),
    )
    db.session.add(market)
    return market


def _make_topics(db, count=3):
    from app.models import TrendingTopic

    topics = [
        TrendingTopic(
            title=f"UK climate policy fight {i}",
            status="published",
            primary_topic="Environment",
            canonical_tags=["climate", "uk", "parliament"],
        )
        for i in range(count)
    ]
    db.session.add_all(topics)
    return topics


def test_batch_matching_loads_candidate_pool_once(db, monkeypatch):
    """The pool SQL has no topic-dependent term, so N topics must cost 1 load."""
    from app.polymarket.matcher import MarketMatcher

    _make_market(db)
    _make_topics(db, count=3)
    db.session.commit()

    matcher = MarketMatcher()
    calls = []
    original = matcher._load_candidate_pool

    def counting_loader(tier):
        calls.append(tier)
        return original(tier)

    monkeypatch.setattr(matcher, "_load_candidate_pool", counting_loader)

    stats = matcher.run_batch_matching(days_back=7)

    assert stats["processed"] == 3
    assert len(calls) == 1, (
        f"candidate pool loaded {len(calls)}x for 3 topics — it must be "
        f"hoisted out of the per-topic loop"
    )


def _make_unrelated_market(db, condition_id="c-unrelated"):
    """Liquid market that will not keyword-match the UK climate fixtures."""
    from app.models import PolymarketMarket

    market = PolymarketMarket(
        condition_id=condition_id,
        slug="nba-unrelated",
        event_slug="nba-unrelated",
        question="Will the Lakers win the NBA championship?",
        category="sports",
        tags=["sports", "nba"],
        probability=0.3,
        volume_24h=15_000,
        liquidity=6_000,
        is_active=True,
        end_date=utcnow_naive() + timedelta(days=60),
    )
    db.session.add(market)
    return market


def test_batch_matching_skips_topics_inside_retry_window(db):
    """Topics that match nothing must back off, not return every 30 minutes."""
    from app.models import TrendingTopic
    from app.polymarket.matcher import MarketMatcher

    # Pool must be non-empty: an empty book is a sync gap and must not stamp
    # attempted_at (see test_empty_candidate_pool_does_not_stamp_attempts).
    _make_unrelated_market(db)
    _make_topics(db, count=2)
    db.session.commit()

    matcher = MarketMatcher()
    first = matcher.run_batch_matching(days_back=7)
    assert first["processed"] == 2
    assert first["skipped"] == 2

    # Every topic recorded an attempt even though none matched.
    assert all(
        t.market_match_attempted_at is not None
        for t in TrendingTopic.query.all()
    )

    second = matcher.run_batch_matching(days_back=7)
    assert second["processed"] == 0, (
        "unmatched topics were re-processed inside the retry window — this is "
        "the loop that re-downloaded the market pool 48x/day"
    )


def test_empty_candidate_pool_does_not_stamp_attempts(db):
    """No liquid markets is a transient gap, not a negative match result."""
    from app.models import PolymarketMarket, TrendingTopic
    from app.polymarket.matcher import MarketMatcher

    assert PolymarketMarket.query.count() == 0
    _make_topics(db, count=2)
    db.session.commit()

    matcher = MarketMatcher()
    stats = matcher.run_batch_matching(days_back=7)
    assert stats["processed"] == 0
    assert all(
        t.market_match_attempted_at is None for t in TrendingTopic.query.all()
    )

    # Markets appearing later must still be considered this window.
    _make_unrelated_market(db)
    db.session.commit()
    again = matcher.run_batch_matching(days_back=7)
    assert again["processed"] == 2


def test_batch_matching_retries_after_window_expires(db):
    from app.models import TrendingTopic
    from app.polymarket.matcher import MarketMatcher

    _make_unrelated_market(db)
    _make_topics(db, count=1)
    db.session.commit()

    matcher = MarketMatcher()
    matcher.run_batch_matching(days_back=7)

    stale = utcnow_naive() - timedelta(hours=MarketMatcher.MATCH_RETRY_HOURS + 1)
    for topic in TrendingTopic.query.all():
        topic.market_match_attempted_at = stale
    db.session.commit()

    again = matcher.run_batch_matching(days_back=7)
    assert again["processed"] == 1, "topics must be reconsidered once the window lapses"


def test_reprocess_existing_ignores_retry_window(db):
    """The daily pre-brief pass must still get a fresh look at every topic."""
    from app.polymarket.matcher import MarketMatcher

    _make_unrelated_market(db)
    _make_topics(db, count=2)
    db.session.commit()

    matcher = MarketMatcher()
    matcher.run_batch_matching(days_back=7)

    forced = matcher.run_batch_matching(days_back=7, reprocess_existing=True)
    assert forced["processed"] == 2


def test_due_check_does_not_select_topic_embedding(db):
    """The existence probe must not undefer the vector just to see if work is due."""
    from app.models import TrendingTopic
    from app.polymarket.matcher import MarketMatcher

    matcher = MarketMatcher()
    sql = str(
        matcher._topics_due_for_matching_query(7, False)
        .with_entities(TrendingTopic.id)
        .statement
    ).lower()
    assert "topic_embedding" not in sql


def test_due_query_is_not_mutated_by_existence_probe(db):
    """with_entities() must not poison the query that later loads full topics.

    run_batch_matching probes due_query.with_entities(TrendingTopic.id).first()
    then calls due_query.options(undefer(...)).all(). If with_entities mutated
    the original query in place, .all() would yield Row tuples, match_topic
    would throw, and every topic would land in stats['errors'] — silently
    matching nothing. The load-count test would still pass.
    """
    from app.models import TrendingTopic
    from app.polymarket.matcher import MarketMatcher

    _make_unrelated_market(db)
    _make_topics(db, count=2)
    db.session.commit()

    matcher = MarketMatcher()
    due_query = matcher._topics_due_for_matching_query(7, False)
    assert due_query.with_entities(TrendingTopic.id).first() is not None

    topics = due_query.all()
    assert len(topics) == 2
    assert all(isinstance(t, TrendingTopic) for t in topics)
    assert all(hasattr(t, "title") and t.title for t in topics)


def test_batch_matching_writes_embedding_matches(db):
    """End-to-end: the due-check, one pool, undefer, and a real TopicMarketMatch."""
    from app.models import TopicMarketMatch
    from app.polymarket.matcher import MarketMatcher

    market = _make_market(db)
    market.question_embedding = [1.0, 0.0, 0.0]
    topic = _make_topics(db, count=1)[0]
    topic.topic_embedding = [1.0, 0.0, 0.0]
    db.session.commit()

    stats = MarketMatcher().run_batch_matching(days_back=7)
    assert stats["processed"] == 1
    assert stats["matched"] == 1
    assert stats["errors"] == 0
    assert stats["skipped"] == 0

    rows = TopicMarketMatch.query.all()
    assert len(rows) == 1
    assert rows[0].trending_topic_id == topic.id
    assert rows[0].market_id == market.id
    assert rows[0].match_method == "embedding"
    assert rows[0].similarity_score >= MarketMatcher.EMBEDDING_THRESHOLD

    # Matched topics must not re-enter the 30-minute job.
    again = MarketMatcher().run_batch_matching(days_back=7)
    assert again["processed"] == 0


def test_match_topic_survives_session_expire_when_pool_holds_vectors(db):
    """Parsed pool vectors must survive ORM expire; do not re-read JSON from the row."""
    from sqlalchemy.orm import undefer
    from app.models import TrendingTopic
    from app.polymarket.matcher import MarketMatcher

    market = _make_market(db)
    market.question_embedding = [1.0, 0.0, 0.0]
    topic = _make_topics(db, count=1)[0]
    topic.topic_embedding = [1.0, 0.0, 0.0]
    db.session.commit()

    matcher = MarketMatcher()
    pool = matcher._load_candidate_pool("medium")
    assert market.id in pool.vectors

    db.session.expire_all()
    topic = TrendingTopic.query.options(
        undefer(TrendingTopic.topic_embedding)
    ).first()
    matches = matcher.match_topic(topic, candidate_pool=pool)
    assert matches
    assert matches[0]["market"].id == market.id
    assert matches[0]["method"] == "embedding"


# ---------------------------------------------------------------------------
# Topic duplicate detection index
# ---------------------------------------------------------------------------

def test_index_is_not_a_frozen_snapshot(db):
    """Topics registered mid-run are visible to later lookups.

    The index must stay live rather than being a snapshot taken before the
    cluster loop, otherwise duplicate detection would silently degrade.
    """
    from app.trending.clustering import TopicEmbeddingIndex

    index = TopicEmbeddingIndex()
    assert len(index) == 0

    vector = [1.0, 0.0, 0.0]
    assert index.find_duplicate_id(vector) is None

    index.add(4242, vector)
    assert index.find_duplicate_id(vector) == 4242


def test_pending_topics_are_not_dedupe_candidates(db):
    """Pins the status contract the index must mirror.

    create_topic_from_cluster creates topics with status='pending', which is
    NOT a dedupe candidate status — so a topic created earlier in a run was
    never a duplicate target under the original per-cluster query either.
    Appending such topics to the shared index unconditionally would widen
    dedup behaviour rather than preserve it.
    """
    from app.models import TrendingTopic
    from app.trending.clustering import (
        DUPLICATE_CANDIDATE_STATUSES,
        TopicEmbeddingIndex,
    )

    assert "pending" not in DUPLICATE_CANDIDATE_STATUSES

    db.session.add(
        TrendingTopic(
            title="Freshly clustered topic",
            status="pending",
            topic_embedding=[1.0, 0.0, 0.0],
        )
    )
    db.session.commit()

    index = TopicEmbeddingIndex()
    assert len(index) == 0, "pending topics must not enter the dedupe index"


def test_index_returns_best_match_not_first(db):
    from app.trending.clustering import TopicEmbeddingIndex

    index = TopicEmbeddingIndex(load=False)
    index.add(1, [1.0, 0.05, 0.0])   # similar
    index.add(2, [1.0, 0.0, 0.0])    # identical — the better match

    assert index.find_duplicate_id([1.0, 0.0, 0.0]) == 2


def test_index_ignores_unusable_vectors(db):
    from app.trending.clustering import TopicEmbeddingIndex

    index = TopicEmbeddingIndex(load=False)
    assert index.add(1, None) is False
    assert index.add(2, []) is False
    assert index.add(3, [0.0, 0.0, 0.0]) is False      # zero norm
    assert index.add(4, [1.0, 0.0, 0.0]) is True
    assert index.add(5, [1.0, 0.0]) is False            # wrong dimensionality
    assert len(index) == 1


def test_index_below_threshold_is_not_a_duplicate(db):
    from app.trending.clustering import TopicEmbeddingIndex

    index = TopicEmbeddingIndex(load=False)
    index.add(1, [1.0, 0.0, 0.0])
    assert index.find_duplicate_id([0.0, 1.0, 0.0]) is None


def test_find_duplicate_topic_reuses_supplied_index(db):
    """With an index supplied, no per-call topic query should be needed."""
    from app.models import TrendingTopic
    from app.trending.clustering import TopicEmbeddingIndex, find_duplicate_topic

    topic = TrendingTopic(
        title="Existing topic",
        status="published",
        topic_embedding=[1.0, 0.0, 0.0],
    )
    db.session.add(topic)
    db.session.commit()

    index = TopicEmbeddingIndex()
    assert len(index) == 1

    found = find_duplicate_topic([1.0, 0.0, 0.0], index=index)
    assert found is not None
    assert found.id == topic.id
    assert isinstance(found, TrendingTopic)


def test_find_duplicate_topic_without_index_still_works(db):
    """Backwards compatibility for callers outside the pipeline."""
    from app.models import TrendingTopic
    from app.trending.clustering import find_duplicate_topic

    topic = TrendingTopic(
        title="Standalone topic",
        status="approved",
        topic_embedding=[0.0, 1.0, 0.0],
    )
    db.session.add(topic)
    db.session.commit()

    assert find_duplicate_topic([0.0, 1.0, 0.0]).id == topic.id
    assert find_duplicate_topic([1.0, 0.0, 0.0]) is None


# ---------------------------------------------------------------------------
# RSS article dedup: indexed url_hash instead of unindexed url
# ---------------------------------------------------------------------------

def test_article_url_dedup_uses_indexed_url_hash(db):
    """news_article has no index on url, so the RSS dedup must use url_hash.

    url_hash is set by the before_insert/before_update listeners and hashes the
    *normalised* URL, so it also catches tracking-parameter variants that raw
    url equality missed.
    """
    from app.models import NewsArticle, NewsSource
    from app.lib.url_normalizer import url_hash

    source = NewsSource(name="Test Wire", feed_url="https://example.com/feed")
    db.session.add(source)
    db.session.flush()

    canonical = "https://www.bbc.co.uk/news/articles/abc123"
    article = NewsArticle(
        source_id=source.id,
        title="A headline",
        url=canonical,
        external_id="ext-1",
    )
    db.session.add(article)
    db.session.commit()

    assert article.url_hash == url_hash(canonical)

    # The exact lookup the RSS fetcher performs.
    tracked = canonical + "?utm_source=twitter&utm_medium=social"
    found = NewsArticle.query.filter_by(url_hash=url_hash(tracked)).first()
    assert found is not None and found.id == article.id, (
        "url_hash dedup must match the same article across tracking params"
    )

    other = NewsArticle.query.filter_by(
        url_hash=url_hash("https://www.bbc.co.uk/news/articles/different")
    ).first()
    assert other is None


def test_news_article_url_column_has_no_index(db):
    """Documents why the fetcher matches on url_hash.

    url is String(1000); a btree index on it risks exceeding the index row size
    limit for long URLs. If someone adds one, revisit news_fetcher._fetch_rss.
    """
    from app.models import NewsArticle

    indexed = {
        tuple(c.name for c in idx.columns)
        for idx in NewsArticle.__table__.indexes
    }
    assert ("url",) not in indexed
    assert ("url_hash",) in indexed


def test_discussion_page_eager_load_omits_article_embedding(db):
    """The public discussion page must not ship article vectors from Postgres.

    view_discussion eager-loads source articles; before title_embedding was
    deferred, ~19 KB of vector per discussion rode along on every render,
    including every crawler hit.
    """
    from sqlalchemy.orm import joinedload, selectinload
    from app.models import Discussion, DiscussionSourceArticle, NewsArticle

    query = Discussion.query.options(
        joinedload(Discussion.creator),
        selectinload(Discussion.source_article_links)
        .joinedload(DiscussionSourceArticle.article)
        .joinedload(NewsArticle.source),
    ).filter_by(id=1)

    assert "title_embedding" not in str(query)


def test_undefer_still_reaches_the_vector(db):
    """Deferral must not make the column unreachable for code that needs it."""
    from sqlalchemy.orm import undefer
    from app.models import NewsArticle

    assert "title_embedding" not in str(NewsArticle.query)
    assert "title_embedding" in str(
        NewsArticle.query.options(undefer(NewsArticle.title_embedding))
    )


def test_candidate_pool_parses_embeddings_once_into_numpy(db):
    """The pool must hold vectors even after the ORM row is expired."""
    from app.polymarket.matcher import MarketMatcher

    market = _make_market(db)
    market.question_embedding = [0.1, 0.2, 0.3]
    db.session.commit()

    pool = MarketMatcher()._load_candidate_pool("medium")
    assert len(pool) == 1
    assert market.id in pool.vectors

    db.session.expire_all()
    assert market.id in pool.vectors


def test_empty_backfill_cache_does_not_query_topics(db):
    """An empty dict means 'match against nothing', not 'please load the pool'."""
    import numpy as np
    from app.models import NewsArticle, NewsSource, TrendingTopic
    from app.trending.pipeline import _backfill_single_article

    source = NewsSource(name="Cache Wire", feed_url="https://example.com/feed")
    db.session.add(source)
    db.session.flush()

    article = NewsArticle(
        source_id=source.id,
        title="Aligned headline",
        url="https://example.com/aligned",
        external_id="aligned-1",
        title_embedding=[1.0, 0.0, 0.0],
        relevance_score=0.9,
    )
    topic = TrendingTopic(
        title="Aligned topic",
        status="published",
        topic_embedding=[1.0, 0.0, 0.0],
    )
    db.session.add_all([article, topic])
    db.session.commit()

    assert _backfill_single_article(article, topic_embeddings_cache={}) is False

    cache = {topic.id: (topic, np.array(topic.topic_embedding))}
    assert _backfill_single_article(article, cache) is True


def test_backfill_cache_includes_pending_topics(db):
    """Singleton/orphan backfill attaches to pending; dedupe does not."""
    from app.models import TrendingTopic
    from app.trending.clustering import TopicEmbeddingIndex
    from app.trending.pipeline import _load_topic_embedding_cache

    db.session.add(
        TrendingTopic(
            title="Just clustered",
            status="pending",
            topic_embedding=[1.0, 0.0, 0.0],
        )
    )
    db.session.commit()

    assert len(TopicEmbeddingIndex()) == 0
    assert len(_load_topic_embedding_cache()) == 1


def test_candidate_pool_markets_are_fully_loaded(db):
    """Pool markets must carry every column their consumers read.

    Market Pulse turns matched markets into signal dicts via to_signal_dict(),
    which reads most of the row. Narrowing the pool with load_only() would
    make each selection lazy-load instead — trading a measured ~4.5% of pool
    bytes (the embedding is 94% of a row) for an N+1.
    """
    from sqlalchemy import inspect as sa_inspect
    from app.models import PolymarketMarket
    from app.polymarket.matcher import MarketMatcher

    _make_market(db, condition_id="c-fullload")
    db.session.commit()
    db.session.expunge_all()

    pool = MarketMatcher()._load_candidate_pool("medium")
    assert len(pool) == 1

    market = pool.markets[0]
    column_attrs = {
        attr.key for attr in PolymarketMarket.__mapper__.column_attrs
    }
    unloaded_columns = sa_inspect(market).unloaded & column_attrs
    assert unloaded_columns == set(), (
        f"candidate pool rows must be fully loaded, including the undeferred "
        f"question_embedding; unloaded: {sorted(unloaded_columns)}"
    )
    # The vector the matcher needs is present without a second query.
    assert market.id in pool.vectors or market.question_embedding is None


def test_writing_a_deferred_embedding_does_not_read_it_first(db):
    """Setting a deferred column must not emit a SELECT to fetch the old value.

    cluster_articles() assigns title_embedding for every article in a pipeline
    run. If deferral made each assignment load the column first, deferring
    would have introduced an N+1 on the hottest write path in the pipeline.
    """
    from sqlalchemy import event, inspect as sa_inspect
    from app.models import NewsArticle, NewsSource

    source = NewsSource(name="Write Wire", feed_url="https://example.com/w")
    db.session.add(source)
    db.session.flush()
    article = NewsArticle(
        source_id=source.id, title="t", url="https://example.com/a", external_id="w-1"
    )
    db.session.add(article)
    db.session.commit()
    db.session.expunge_all()

    loaded = NewsArticle.query.filter_by(external_id="w-1").one()
    assert "title_embedding" in sa_inspect(loaded).unloaded

    statements = []

    def _record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", _record)
    try:
        loaded.title_embedding = [0.1, 0.2, 0.3]
    finally:
        event.remove(db.engine, "before_cursor_execute", _record)

    assert statements == [], (
        f"assigning a deferred column emitted SQL: {statements}"
    )

    db.session.commit()
    db.session.expunge_all()
    assert NewsArticle.query.filter_by(external_id="w-1").one().title_embedding == [
        0.1,
        0.2,
        0.3,
    ]


def test_url_hash_is_derived_from_normalized_url(db):
    """Pins the invariant the partner API lookup relies on.

    partner.py does a single indexed lookup on normalized_url and no longer
    probes url_hash afterwards, because url_hash IS sha256(normalize_url(url)).
    Verified against production: 51,211 rows, zero rows where
    url_hash <> substr(sha256(normalized_url), 1, 32), and NULLs on the same
    19 rows in both columns.

    If this ever stops holding, the two columns have diverged and the partner
    lookup needs revisiting — not a raw-url seq scan bolted back on.
    """
    import hashlib
    from app.lib.url_normalizer import normalize_url, url_hash

    for raw in [
        "https://www.bbc.co.uk/news/articles/abc123",
        "https://example.com/story?utm_source=x&id=7",
        "http://theguardian.com/world/2026/sep/01/something/",
    ]:
        normalized = normalize_url(raw)
        assert normalized
        expected = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
        assert url_hash(raw) == expected


def test_url_hash_and_normalized_url_are_set_together(db):
    """Both derived columns are written by the same listener, or neither is."""
    from app.models import NewsArticle, NewsSource

    source = NewsSource(name="Inv Wire", feed_url="https://example.com/inv")
    db.session.add(source)
    db.session.flush()

    article = NewsArticle(
        source_id=source.id,
        title="t",
        url="https://example.com/inv/story?utm_medium=email",
        external_id="inv-1",
    )
    db.session.add(article)
    db.session.commit()

    assert (article.normalized_url is None) == (article.url_hash is None)
    assert article.normalized_url == "https://example.com/inv/story"
