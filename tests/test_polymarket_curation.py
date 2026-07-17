"""Tests for Polymarket brief curation and matching helpers."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.lib.time import utcnow_naive


def test_word_boundary_war_does_not_match_warriors():
    from app.polymarket.curation import word_boundary_pattern, WORLD_EVENT_KEYWORDS

    pattern = word_boundary_pattern(WORLD_EVENT_KEYWORDS)
    assert pattern.search("Will the U.S. invade Iran before 2027?")
    assert pattern.search("Russia-Ukraine war ceasefire odds")
    assert not pattern.search("Will LeBron James play for the Golden State Warriors?")


def test_sports_filter_and_world_relevance():
    from app.polymarket.curation import is_sports_or_entertainment, is_world_relevant

    sports = SimpleNamespace(
        question="Will Argentina win the 2026 FIFA World Cup?",
        description="",
        tags=["sports", "soccer"],
        category="sports",
    )
    geopolitics = SimpleNamespace(
        question="Will the U.S. invade Iran before 2027?",
        description="",
        tags=["politics", "geopolitics"],
        category="politics",
    )

    assert is_sports_or_entertainment(sports)
    assert not is_world_relevant(sports)
    assert not is_sports_or_entertainment(geopolitics)
    assert is_world_relevant(geopolitics)


def test_brief_market_score_prefers_movers_over_volume():
    from app.polymarket.curation import brief_market_score

    stagnant_whale = SimpleNamespace(
        change_24h=0.002,
        volume_24h=5_000_000,
        end_date=None,
    )
    lively = SimpleNamespace(
        change_24h=0.06,
        volume_24h=40_000,
        end_date=None,
    )

    assert brief_market_score(stagnant_whale) is None
    lively_score = brief_market_score(lively)
    assert lively_score is not None
    assert lively_score > 3


def test_topic_bonus_lowers_the_movement_bar_but_does_not_remove_it():
    from app.polymarket.curation import brief_market_score

    frozen = SimpleNamespace(change_24h=0.0, volume_24h=5_000_000, end_date=None)
    nudged = SimpleNamespace(change_24h=0.006, volume_24h=40_000, end_date=None)

    assert brief_market_score(frozen, topic_bonus=10.0) is None
    # Below the default 0.01 gate, but topic-linked markets clear 0.005
    assert brief_market_score(nudged) is None
    assert brief_market_score(nudged, topic_bonus=10.0) is not None


def test_events_outage_does_not_wipe_stored_tags(db):
    from app.polymarket.service import PolymarketService

    service = PolymarketService()
    market_data = {
        "conditionId": "0xtagpreserve",
        "slug": "us-invade-iran",
        "question": "Will the U.S. invade Iran before 2027?",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["t1", "t2"]',
        "volume24hr": 90000,
        "outcomePrices": '["0.22", "0.78"]',
        "active": True,
        "events": [{"id": 999, "slug": "us-invade-iran"}],
    }
    event_meta = {
        "999": {
            "slug": "us-invade-iran",
            "tags": ["politics", "geopolitics"],
            "category": "politics",
            "open_interest": 5000,
        }
    }

    _, market = service._upsert_market(market_data, event_meta=event_meta)
    db.session.commit()
    assert market.tags == ["politics", "geopolitics"]
    assert market.trader_count == 5000

    # Empty event_meta mimics /events outage — must not blank stored enrichment
    _, market = service._upsert_market(market_data, event_meta={})
    db.session.commit()

    assert market.tags == ["politics", "geopolitics"]
    assert market.category == "politics"
    assert market.trader_count == 5000


def test_event_index_walks_keyset_pages_and_terminates():
    from app.polymarket.service import PolymarketService

    service = PolymarketService()
    calls = []

    def fake_gamma(endpoint, params=None):
        calls.append((endpoint, dict(params or {})))
        assert endpoint == "/events/keyset", "must use keyset, not offset paging"
        cursor = (params or {}).get("after_cursor")
        if cursor is None:
            return {
                "events": [{"id": 1, "slug": "a", "tags": [{"slug": "Politics"}, {"slug": "politics"}]}],
                "next_cursor": "cur1",
            }
        if cursor == "cur1":
            return {
                "events": [{"id": 2, "slug": "b", "tags": [{"slug": "finance"}]}],
                "next_cursor": "cur2",
            }
        # Final page: no next_cursor -> loop ends
        return {"events": [{"id": 3, "slug": "c", "tags": ["crypto"]}], "next_cursor": None}

    service._gamma_request = fake_gamma
    meta = service._load_event_meta_map()

    assert set(meta.keys()) == {"1", "2", "3"}
    assert len(calls) == 3  # walked exactly three pages, then stopped
    assert calls[1][1]["after_cursor"] == "cur1"
    # Tags deduped case-insensitively; category inferred
    assert meta["1"]["tags"] == ["politics"]
    assert meta["1"]["category"] == "politics"
    assert meta["3"]["tags"] == ["crypto"]


def test_event_index_stops_on_repeated_cursor():
    from app.polymarket.service import PolymarketService

    service = PolymarketService()
    calls = []

    def fake_gamma(endpoint, params=None):
        calls.append(endpoint)
        # API misbehaves: always returns the same non-null cursor
        return {"events": [{"id": 1, "slug": "a", "tags": ["politics"]}], "next_cursor": "stuck"}

    service._gamma_request = fake_gamma
    meta = service._load_event_meta_map()

    assert meta == {"1": meta["1"]}  # one event
    assert len(calls) == 2  # first page, then the repeat is detected and we stop


def test_failed_page_does_not_deactivate_unseen_markets(db):
    from app.models import PolymarketMarket
    from app.polymarket.service import PolymarketService

    survivor = PolymarketMarket(
        condition_id="c-page2",
        question="Will the Fed cut rates in September?",
        probability=0.5,
        volume_24h=10_000,
        is_active=True,
        last_synced_at=utcnow_naive() - timedelta(days=3),
    )
    db.session.add(survivor)
    db.session.commit()

    service = PolymarketService()
    page1 = [{
        "conditionId": "c-page1",
        "question": "Will the U.S. invade Iran before 2027?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.22", "0.78"]',
        "volume24hr": 90000,
        "active": True,
    }]

    calls = []

    def fake_page(limit=500, offset=0, closed=False):
        calls.append(offset)
        # Full first page, then the second page request fails
        return page1 * limit if offset == 0 else None

    service._fetch_markets_page = fake_page
    service._load_event_meta_map = lambda *a, **k: {}
    service._generate_embeddings_for_markets = lambda markets, batch_size=50: 0

    stats = service.sync_all_markets()

    assert len(calls) == 2  # attempted page 2, which failed
    assert stats["deactivated"] == 0
    assert db.session.get(PolymarketMarket, survivor.id).is_active is True


def test_recently_synced_market_survives_one_missed_sync(db):
    from app.models import PolymarketMarket
    from app.polymarket.service import PolymarketService

    # Missed this sync (e.g. shifted pages) but synced successfully minutes ago
    fresh = PolymarketMarket(
        condition_id="c-fresh",
        question="Will China invade Taiwan before 2027?",
        probability=0.11,
        volume_24h=60_000,
        is_active=True,
        last_synced_at=utcnow_naive() - timedelta(minutes=10),
    )
    # Absent for days — genuinely gone
    stale = PolymarketMarket(
        condition_id="c-stale",
        question="Resolved market nobody returns anymore",
        probability=0.99,
        volume_24h=100,
        is_active=True,
        last_synced_at=utcnow_naive() - timedelta(days=2),
    )
    db.session.add_all([fresh, stale])
    db.session.commit()
    fresh_id, stale_id = fresh.id, stale.id

    service = PolymarketService()
    service._load_event_meta_map = lambda *a, **k: {}
    service._generate_embeddings_for_markets = lambda markets, batch_size=50: 0
    service._fetch_markets_page = lambda limit=500, offset=0, closed=False: [{
        "conditionId": "c-other",
        "question": "Will the Fed cut rates in September?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.5", "0.5"]',
        "volume24hr": 10000,
        "active": True,
    }] if offset == 0 else []

    service.sync_all_markets()

    assert db.session.get(PolymarketMarket, fresh_id).is_active is True
    assert db.session.get(PolymarketMarket, stale_id).is_active is False


def test_recent_usage_window_is_filtered_in_sql(db):
    from app.models import DailyBrief
    from app.polymarket.curation import get_recent_brief_market_usage

    today = date.today()
    db.session.add_all([
        DailyBrief(
            date=today - timedelta(days=2), brief_type="daily", status="published",
            title="Recent", world_events=[{"market_id": 11, "event_slug": "recent-event"}],
        ),
        DailyBrief(
            date=today - timedelta(days=40), brief_type="daily", status="published",
            title="Old", world_events=[{"market_id": 22, "event_slug": "old-event"}],
        ),
        DailyBrief(
            date=today, brief_type="daily", status="published",
            title="Today", world_events=[{"market_id": 33, "event_slug": "todays-event"}],
        ),
    ])
    db.session.commit()

    market_ids, event_keys = get_recent_brief_market_usage(
        days=7, exclude_brief_date=today
    )

    assert market_ids == {11}
    assert event_keys == {"event:recent-event"}


def test_novelty_is_not_stale_within_a_long_lived_process(db):
    """market_curator is a singleton living for the whole scheduler process."""
    from app.models import DailyBrief, PolymarketMarket
    from app.polymarket.curation import market_curator

    today = date.today()

    def _mk(cid, event_slug, question, prob, prev, category, tags):
        return PolymarketMarket(
            condition_id=cid, slug=cid, event_slug=event_slug, question=question,
            category=category, tags=tags, probability=prob, probability_24h_ago=prev,
            volume_24h=80_000, liquidity=10_000, is_active=True,
            end_date=utcnow_naive() + timedelta(days=100),
        )

    db.session.add_all([
        _mk("n1", "us-invade-iran", "Will the U.S. invade Iran before 2027?",
            0.22, 0.12, "geopolitics", ["geopolitics"]),
        _mk("n2", "china-taiwan", "Will China invade Taiwan before 2027?",
            0.11, 0.05, "geopolitics", ["geopolitics"]),
        _mk("n3", "ukraine-ceasefire", "Will Russia and Ukraine agree a ceasefire?",
            0.33, 0.20, "geopolitics", ["geopolitics"]),
        _mk("n4", "fed-rates", "Will the Fed cut interest rates in September?",
            0.55, 0.40, "finance", ["finance", "fed"]),
        _mk("n5", "nato-summit", "Will NATO admit a new member in 2026?",
            0.40, 0.28, "politics", ["politics"]),
    ])
    db.session.commit()

    first = market_curator.generate_world_events(brief_date=today, min_markets=1)
    assert first
    shown = first[0]["event_slug"]

    # A brief published after that lookup shows the same event — a regenerate
    # must see it rather than reusing a warmed snapshot.
    db.session.add(DailyBrief(
        date=today - timedelta(days=1), brief_type="daily", status="published",
        title="Published since",
        world_events=[{"market_id": first[0]["market_id"], "event_slug": shown}],
    ))
    db.session.commit()

    second = market_curator.generate_world_events(brief_date=today, min_markets=1)
    assert second
    assert shown not in [e["event_slug"] for e in second]


def test_event_key_dedupes_by_event_slug():
    from app.polymarket.curation import event_key

    a = SimpleNamespace(event_slug="next-prime-minister-of-ethiopia", slug="belete", id=1)
    b = SimpleNamespace(event_slug="next-prime-minister-of-ethiopia", slug="gedion", id=2)
    assert event_key(a) == event_key(b)


def test_infer_category_and_upsert_tags(db):
    from app.polymarket.service import PolymarketService

    service = PolymarketService()
    assert service._infer_category_from_tags(["ethiopia", "elections", "politics"]) == "politics"

    event_meta = {
        "411239": {
            "slug": "next-prime-minister-of-ethiopia",
            "tags": ["ethiopia", "elections", "politics"],
            "category": "politics",
            "open_interest": 12000,
        }
    }
    market_data = {
        "conditionId": "0xabc123test",
        "slug": "will-belete-molla-be-pm",
        "question": "Will Belete Molla be the next Prime Minister of Ethiopia?",
        "description": "Election market",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["t1", "t2"]',
        "volume24hr": 50000,
        "volumeNum": 100000,
        "liquidityNum": 8000,
        "outcomePrices": '["0.42", "0.58"]',
        "oneDayPriceChange": 0.05,
        "active": True,
        "events": [{"id": 411239, "slug": "next-prime-minister-of-ethiopia"}],
    }

    result, market = service._upsert_market(market_data, event_meta=event_meta)
    db.session.commit()

    assert result == "created"
    assert market.event_slug == "next-prime-minister-of-ethiopia"
    assert market.category == "politics"
    assert "elections" in market.tags
    assert market.probability == pytest.approx(0.42)
    assert market.probability_24h_ago == pytest.approx(0.37)
    assert market.trader_count == 12000
    assert "event/" in market.polymarket_url


def test_world_events_dedupes_event_and_skips_recent(db):
    from app.models import DailyBrief, PolymarketMarket
    from app.polymarket.curation import market_curator

    today = date.today()
    yesterday = today - timedelta(days=1)

    m1 = PolymarketMarket(
        condition_id="c1",
        slug="iran-invade-a",
        event_slug="us-invade-iran",
        question="Will the U.S. invade Iran before 2027?",
        category="politics",
        tags=["politics", "geopolitics"],
        probability=0.22,
        probability_24h_ago=0.12,
        volume_24h=80_000,
        liquidity=10_000,
        is_active=True,
        end_date=utcnow_naive() + timedelta(days=100),
    )
    m2 = PolymarketMarket(
        condition_id="c2",
        slug="iran-invade-b",
        event_slug="us-invade-iran",
        question="Will the U.S. invade Iran in 2026?",
        category="politics",
        tags=["politics", "geopolitics"],
        probability=0.18,
        probability_24h_ago=0.10,
        volume_24h=70_000,
        liquidity=10_000,
        is_active=True,
        end_date=utcnow_naive() + timedelta(days=100),
    )
    m3 = PolymarketMarket(
        condition_id="c3",
        slug="fed-cut",
        event_slug="fed-rates-july",
        question="Will the Fed decrease interest rates by 25 bps after the July meeting?",
        category="finance",
        tags=["finance", "fed"],
        probability=0.55,
        probability_24h_ago=0.40,
        volume_24h=90_000,
        liquidity=12_000,
        is_active=True,
        end_date=utcnow_naive() + timedelta(days=20),
    )
    m4 = PolymarketMarket(
        condition_id="c4",
        slug="taiwan",
        event_slug="china-taiwan",
        question="Will China invade Taiwan before 2027?",
        category="geopolitics",
        tags=["geopolitics", "china"],
        probability=0.11,
        probability_24h_ago=0.05,
        volume_24h=60_000,
        liquidity=9_000,
        is_active=True,
        end_date=utcnow_naive() + timedelta(days=200),
    )
    m5 = PolymarketMarket(
        condition_id="c5",
        slug="ukraine-ceasefire",
        event_slug="ukraine-ceasefire-2026",
        question="Will Russia and Ukraine agree a ceasefire in 2026?",
        category="geopolitics",
        tags=["geopolitics", "ukraine"],
        probability=0.33,
        probability_24h_ago=0.20,
        volume_24h=55_000,
        liquidity=8_000,
        is_active=True,
        end_date=utcnow_naive() + timedelta(days=150),
    )
    db.session.add_all([m1, m2, m3, m4, m5])
    db.session.commit()

    # Yesterday already showed the Iran event — should be skipped for novelty
    db.session.add(DailyBrief(
        date=yesterday,
        brief_type="daily",
        status="published",
        title="Yesterday",
        world_events=[{
            "market_id": m1.id,
            "event_slug": "us-invade-iran",
            "question": m1.question,
        }],
    ))
    db.session.commit()

    from app.polymarket.curation import get_recent_brief_market_usage
    recent_ids, recent_keys = get_recent_brief_market_usage(
        days=7, exclude_brief_date=today
    )
    assert m1.id in recent_ids
    assert "event:us-invade-iran" in recent_keys

    events = market_curator.generate_world_events(
        min_markets=3,
        max_markets=5,
        brief_date=today,
    )
    assert events is not None
    assert len(events) >= 3

    event_slugs = [e.get("event_slug") for e in events]
    assert len(event_slugs) == len(set(event_slugs))
    assert "us-invade-iran" not in event_slugs


def test_matcher_soft_category_does_not_return_empty(db):
    from app.models import PolymarketMarket, TrendingTopic
    from app.polymarket.matcher import MarketMatcher

    market = PolymarketMarket(
        condition_id="c-match",
        slug="uk-climate-bill",
        event_slug="uk-net-zero",
        question="Will the UK pass net zero legislation in 2026?",
        category="climate",
        tags=["climate", "energy", "uk"],
        probability=0.4,
        probability_24h_ago=0.35,
        volume_24h=15_000,
        liquidity=6_000,
        is_active=True,
        end_date=utcnow_naive() + timedelta(days=60),
    )
    topic = TrendingTopic(
        title="UK climate policy faces parliamentary fight",
        status="published",
        primary_topic="Environment",
        canonical_tags=["climate", "uk", "parliament"],
    )
    db.session.add_all([market, topic])
    db.session.commit()

    matcher = MarketMatcher()
    candidates = matcher._get_candidates(topic, "medium")
    assert candidates
    assert any(c.id == market.id for c in candidates)

    matches = matcher.match_topic(topic, max_matches=1)
    assert matches
    assert matches[0]["market"].id == market.id
