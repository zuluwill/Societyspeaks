"""
Market Matcher Service

Automatically matches TrendingTopics to relevant Polymarket markets using:
1. Tag/category affinity (Society Speaks topics -> Polymarket event tags)
2. Embedding similarity (semantic matching)
3. Keyword / title overlap (fallback)

Design Principles:
1. High precision over recall - only match when confident
2. No false positives - better to miss a match than show irrelevant market
3. Soft category filters — never return zero candidates just because tags differ
4. Batch operations for efficiency
5. Results cached in TopicMarketMatch table
"""

import logging
import re
from datetime import timedelta
from typing import Optional, List, Dict, Set

import numpy as np
from sqlalchemy import or_
from sqlalchemy.orm import undefer

from app import db
from app.lib.time import utcnow_naive
from app.models import TrendingTopic, PolymarketMarket, TopicMarketMatch

logger = logging.getLogger(__name__)


class CandidatePool:
    """Markets for one matching pass, with their embeddings parsed once.

    ``question_embedding`` is ~21 KB of JSON per market and the candidate SQL
    does not depend on the topic, so a batch run loads this once and reuses it
    for every topic instead of re-downloading ~2 MB per topic.

    Vectors are kept as plain numpy arrays keyed by market id so the maths
    neither re-parses JSON per topic nor re-reads attributes that a mid-run
    ``db.session.commit()`` would have expired.
    """

    __slots__ = ('markets', 'vectors')

    def __init__(self, markets: List[PolymarketMarket]):
        self.markets = markets
        self.vectors: Dict[int, np.ndarray] = {}
        for market in markets:
            embedding = market.question_embedding
            if embedding:
                self.vectors[market.id] = np.array(embedding)

    def __len__(self) -> int:
        return len(self.markets)


class MarketMatcher:
    """
    Service for matching TrendingTopics to Polymarket markets.

    Usage:
        matcher = MarketMatcher()
        matches = matcher.match_topic(topic)  # Returns list of matches
        matcher.run_batch_matching()  # Process all recent topics
    """

    # Category mapping: Society Speaks topic -> Polymarket event tag slugs
    CATEGORY_MAP = {
        'Politics': ['politics', 'elections', 'government', 'geopolitics'],
        'Economy': ['economics', 'finance', 'fed', 'inflation', 'markets', 'business'],
        'Technology': ['tech', 'ai', 'crypto', 'science'],
        'Geopolitics': ['geopolitics', 'international', 'war', 'diplomacy', 'politics'],
        'Healthcare': ['health', 'covid', 'fda', 'medicine'],
        'Environment': ['climate', 'energy', 'environment'],
        'Business': ['business', 'companies', 'markets', 'finance'],
        'Society': ['social', 'culture', 'legal', 'immigration'],
        'Infrastructure': ['infrastructure', 'transportation'],
        'Education': ['education'],
        'Culture': ['entertainment', 'sports', 'media', 'culture'],
    }

    # Similarity thresholds
    # 0.60 still ensures topical relevance while allowing "related market" matches
    EMBEDDING_THRESHOLD = 0.60
    KEYWORD_MIN_OVERLAP = 2

    # How long before a topic that matched nothing is reconsidered by the
    # 30-minute batch job. Topics with no match never get a TopicMarketMatch
    # row, so without this they were re-matched 48x/day for 7 days. The daily
    # pre-brief pass uses reprocess_existing=True and ignores this window.
    MATCH_RETRY_HOURS = 24

    def __init__(self, embedding_service=None):
        """
        Args:
            embedding_service: Optional embedding service for generating embeddings.
                              If None, will use existing embeddings only.
        """
        self._embedding_service = embedding_service

    def match_topic(self, topic: TrendingTopic,
                    max_matches: int = 2,
                    min_quality_tier: str = 'medium',
                    candidate_pool: Optional['CandidatePool'] = None) -> List[Dict]:
        """
        Find relevant markets for a single topic.

        Args:
            candidate_pool: Pool to match against. Batch callers pass one pool
                for the whole run (see run_batch_matching); when omitted a
                pool is loaded for this call alone.

        Returns:
            List of match dicts with 'market', 'similarity', 'method' keys
            Empty list if no matches found
        """
        try:
            pool = (candidate_pool if candidate_pool is not None
                    else self._load_candidate_pool(min_quality_tier))
            candidates = self._get_candidates(topic, min_quality_tier, pool=pool)
            if not candidates:
                return []

            matches = []

            # Method 1: Embedding similarity
            if topic.topic_embedding:
                embedding_matches = self._match_by_embedding(
                    topic.topic_embedding, candidates, pool=pool
                )
                matches.extend(embedding_matches)

            # Method 2: Keyword / title overlap fallback
            if len(matches) < max_matches:
                keyword_matches = self._match_by_keywords(
                    topic, candidates,
                    exclude_ids=[m['market'].id for m in matches]
                )
                matches.extend(keyword_matches)

            matches.sort(key=lambda x: x['similarity'], reverse=True)
            return matches[:max_matches]

        except Exception as e:
            logger.warning(f"Error matching topic {topic.id}: {e}")
            return []

    def run_batch_matching(self, days_back: int = 7,
                           reprocess_existing: bool = False,
                           min_quality_tier: str = 'medium') -> Dict[str, int]:
        """
        Batch match all recent topics to markets.
        Called by scheduler every 30 minutes.

        The candidate market pool is loaded once for the whole run and shared
        across topics; see _load_candidate_pool. Topics that match nothing
        record market_match_attempted_at so they back off for
        MATCH_RETRY_HOURS instead of returning on every run.
        """
        stats = {'processed': 0, 'matched': 0, 'skipped': 0, 'errors': 0}

        due_query = self._topics_due_for_matching_query(
            days_back, reprocess_existing
        )

        # Existence check without pulling deferred topic_embedding (~16 KB/row).
        if due_query.with_entities(TrendingTopic.id).first() is None:
            logger.info("Market matching: no topics due, skipping candidate load")
            return stats

        pool = self._load_candidate_pool(min_quality_tier)
        if not pool:
            # An empty book is a transient sync gap, not evidence that these
            # topics have no market. Stamping attempted_at would hide them for
            # MATCH_RETRY_HOURS after markets return, and loading embeddings
            # here would still pull ~6 MB of topic vectors for no work.
            logger.info("Market matching: no candidate markets, skipping")
            return stats

        topics = due_query.options(
            undefer(TrendingTopic.topic_embedding)
        ).all()
        logger.info(
            "Market matching: %d topic(s) against %d candidate market(s)",
            len(topics), len(pool),
        )

        attempted_at = utcnow_naive()

        for topic in topics:
            stats['processed'] += 1
            try:
                matches = self.match_topic(
                    topic, min_quality_tier=min_quality_tier, candidate_pool=pool
                )

                # Recorded whether or not we matched: a topic with no market is
                # the normal case and must not be retried every 30 minutes.
                topic.market_match_attempted_at = attempted_at

                if not matches:
                    stats['skipped'] += 1
                    continue

                for match in matches:
                    existing = TopicMarketMatch.query.filter_by(
                        trending_topic_id=topic.id,
                        market_id=match['market'].id
                    ).first()

                    if existing:
                        existing.similarity_score = match['similarity']
                        existing.match_method = match['method']
                        existing.updated_at = utcnow_naive()
                    else:
                        db.session.add(TopicMarketMatch(
                            trending_topic_id=topic.id,
                            market_id=match['market'].id,
                            similarity_score=match['similarity'],
                            match_method=match['method'],
                            probability_at_match=match['market'].probability,
                            volume_at_match=match['market'].volume_24h
                        ))
                    stats['matched'] += 1

            except Exception as e:
                logger.warning(f"Error processing topic {topic.id}: {e}")
                stats['errors'] += 1

        db.session.commit()
        logger.info(f"Market matching complete: {stats}")
        return stats

    def get_best_match_for_topic(self, topic_id: int) -> Optional[PolymarketMarket]:
        """
        Get the best matching market for a topic.
        Returns None if no match exists or market is inactive.
        """
        match = TopicMarketMatch.query.filter_by(
            trending_topic_id=topic_id
        ).join(PolymarketMarket).filter(
            PolymarketMarket.is_active == True  # noqa: E712
        ).order_by(
            TopicMarketMatch.similarity_score.desc()
        ).first()

        if match and match.similarity_score >= self.EMBEDDING_THRESHOLD:
            return match.market
        return None

    def get_market_signal_for_topic(self, topic_id: int) -> Optional[dict]:
        """
        Get market signal data for a topic, ready for use in briefs.
        Returns None if no matching market (graceful degradation).
        """
        market = self.get_best_match_for_topic(topic_id)
        if not market:
            logger.debug(f"No market match for topic {topic_id}")
            return None

        signal = market.to_signal_dict()
        logger.info(
            f"Market signal matched: topic={topic_id} -> "
            f"market='{market.question[:50]}...' "
            f"(prob={market.probability:.0%}, vol=${market.volume_24h:,.0f})"
        )
        return signal

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _topics_due_for_matching_query(
        self, days_back: int, reprocess_existing: bool
    ):
        """Topics the batch job should consider, without undeferring embeddings."""
        cutoff = utcnow_naive() - timedelta(days=days_back)
        query = TrendingTopic.query.filter(
            TrendingTopic.created_at >= cutoff,
            TrendingTopic.status.in_(['approved', 'published', 'pending_review']),
        )
        if not reprocess_existing:
            retry_cutoff = utcnow_naive() - timedelta(hours=self.MATCH_RETRY_HOURS)
            query = query.outerjoin(TopicMarketMatch).filter(
                TopicMarketMatch.id == None,  # noqa: E711
                or_(
                    TrendingTopic.market_match_attempted_at.is_(None),
                    TrendingTopic.market_match_attempted_at < retry_cutoff,
                ),
            )
        return query

    def _load_candidate_pool(self, min_quality_tier: str) -> 'CandidatePool':
        """Load the market pool for a matching pass.

        This SQL deliberately has no topic-dependent term — category
        preference is applied in Python by _get_candidates — so one pool is
        valid for every topic in a batch run. Loading it per topic pulled
        ~2 MB of question_embedding JSON out of Postgres each time, which was
        the single largest source of Neon egress on this project.
        """
        if min_quality_tier == 'high':
            min_volume = PolymarketMarket.HIGH_QUALITY_VOLUME
        elif min_quality_tier == 'medium':
            min_volume = PolymarketMarket.MIN_VOLUME_24H
        else:
            min_volume = 0

        now = utcnow_naive()
        # Deliberately NOT load_only(): measured against production, the
        # embedding is 94% of a pool row (1,286 kB of 1,362 kB for the whole
        # pool), so narrowing the heap columns saves ~4.5% — while any
        # consumer touching an unloaded attribute silently lazy-loads per row.
        # Market Pulse's _signal_dict/to_signal_dict reads most of the row, so
        # a narrowed pool would trade 4.5% for an N+1. undefer() is the part
        # that matters.
        markets = PolymarketMarket.query.options(
            undefer(PolymarketMarket.question_embedding),
        ).filter(
            PolymarketMarket.is_active == True,  # noqa: E712
            PolymarketMarket.volume_24h >= min_volume,
            (PolymarketMarket.end_date > now) | PolymarketMarket.end_date.is_(None),
        ).order_by(PolymarketMarket.volume_24h.desc()).limit(400).all()

        return CandidatePool(markets)

    def _get_candidates(self, topic: TrendingTopic,
                        min_quality_tier: str = 'medium',
                        pool: Optional['CandidatePool'] = None) -> List[PolymarketMarket]:
        """Get candidate markets — soft tag preference, never hard-empty."""

        primary_topic = getattr(topic, 'primary_topic', None)
        # Normalize case: topics may store 'politics' or 'Politics'
        pm_categories = []
        if primary_topic:
            pm_categories = self.CATEGORY_MAP.get(primary_topic) or \
                self.CATEGORY_MAP.get(primary_topic.title()) or \
                self.CATEGORY_MAP.get(primary_topic.capitalize()) or []

        if pool is None:
            pool = self._load_candidate_pool(min_quality_tier)

        # Pull a broad pool, then prefer tag-aligned markets in Python.
        # Hard SQL category filters are wrong when tags were historically null.
        markets = pool.markets
        if not markets:
            return []

        if not pm_categories:
            return markets[:150]

        preferred = [
            m for m in markets
            if self._market_matches_categories(m, pm_categories)
        ]
        if len(preferred) >= 15:
            return preferred[:200]

        # Not enough tagged matches — keep preferred first, then fill
        preferred_ids = {m.id for m in preferred}
        filled = preferred + [m for m in markets if m.id not in preferred_ids]
        return filled[:200]

    def _market_matches_categories(self, market: PolymarketMarket,
                                   pm_categories: List[str]) -> bool:
        cats = {c.lower() for c in pm_categories}
        if market.category and market.category.lower() in cats:
            return True
        tags = {str(t).lower() for t in (market.tags or []) if t}
        return bool(tags & cats)

    def _match_by_embedding(self, topic_embedding: List[float],
                           candidates: List[PolymarketMarket],
                           pool: Optional['CandidatePool'] = None) -> List[Dict]:
        """Match using embedding similarity.

        When a pool is supplied its pre-parsed vectors are used, so a batch run
        converts each market embedding to numpy once rather than once per topic.
        """
        matches = []
        topic_vec = np.array(topic_embedding)

        for market in candidates:
            if pool is not None:
                market_vec = pool.vectors.get(market.id)
                if market_vec is None:
                    continue
            else:
                if not market.question_embedding:
                    continue
                market_vec = np.array(market.question_embedding)

            similarity = self._cosine_similarity(topic_vec, market_vec)

            if similarity >= self.EMBEDDING_THRESHOLD:
                matches.append({
                    'market': market,
                    'similarity': float(similarity),
                    'method': 'embedding'
                })

        return matches

    def _match_by_keywords(self, topic: TrendingTopic,
                          candidates: List[PolymarketMarket],
                          exclude_ids: List[int] = None) -> List[Dict]:
        """Match using tag overlap and significant title tokens."""
        matches = []
        exclude_ids = exclude_ids or []

        topic_tags: Set[str] = set()
        if topic.canonical_tags:
            topic_tags = {str(tag).lower() for tag in topic.canonical_tags if tag}

        title_tokens = self._significant_tokens(topic.title or '')

        for market in candidates:
            if market.id in exclude_ids:
                continue

            market_tags = {str(tag).lower() for tag in (market.tags or []) if tag}
            if market.category:
                market_tags.add(market.category.lower())

            tag_overlap = len(topic_tags & market_tags)
            title_overlap = len(title_tokens & self._significant_tokens(market.question or ''))

            if tag_overlap >= self.KEYWORD_MIN_OVERLAP or title_overlap >= 2:
                similarity = min(0.5 + tag_overlap * 0.1 + title_overlap * 0.08, 0.9)
                # Only accept keyword matches that clear the same bar as embeddings
                if similarity >= self.EMBEDDING_THRESHOLD:
                    matches.append({
                        'market': market,
                        'similarity': similarity,
                        'method': 'keyword'
                    })

        return matches

    @staticmethod
    def _significant_tokens(text: str) -> Set[str]:
        stop = {
            'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'with',
            'as', 'at', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'this',
            'that', 'its', 'it', 'new', 'after', 'over', 'into', 'about', 'will',
            'has', 'have', 'had', 'not', 'but', 'they', 'their',
        }
        tokens = re.findall(r"[a-z0-9]{3,}", (text or '').lower())
        return {t for t in tokens if t not in stop}

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        if vec1.size == 0 or vec2.size == 0:
            return 0.0

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))


# Singleton instance
market_matcher = MarketMatcher()
