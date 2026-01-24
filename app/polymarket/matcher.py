"""
Market Matcher Service

Automatically matches TrendingTopics to relevant Polymarket markets using:
1. Category mapping (Society Speaks categories -> Polymarket categories)
2. Embedding similarity (semantic matching)
3. Keyword overlap (fallback)

Design Principles:
1. High precision over recall - only match when confident
2. No false positives - better to miss a match than show irrelevant market
3. Batch operations for efficiency
4. Results cached in TopicMarketMatch table
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict

import numpy as np

from app import db
from app.models import TrendingTopic, PolymarketMarket, TopicMarketMatch

logger = logging.getLogger(__name__)


class MarketMatcher:
    """
    Service for matching TrendingTopics to Polymarket markets.

    Usage:
        matcher = MarketMatcher()
        matches = matcher.match_topic(topic)  # Returns list of matches
        matcher.run_batch_matching()  # Process all recent topics
    """

    # Category mapping: Society Speaks topic -> Polymarket categories
    CATEGORY_MAP = {
        'Politics': ['politics', 'elections', 'government'],
        'Economy': ['economics', 'fed', 'inflation', 'markets', 'finance'],
        'Technology': ['tech', 'ai', 'crypto', 'science'],
        'Geopolitics': ['geopolitics', 'international', 'war', 'diplomacy'],
        'Healthcare': ['health', 'covid', 'fda', 'medicine'],
        'Environment': ['climate', 'energy', 'environment'],
        'Business': ['business', 'companies', 'markets'],
        'Society': ['social', 'culture', 'legal'],
        'Infrastructure': ['infrastructure', 'transportation'],
        'Education': ['education'],
        'Culture': ['entertainment', 'sports', 'media'],
    }

    # Similarity thresholds
    EMBEDDING_THRESHOLD = 0.75  # Minimum cosine similarity for embedding match
    KEYWORD_MIN_OVERLAP = 2  # Minimum keyword overlap for fallback

    def __init__(self, embedding_service=None):
        """
        Args:
            embedding_service: Optional embedding service for generating embeddings.
                              If None, will use existing embeddings only.
        """
        self._embedding_service = embedding_service

    def match_topic(self, topic: TrendingTopic,
                    max_matches: int = 2,
                    min_quality_tier: str = 'medium') -> List[Dict]:
        """
        Find relevant markets for a single topic.

        Args:
            topic: TrendingTopic to match
            max_matches: Maximum number of matches to return
            min_quality_tier: Minimum market quality ('high', 'medium', 'low')

        Returns:
            List of match dicts with 'market', 'similarity', 'method' keys
            Empty list if no matches found
        """
        try:
            # Get candidate markets by category
            candidates = self._get_candidates(topic, min_quality_tier)
            if not candidates:
                return []

            matches = []

            # Method 1: Embedding similarity
            if topic.topic_embedding:
                embedding_matches = self._match_by_embedding(
                    topic.topic_embedding, candidates
                )
                matches.extend(embedding_matches)

            # Method 2: Keyword overlap (fallback for markets without embeddings)
            if len(matches) < max_matches and topic.canonical_tags:
                keyword_matches = self._match_by_keywords(
                    set(topic.canonical_tags), candidates,
                    exclude_ids=[m['market'].id for m in matches]
                )
                matches.extend(keyword_matches)

            # Sort by similarity and return top matches
            matches.sort(key=lambda x: x['similarity'], reverse=True)
            return matches[:max_matches]

        except Exception as e:
            logger.warning(f"Error matching topic {topic.id}: {e}")
            return []

    def run_batch_matching(self, days_back: int = 7,
                           reprocess_existing: bool = False) -> Dict[str, int]:
        """
        Batch match all recent topics to markets.
        Called by scheduler every 30 minutes.

        Args:
            days_back: Process topics created within this many days
            reprocess_existing: If True, reprocess topics that already have matches

        Returns:
            Stats dict: {'processed': N, 'matched': N, 'skipped': N, 'errors': N}
        """
        stats = {'processed': 0, 'matched': 0, 'skipped': 0, 'errors': 0}

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        query = TrendingTopic.query.filter(
            TrendingTopic.created_at >= cutoff,
            TrendingTopic.status.in_(['approved', 'published', 'pending_review'])
        )

        if not reprocess_existing:
            # Only process topics without existing matches
            query = query.outerjoin(TopicMarketMatch).filter(
                TopicMarketMatch.id == None
            )

        topics = query.all()

        for topic in topics:
            stats['processed'] += 1
            try:
                matches = self.match_topic(topic)

                if not matches:
                    stats['skipped'] += 1
                    continue

                # Store matches
                for match in matches:
                    # Check if match already exists
                    existing = TopicMarketMatch.query.filter_by(
                        trending_topic_id=topic.id,
                        market_id=match['market'].id
                    ).first()

                    if existing:
                        # Update similarity score
                        existing.similarity_score = match['similarity']
                        existing.match_method = match['method']
                        existing.updated_at = datetime.utcnow()
                    else:
                        # Create new match
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

        This is the main method called by brief generator.
        """
        match = TopicMarketMatch.query.filter_by(
            trending_topic_id=topic_id
        ).join(PolymarketMarket).filter(
            PolymarketMarket.is_active == True
        ).order_by(
            TopicMarketMatch.similarity_score.desc()
        ).first()

        if match and match.similarity_score >= TopicMarketMatch.SIMILARITY_THRESHOLD:
            return match.market
        return None

    def get_market_signal_for_topic(self, topic_id: int) -> Optional[dict]:
        """
        Get market signal data for a topic, ready for use in briefs.
        Returns None if no matching market (graceful degradation).

        This is the main entry point for brief generators.
        """
        market = self.get_best_match_for_topic(topic_id)
        if not market:
            return None

        return market.to_signal_dict()

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _get_candidates(self, topic: TrendingTopic,
                        min_quality_tier: str) -> List[PolymarketMarket]:
        """Get candidate markets based on category and quality."""

        # Map topic category to Polymarket categories
        # Use primary_topic if available, otherwise try to infer from title
        primary_topic = getattr(topic, 'primary_topic', None)
        pm_categories = self.CATEGORY_MAP.get(primary_topic, [])

        # Quality threshold
        if min_quality_tier == 'high':
            min_volume = PolymarketMarket.HIGH_QUALITY_VOLUME
        elif min_quality_tier == 'medium':
            min_volume = PolymarketMarket.MIN_VOLUME_24H
        else:
            min_volume = 0

        query = PolymarketMarket.query.filter(
            PolymarketMarket.is_active == True,
            PolymarketMarket.volume_24h >= min_volume
        )

        # If we have category mapping, use it; otherwise search all
        if pm_categories:
            query = query.filter(PolymarketMarket.category.in_(pm_categories))

        return query.limit(100).all()

    def _match_by_embedding(self, topic_embedding: List[float],
                           candidates: List[PolymarketMarket]) -> List[Dict]:
        """Match using embedding similarity."""
        matches = []
        topic_vec = np.array(topic_embedding)

        for market in candidates:
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

    def _match_by_keywords(self, topic_tags: set,
                          candidates: List[PolymarketMarket],
                          exclude_ids: List[int] = None) -> List[Dict]:
        """Match using keyword overlap (fallback)."""
        matches = []
        exclude_ids = exclude_ids or []

        # Normalize tags to lowercase for comparison
        topic_tags_lower = {tag.lower() for tag in topic_tags}

        for market in candidates:
            if market.id in exclude_ids:
                continue

            market_tags = set((tag.lower() for tag in (market.tags or [])))
            overlap = len(topic_tags_lower & market_tags)

            if overlap >= self.KEYWORD_MIN_OVERLAP:
                # Convert overlap to similarity score (0.5-0.9 range)
                similarity = min(0.5 + overlap * 0.1, 0.9)
                matches.append({
                    'market': market,
                    'similarity': similarity,
                    'method': 'keyword'
                })

        return matches

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        if vec1.size == 0 or vec2.size == 0:
            return 0.0

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)


# Singleton instance
market_matcher = MarketMatcher()
