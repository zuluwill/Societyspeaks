"""
Curate Polymarket markets for daily/weekly brief sections.

Design goals for brief UX:
1. Relevance — Market Pulse should track today's topics when possible
2. Movement — prefer markets whose odds actually moved (news signal)
3. Diversity — one market per parent event; spread themes
4. Novelty — avoid repeating the same markets across consecutive briefs
5. Precision — word-boundary keywords; exclude sports/entertainment noise
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.lib.time import utcnow_naive
from app.models import DailyBrief, PolymarketMarket, TrendingTopic

logger = logging.getLogger(__name__)


def _coerce_brief_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _section_list(value: Any) -> List[Dict]:
    """Normalize brief JSON sections (list/dict/JSON string) to a list of dicts."""
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []

# Word-boundary keyword sets (substring matching is intentionally avoided —
# e.g. bare "war" must not match "Warriors").
WORLD_EVENT_KEYWORDS = (
    'trump', 'biden', 'president', 'election', 'elections',
    'war', 'wars', 'conflict', 'military', 'invasion', 'invade',
    'sanctions', 'tariff', 'tariffs', 'nato', 'treaty',
    'summit', 'diplomacy', 'nuclear', 'ceasefire',
    'parliament', 'congress', 'senate', 'government',
    'prime minister', 'chancellor',
    'russia', 'ukraine', 'china', 'iran', 'israel',
    'gaza', 'palestine', 'north korea', 'venezuela', 'taiwan',
    'european union', 'united nations',
    'deport', 'immigration', 'refugee',
    'interest rate', 'interest rates', 'recession',
    'climate', 'paris agreement',
    'coup', 'regime', 'rebel',
)

FINANCE_KEYWORDS = (
    'interest rate', 'interest rates', 'federal reserve', 'inflation', 'gdp',
    'recession', 'unemployment', 'stock market', 'nasdaq',
    'bond', 'yield', 'treasury', 'dollar', 'currency', 'exchange rate',
    'crude oil', 'oil price', 'gold price', 'commodity',
    'bitcoin', 'ethereum', 'crypto', 'btc',
    'tariff', 'tariffs', 'trade war', 'trade deal', 'sanctions',
    'earnings', 'ipo', 'merger', 'acquisition', 'bankruptcy',
    'central bank', 'ecb', 'imf', 'world bank',
    'monetary policy', 'fiscal', 'deficit', 'debt ceiling',
    'jobs report', 'payroll', 'cpi', 'ppi', 'pce',
    'rate cut', 'rate hike', 'quantitative',
    'hedge fund', 'valuation',
)

SPORTS_ENTERTAINMENT_KEYWORDS = (
    'nba', 'nfl', 'mlb', 'nhl', 'mls', 'ufc', 'wwe', 'fifa',
    'premier league', 'champions league', 'la liga', 'bundesliga',
    'serie a', 'ligue 1', 'eredivisie',
    'super bowl', 'world series', 'stanley cup', 'nba finals',
    'world cup', 'fifa world cup',
    'mvp', 'draft pick', 'touchdown', 'home run', 'slam dunk',
    'oscar', 'grammy', 'emmy', 'golden globe',
    'bachelor', 'bachelorette', 'reality tv', 'american idol',
)

WORLD_TAG_HINTS = {
    'politics', 'elections', 'geopolitics', 'government', 'diplomacy',
    'international', 'war', 'military', 'global-elections', 'main-election',
    'finance', 'economics', 'fed', 'inflation', 'crypto', 'business',
    'climate', 'energy', 'immigration',
}

SPORTS_TAG_HINTS = {
    'sports', 'nba', 'nfl', 'mlb', 'nhl', 'soccer', 'football', 'tennis',
    'golf', 'ufc', 'mma', 'cricket', 'formula-1', 'f1', 'olympics',
    'entertainment', 'movies', 'music', 'awards', 'pop-culture',
}

# Soft category labels shown in the World Events UI
TAG_TO_DISPLAY_CATEGORY = {
    'politics': 'politics',
    'elections': 'politics',
    'geopolitics': 'geopolitics',
    'war': 'geopolitics',
    'military': 'geopolitics',
    'finance': 'economy',
    'economics': 'economy',
    'fed': 'economy',
    'inflation': 'economy',
    'crypto': 'markets',
    'business': 'economy',
    'climate': 'climate',
    'energy': 'climate',
    'immigration': 'society',
}


def word_boundary_pattern(keywords: Sequence[str]) -> re.Pattern:
    """Compile an OR pattern that only matches whole words/phrases."""
    parts = sorted((k.strip() for k in keywords if k and k.strip()), key=len, reverse=True)
    if not parts:
        return re.compile(r'(?!)')  # never matches
    return re.compile(r'\b(?:' + '|'.join(re.escape(p) for p in parts) + r')\b', re.IGNORECASE)


_WORLD_PATTERN = word_boundary_pattern(WORLD_EVENT_KEYWORDS)
_FINANCE_PATTERN = word_boundary_pattern(FINANCE_KEYWORDS)
_SPORTS_PATTERN = word_boundary_pattern(SPORTS_ENTERTAINMENT_KEYWORDS)


def market_text(market: PolymarketMarket) -> str:
    return f"{market.question or ''} {(market.description or '')[:240]}"


def market_tag_set(market: PolymarketMarket) -> Set[str]:
    tags = set()
    for tag in market.tags or []:
        if isinstance(tag, str) and tag.strip():
            tags.add(tag.strip().lower())
    if market.category:
        tags.add(market.category.strip().lower())
    return tags


def is_sports_or_entertainment(market: PolymarketMarket) -> bool:
    tags = market_tag_set(market)
    if tags & SPORTS_TAG_HINTS:
        return True
    return bool(_SPORTS_PATTERN.search(market_text(market)))


def is_world_relevant(market: PolymarketMarket) -> bool:
    if is_sports_or_entertainment(market):
        return False
    tags = market_tag_set(market)
    if tags & WORLD_TAG_HINTS:
        return True
    return bool(_WORLD_PATTERN.search(market_text(market)))


def is_finance_relevant(market: PolymarketMarket) -> bool:
    if is_sports_or_entertainment(market):
        return False
    tags = market_tag_set(market)
    if tags & {'finance', 'economics', 'fed', 'inflation', 'crypto', 'business', 'markets'}:
        return True
    return bool(_FINANCE_PATTERN.search(market_text(market)))


def display_category(market: PolymarketMarket) -> str:
    tags = market_tag_set(market)
    for tag, label in TAG_TO_DISPLAY_CATEGORY.items():
        if tag in tags:
            return label
    if market.category:
        return market.category.lower()
    return 'world'


def event_key(market: PolymarketMarket) -> str:
    """Stable key for parent-event dedupe."""
    if getattr(market, 'event_slug', None):
        return f"event:{market.event_slug}"
    if market.slug:
        # No event_slug (pre-pm002 rows, or an /events miss) — the market slug
        # only dedupes against itself, not its sibling outcomes.
        return f"market:{market.slug}"
    return f"id:{market.id}"


def get_recent_brief_market_usage(
    days: int = 7,
    exclude_brief_date: Optional[date] = None,
) -> Tuple[Set[int], Set[str]]:
    """Collect market IDs / event keys shown in recent published briefs."""
    exclude_brief_date = _coerce_brief_date(exclude_brief_date)
    cutoff = (exclude_brief_date or date.today()) - timedelta(days=days)

    # Filter in SQL and select only the JSON columns we read — briefs accumulate
    # daily and carry large bodies we have no use for here.
    query = DailyBrief.query.with_entities(
        DailyBrief.market_pulse, DailyBrief.world_events
    ).filter(
        DailyBrief.brief_type.in_(['daily', 'weekly']),
        DailyBrief.status.in_(['ready', 'published']),
        DailyBrief.date >= cutoff,
    )
    if exclude_brief_date is not None:
        query = query.filter(DailyBrief.date != exclude_brief_date)

    market_ids: Set[int] = set()
    event_keys: Set[str] = set()
    for brief in query.all():
        for section in _section_list(brief.market_pulse) + _section_list(brief.world_events):
            mid = section.get('market_id')
            if mid is not None:
                try:
                    market_ids.add(int(mid))
                except (TypeError, ValueError):
                    pass
            slug = section.get('event_slug')
            if slug:
                event_keys.add(f"event:{slug}")
            elif mid is not None:
                event_keys.add(f"id:{mid}")
    return market_ids, event_keys


def brief_market_score(
    market: PolymarketMarket,
    *,
    topic_bonus: float = 0.0,
    recently_shown: bool = False,
    min_change: float = 0.01,
) -> Optional[float]:
    """
    Rank markets for brief inclusion.

    Movement dominates; volume is a soft liquidity gate (not the main driver).
    Topic-linked markets may pass with smaller moves.
    """
    change = market.change_24h
    if change is None:
        return None

    abs_change = abs(change)
    # Topic-linked markets clear a lower bar, not no bar — a frozen market has
    # no place under a "markets moving with today's stories" heading.
    effective_min = min(min_change, 0.005) if topic_bonus > 0 else min_change
    if abs_change < effective_min:
        return None

    volume = max(float(market.volume_24h or 0), 1.0)
    # log10(volume) capped so $50k and $5M don't diverge wildly
    liquidity = min(math.log10(volume + 10.0) / 5.5, 1.0)

    score = (abs_change * 100.0) * (0.55 + 0.45 * liquidity)
    score += topic_bonus

    end_date = market.end_date
    if end_date is not None:
        try:
            days_left = (end_date.replace(tzinfo=None) - utcnow_naive()).days
        except Exception:
            days_left = None
        if days_left is not None and 0 <= days_left <= 21:
            score *= 1.12

    if recently_shown:
        score *= 0.2

    return score


def _active_tradable_query(min_volume: float = 2000.0):
    now = utcnow_naive()
    return PolymarketMarket.query.filter(
        PolymarketMarket.is_active == True,  # noqa: E712
        PolymarketMarket.volume_24h >= min_volume,
        PolymarketMarket.probability.isnot(None),
        (PolymarketMarket.end_date > now) | PolymarketMarket.end_date.is_(None),
    )


def _signal_dict(
    market: PolymarketMarket,
    *,
    matched_topic: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict:
    signal = market.to_signal_dict()
    signal['matched_topic'] = matched_topic
    signal['category'] = category or display_category(market)
    if getattr(market, 'event_slug', None):
        signal['event_slug'] = market.event_slug
        signal['url'] = f"https://polymarket.com/event/{market.event_slug}"
    return signal


def _topic_title_tokens(title: str) -> Set[str]:
    stop = {
        'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'with',
        'as', 'at', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'this',
        'that', 'its', 'it', 'new', 'after', 'over', 'into', 'about',
    }
    tokens = re.findall(r"[a-z0-9]{3,}", (title or '').lower())
    return {t for t in tokens if t not in stop}


def _title_overlap_bonus(topic: TrendingTopic, market: PolymarketMarket) -> float:
    topic_tokens = _topic_title_tokens(topic.title or '')
    if not topic_tokens:
        return 0.0
    market_tokens = _topic_title_tokens(market.question or '')
    overlap = topic_tokens & market_tokens
    if not overlap:
        return 0.0
    return min(8.0, 2.5 * len(overlap))


class MarketCurator:
    """Build Market Pulse and World Events payloads for a brief."""

    # Novelty windows. Market Pulse follows the news, so a market the day's
    # topics point back at may resurface sooner than the World Events rotation,
    # which picks freely from the whole board.
    #
    # Deliberately uncached: the lookup is one indexed query over a handful of
    # rows, and this class is a process-lifetime singleton — a cache here goes
    # stale against briefs published after it was warmed.
    MARKET_PULSE_NOVELTY_DAYS = 5
    WORLD_EVENTS_NOVELTY_DAYS = 7

    def generate_market_pulse(
        self,
        topics: Sequence[TrendingTopic],
        *,
        max_markets: int = 3,
        brief_date: Optional[date] = None,
    ) -> Optional[List[Dict]]:
        from app.polymarket.matcher import market_matcher

        recent_ids, recent_events = get_recent_brief_market_usage(
            days=self.MARKET_PULSE_NOVELTY_DAYS, exclude_brief_date=brief_date
        )
        signals: List[Dict] = []
        seen_market_ids: Set[int] = set()
        seen_events: Set[str] = set()

        def _try_add(market: PolymarketMarket, matched_topic: Optional[str], topic_bonus: float) -> bool:
            if market is None or market.id in seen_market_ids:
                return False
            if market.probability is None or not market.is_active:
                return False
            if is_sports_or_entertainment(market):
                return False

            key = event_key(market)
            if key in seen_events:
                return False

            recently = market.id in recent_ids or key in recent_events
            # Hard-skip recently shown unless strongly topic-linked
            if recently and topic_bonus < 5:
                return False

            score = brief_market_score(
                market,
                topic_bonus=topic_bonus,
                recently_shown=recently,
                min_change=0.008 if topic_bonus > 0 else 0.01,
            )
            if score is None:
                return False

            signals.append(_signal_dict(market, matched_topic=matched_topic))
            seen_market_ids.add(market.id)
            seen_events.add(key)
            logger.info(
                "Market Pulse: '%s' (topic=%s, score=%.2f)",
                (market.question or '')[:50],
                (matched_topic or '—')[:40],
                score,
            )
            return True

        # Pass 1 — link to today's topics (stored match, then live match).
        # One candidate pool for the whole pass: match_topic would otherwise
        # re-download ~2 MB of market embeddings per topic.
        live_pool = None
        for topic in list(topics)[:10]:
            if len(signals) >= max_markets:
                break

            market = market_matcher.get_best_match_for_topic(topic.id)
            if market and _try_add(market, (topic.title or '')[:80], topic_bonus=10 + _title_overlap_bonus(topic, market)):
                continue

            if live_pool is None:
                live_pool = market_matcher._load_candidate_pool('medium')
            live_matches = market_matcher.match_topic(
                topic,
                max_matches=1,
                min_quality_tier='medium',
                candidate_pool=live_pool,
            )
            if live_matches:
                market = live_matches[0]['market']
                bonus = 8 + float(live_matches[0].get('similarity', 0)) * 5
                bonus += _title_overlap_bonus(topic, market)
                _try_add(market, (topic.title or '')[:80], topic_bonus=bonus)

        # Pass 2 — fill with moving finance / topic-overlapping markets
        if len(signals) < max_markets:
            topic_tokens: Set[str] = set()
            for topic in topics[:10]:
                topic_tokens |= _topic_title_tokens(topic.title or '')

            candidates = (
                _active_tradable_query(min_volume=3000)
                .order_by(PolymarketMarket.volume_24h.desc())
                .limit(800)
                .all()
            )
            scored: List[Tuple[float, PolymarketMarket, Optional[str], float]] = []
            for market in candidates:
                if market.id in seen_market_ids:
                    continue
                if event_key(market) in seen_events:
                    continue
                if is_sports_or_entertainment(market):
                    continue

                overlap = _topic_title_tokens(market.question or '') & topic_tokens
                finance = is_finance_relevant(market)
                if not finance and len(overlap) < 2:
                    continue

                recently = market.id in recent_ids or event_key(market) in recent_events
                if recently:
                    continue

                bonus = 3.0 * len(overlap)
                if finance:
                    bonus += 1.5
                score = brief_market_score(market, topic_bonus=bonus, recently_shown=False)
                if score is None:
                    continue
                matched = None
                if overlap:
                    # Attribute to the first topic that shares tokens
                    for topic in topics[:10]:
                        if _topic_title_tokens(topic.title or '') & overlap:
                            matched = (topic.title or '')[:80]
                            break
                scored.append((score, market, matched, bonus))

            scored.sort(key=lambda x: x[0], reverse=True)
            for score, market, matched, bonus in scored:
                if len(signals) >= max_markets:
                    break
                _try_add(market, matched, topic_bonus=bonus)

        if not signals:
            logger.info("No market signals found for Market Pulse section")
            return None
        return signals

    def generate_world_events(
        self,
        *,
        seen_market_ids: Optional[Set[int]] = None,
        min_markets: int = 3,
        max_markets: int = 5,
        brief_date: Optional[date] = None,
    ) -> Optional[List[Dict]]:
        seen_market_ids = set(seen_market_ids or ())
        recent_ids, recent_events = get_recent_brief_market_usage(
            days=self.WORLD_EVENTS_NOVELTY_DAYS, exclude_brief_date=brief_date
        )

        candidates = (
            _active_tradable_query(min_volume=2500)
            .order_by(PolymarketMarket.volume_24h.desc())
            .limit(1200)
            .all()
        )

        scored: List[Tuple[float, PolymarketMarket]] = []
        for market in candidates:
            if market.id in seen_market_ids:
                continue
            if not is_world_relevant(market):
                continue

            key = event_key(market)
            # Hard-skip markets/events shown in recent briefs so the section rotates
            if market.id in recent_ids or key in recent_events:
                continue

            score = brief_market_score(
                market,
                topic_bonus=0.0,
                recently_shown=False,
                min_change=0.01,
            )
            if score is None:
                continue
            scored.append((score, market))

        scored.sort(key=lambda x: x[0], reverse=True)

        selected: List[Dict] = []
        used_events: Set[str] = set()
        used_categories: Dict[str, int] = {}

        def _pick(pool: List[Tuple[float, PolymarketMarket]], *, enforce_category_cap: bool) -> None:
            for score, market in pool:
                if len(selected) >= max_markets:
                    return
                key = event_key(market)
                if key in used_events:
                    continue

                category = display_category(market)
                # Soft diversity: at most 2 markets in the same display category
                if enforce_category_cap and used_categories.get(category, 0) >= 2:
                    continue

                selected.append(_signal_dict(market, matched_topic=None, category=category))
                used_events.add(key)
                used_categories[category] = used_categories.get(category, 0) + 1
                logger.info(
                    "World Events: '%s' (%s, change=%s, score=%.2f)",
                    (market.question or '')[:60],
                    category,
                    market.change_24h_formatted,
                    score,
                )

        _pick(scored, enforce_category_cap=True)

        # If novelty filtering left us short, allow recently-shown movers back in
        # (still event-deduped) rather than omitting the section.
        if len(selected) < min_markets:
            refill: List[Tuple[float, PolymarketMarket]] = []
            for market in candidates:
                if market.id in seen_market_ids:
                    continue
                if event_key(market) in used_events:
                    continue
                if not is_world_relevant(market):
                    continue
                score = brief_market_score(market, min_change=0.008)
                if score is None:
                    continue
                refill.append((score, market))
            refill.sort(key=lambda x: x[0], reverse=True)
            _pick(refill, enforce_category_cap=False)

        if len(selected) < min_markets:
            logger.info(
                "World Events: only %s qualifying markets (minimum %s), skipping section",
                len(selected),
                min_markets,
            )
            return None
        return selected


market_curator = MarketCurator()
