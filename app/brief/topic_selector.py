"""
Automated Topic Selection for Daily Brief

Selects 3-5 high-quality, diverse topics for the evening brief.
Criteria: civic importance, source diversity, topical diversity, recency.
"""

from datetime import datetime, timedelta, date
from typing import List, Optional
from app.models import TrendingTopic, DailyBrief, BriefItem
from app.brief.coverage_analyzer import CoverageAnalyzer
from app import db
import logging

logger = logging.getLogger(__name__)


class TopicSelector:
    """
    Automated selection of topics for daily brief.

    Selection criteria (in order of priority):
    1. Published in last 24 hours
    2. Civic score >= 0.6 (public importance)
    3. Source diversity (min 1 source, but single-source topics require higher quality)
    4. Topic diversity (max 1 per category)
    5. Geographic diversity (mix of scopes)
    6. Not recently featured in brief (30-day exclusion)
    
    Quality compensation for single-source topics:
    - Single-source topics require civic_score >= 0.7 (vs 0.6 for multi-source)
    - Single-source topics require quality_score >= 0.7
    - This ensures single-source topics still meet a high quality bar
    """

    MIN_ITEMS = 3
    MAX_ITEMS = 5
    MIN_CIVIC_SCORE = 0.6
    MIN_CIVIC_SCORE_SINGLE_SOURCE = 0.7  # Higher bar for single-source topics
    MIN_QUALITY_SCORE_SINGLE_SOURCE = 0.7  # Quality check for single-source
    MIN_SOURCES = 1  # Allow single-source topics for brief
    MAX_IMBALANCE = 0.8  # Allow some imbalance, but not extreme
    EXCLUSION_DAYS = 30

    def __init__(self, brief_date: Optional[date] = None):
        self.brief_date = brief_date or date.today()
        self.recent_topic_ids = self._get_recent_brief_topics()

    def _get_recent_brief_topics(self) -> List[int]:
        """Get topic IDs featured in briefs in last N days"""
        cutoff_date = self.brief_date - timedelta(days=self.EXCLUSION_DAYS)

        recent_items = BriefItem.query.join(DailyBrief).filter(
            DailyBrief.date >= cutoff_date,
            DailyBrief.status.in_(['published', 'ready'])
        ).all()

        return [item.trending_topic_id for item in recent_items if item.trending_topic_id]

    def select_topics(self, limit: int = MAX_ITEMS) -> List[TrendingTopic]:
        """
        Select topics for today's brief.

        Args:
            limit: Maximum number of topics to select (default 5)

        Returns:
            List of TrendingTopic instances, ordered by priority
        """
        # Get candidate topics
        candidates = self._get_candidate_topics()

        if not candidates:
            logger.warning(f"No candidate topics found for brief on {self.brief_date}")
            return []

        # Score and rank
        scored_topics = [(topic, self._calculate_brief_score(topic)) for topic in candidates]
        scored_topics.sort(key=lambda x: x[1], reverse=True)

        logger.info(f"Found {len(scored_topics)} candidate topics, scored and ranked")

        # Select diverse topics
        selected = self._select_diverse_topics(scored_topics, limit)

        logger.info(f"Selected {len(selected)} topics for brief on {self.brief_date}")

        return selected

    def _get_candidate_topics(self) -> List[TrendingTopic]:
        """
        Get candidate topics that meet basic criteria.
        
        Applies compensating quality checks for single-source topics:
        - Single-source topics require higher civic_score (0.7 vs 0.6)
        - Single-source topics require higher quality_score (0.7)
        
        Uses progressive lookback: starts with 24h, extends to 48h, then 72h
        if no candidates found. This prevents brief failures on slow news days.

        Returns:
            List of TrendingTopic instances
        """
        # Progressive lookback: try 24h, then 48h, then 72h
        lookback_hours = [24, 48, 72]
        candidates = []
        
        for hours in lookback_hours:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            # Get all potentially eligible topics (basic filters)
            candidates = TrendingTopic.query.filter(
                TrendingTopic.status == 'published',
                TrendingTopic.published_at >= cutoff,
                TrendingTopic.source_count >= self.MIN_SOURCES,
                ~TrendingTopic.id.in_(self.recent_topic_ids)  # Exclude recently featured
            ).all()
            
            if candidates:
                if hours > 24:
                    logger.info(f"Extended lookback to {hours}h to find {len(candidates)} candidates")
                break
        
        if not candidates:
            logger.warning("No candidates found even with 72h lookback")

        # Filter by quality criteria with compensation for single-source topics
        filtered = []
        for topic in candidates:
            # Apply compensating quality checks for single-source topics
            if topic.source_count == 1:
                # Single-source topics need higher civic_score
                if topic.civic_score < self.MIN_CIVIC_SCORE_SINGLE_SOURCE:
                    logger.debug(f"Excluding single-source topic '{topic.title[:50]}...' - "
                                f"civic_score {topic.civic_score:.2f} < {self.MIN_CIVIC_SCORE_SINGLE_SOURCE}")
                    continue
                
                # Single-source topics need higher quality_score
                quality_score = getattr(topic, 'quality_score', 0) or 0
                if quality_score < self.MIN_QUALITY_SCORE_SINGLE_SOURCE:
                    logger.debug(f"Excluding single-source topic '{topic.title[:50]}...' - "
                                f"quality_score {quality_score:.2f} < {self.MIN_QUALITY_SCORE_SINGLE_SOURCE}")
                    continue
                    
                logger.info(f"Accepting single-source topic '{topic.title[:50]}...' - "
                           f"meets quality thresholds (civic={topic.civic_score:.2f}, quality={quality_score:.2f})")
            else:
                # Multi-source topics use standard civic_score threshold
                if topic.civic_score < self.MIN_CIVIC_SCORE:
                    logger.debug(f"Excluding topic '{topic.title[:50]}...' - "
                                f"civic_score {topic.civic_score:.2f} < {self.MIN_CIVIC_SCORE}")
                    continue
            
            # Check coverage balance
            analyzer = CoverageAnalyzer(topic)
            coverage = analyzer.calculate_distribution()

            # Only include if coverage is sufficient and not too imbalanced
            if coverage['has_sufficient_coverage']:
                if coverage['imbalance_score'] <= self.MAX_IMBALANCE or topic.civic_score >= 0.8:
                    filtered.append(topic)
                else:
                    logger.info(f"Excluding topic '{topic.title}' due to coverage imbalance: {coverage['imbalance_score']}")

        logger.info(f"Topic selection: {len(candidates)} candidates -> {len(filtered)} after quality filters")
        return filtered

    def _calculate_brief_score(self, topic: TrendingTopic) -> float:
        """
        Calculate priority score for brief selection.

        Scoring formula (updated Jan 2026):
        - Civic score: 35% (public importance)
        - Quality score: 25% (factual density, non-clickbait)
        - Personal relevance: 15% (direct impact on daily life)
        - Source count: 15% (more sources = better)
        - Coverage balance: 10% (balanced = bonus)

        Returns:
            float: Score from 0-1 (higher = higher priority)
        """
        # Safely get scores with defaults for None values
        civic_score = topic.civic_score if topic.civic_score is not None else 0.5
        quality_score = topic.quality_score if topic.quality_score is not None else 0.5
        source_count = topic.source_count if topic.source_count is not None else 1
        
        # Calculate average personal relevance from articles
        try:
            article_links = topic.articles.all() if hasattr(topic, 'articles') else []
            articles = [link.article for link in article_links if link.article]
            personal_scores = [a.personal_relevance_score for a in articles if a.personal_relevance_score is not None]
            avg_personal_relevance = sum(personal_scores) / len(personal_scores) if personal_scores else 0.5
        except Exception as e:
            logger.warning(f"Error calculating personal relevance for topic {topic.id}: {e}")
            avg_personal_relevance = 0.5

        base_score = (
            civic_score * 0.35 +
            quality_score * 0.25 +
            avg_personal_relevance * 0.15 +
            min(source_count / 10, 1.0) * 0.15  # Cap at 10 sources
        )

        # Coverage balance bonus (with error handling)
        try:
            analyzer = CoverageAnalyzer(topic)
            coverage = analyzer.calculate_distribution()
            imbalance_score = coverage.get('imbalance_score', 0.5)
            balance_bonus = (1 - imbalance_score) * 0.1
        except Exception as e:
            logger.warning(f"Error calculating coverage for topic {topic.id}: {e}")
            balance_bonus = 0.05  # Default to mid-range

        total_score = base_score + balance_bonus

        logger.debug(f"Topic '{topic.title[:50]}...' scored {total_score:.2f} "
                    f"(civic={civic_score:.2f}, quality={quality_score:.2f}, "
                    f"personal={avg_personal_relevance:.2f}, sources={source_count})")

        return total_score

    def _select_diverse_topics(
        self,
        scored_topics: List[tuple],
        limit: int
    ) -> List[TrendingTopic]:
        """
        Select topics ensuring diversity across categories and geography.

        Uses greedy algorithm:
        1. Take highest-scoring topic
        2. Skip next topic if same category or too similar
        3. Continue until limit reached or candidates exhausted

        Args:
            scored_topics: List of (topic, score) tuples, sorted by score desc
            limit: Maximum topics to select

        Returns:
            List of selected TrendingTopic instances
        """
        selected = []
        used_categories = set()
        used_geographic_countries = set()

        for topic, score in scored_topics:
            if len(selected) >= limit:
                break

            # Check category diversity
            if topic.primary_topic and topic.primary_topic in used_categories:
                logger.debug(f"Skipping '{topic.title[:40]}...' - category '{topic.primary_topic}' already used")
                continue

            # Check geographic diversity (prefer mix of scopes)
            # Allow multiple topics from same country if different scopes
            # Use getattr for backwards compatibility with older topics that may not have this data
            geo_scope = getattr(topic, 'geographic_scope', None) or 'global'
            geo_countries = getattr(topic, 'geographic_countries', None)
            
            if geo_scope and geo_countries:
                countries = geo_countries.split(',')
                # If it's country-specific, check if we already have same country
                if geo_scope == 'country':
                    if any(c.strip() in used_geographic_countries for c in countries):
                        logger.debug(f"Skipping '{topic.title[:40]}...' - country already covered")
                        continue

            # Select this topic
            selected.append(topic)
            if topic.primary_topic:
                used_categories.add(topic.primary_topic)
            if geo_countries:
                for country in geo_countries.split(','):
                    used_geographic_countries.add(country.strip())

            logger.info(f"Selected topic #{len(selected)}: '{topic.title}' (score={score:.2f})")

        # Ensure minimum count
        if len(selected) < self.MIN_ITEMS:
            logger.warning(f"Only selected {len(selected)} topics, below minimum of {self.MIN_ITEMS}")
            # Relax constraints and try again if needed
            if len(scored_topics) >= self.MIN_ITEMS:
                selected = [topic for topic, score in scored_topics[:self.MIN_ITEMS]]
                logger.info("Relaxed constraints to meet minimum count")

        return selected

    def validate_selection(self, topics: List[TrendingTopic]) -> dict:
        """
        Validate that selection meets quality standards.
        
        Applies appropriate thresholds based on source count:
        - Single-source topics: higher civic_score and quality_score required
        - Multi-source topics: standard civic_score threshold

        Returns:
            dict: {
                'valid': bool,
                'issues': list of warning strings,
                'summary': dict of selection stats
            }
        """
        issues = []

        if len(topics) < self.MIN_ITEMS:
            issues.append(f"Only {len(topics)} topics (minimum {self.MIN_ITEMS})")

        if len(topics) > self.MAX_ITEMS:
            issues.append(f"Too many topics: {len(topics)} (maximum {self.MAX_ITEMS})")

        # Check category diversity
        categories = [t.primary_topic for t in topics if t.primary_topic]
        if len(categories) != len(set(categories)):
            issues.append("Duplicate categories detected")

        # Check civic scores with source-count-aware thresholds
        low_civic = []
        low_quality_single_source = []
        single_source_count = 0
        
        for t in topics:
            if t.source_count == 1:
                single_source_count += 1
                # Single-source topics have higher thresholds
                if t.civic_score < self.MIN_CIVIC_SCORE_SINGLE_SOURCE:
                    low_civic.append(t)
                quality_score = getattr(t, 'quality_score', 0) or 0
                if quality_score < self.MIN_QUALITY_SCORE_SINGLE_SOURCE:
                    low_quality_single_source.append(t)
            else:
                # Multi-source topics use standard threshold
                if t.civic_score < self.MIN_CIVIC_SCORE:
                    low_civic.append(t)
        
        if low_civic:
            issues.append(f"{len(low_civic)} topics below civic threshold")
        
        if low_quality_single_source:
            issues.append(f"{len(low_quality_single_source)} single-source topics below quality threshold")

        # Check source counts
        low_sources = [t for t in topics if t.source_count < self.MIN_SOURCES]
        if low_sources:
            issues.append(f"{len(low_sources)} topics with insufficient sources")

        summary = {
            'count': len(topics),
            'single_source_count': single_source_count,
            'multi_source_count': len(topics) - single_source_count,
            'avg_civic_score': sum(t.civic_score for t in topics) / len(topics) if topics else 0,
            'avg_source_count': sum(t.source_count for t in topics) / len(topics) if topics else 0,
            'categories': list(set(categories))
        }

        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'summary': summary
        }


def select_todays_topics(limit: int = 5) -> List[TrendingTopic]:
    """
    Convenience function to select topics for today's brief.

    Args:
        limit: Maximum topics to select (default 5)

    Returns:
        List of selected TrendingTopic instances
    """
    selector = TopicSelector()
    return selector.select_topics(limit)


def select_topics_for_date(brief_date: date, limit: int = 5) -> List[TrendingTopic]:
    """
    Select topics for a specific date.

    Args:
        brief_date: Date to generate brief for
        limit: Maximum topics to select

    Returns:
        List of selected TrendingTopic instances
    """
    selector = TopicSelector(brief_date)
    return selector.select_topics(limit)
