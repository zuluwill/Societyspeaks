"""
Automated Topic Selection for Daily Brief

Selects topics for the evening brief, supporting two modes:
1. Legacy flat: 3-5 high-quality topics ordered by priority score
2. Sectioned: Topics selected per section (lead, politics, economy, etc.)
   with geographic gap-fill for the "Around the World" section

Criteria: civic importance, source diversity, topical diversity, recency.
"""

from datetime import datetime, timedelta, date
from app.lib.time import utcnow_naive
from typing import List, Dict, Optional, Tuple
from collections import OrderedDict
from app.models import TrendingTopic, DailyBrief, BriefItem
from app.brief.coverage_analyzer import CoverageAnalyzer
from app.brief.sections import (
    SECTIONS, CATEGORY_TO_SECTION, REGIONS,
    DEPTH_FULL, DEPTH_STANDARD, DEPTH_QUICK,
    get_section_for_category, get_region_for_countries, get_covered_regions,
)
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
    EXCLUSION_DAYS = 5

    def __init__(self, brief_date: Optional[date] = None):
        self.brief_date = brief_date or date.today()
        self.recent_topic_ids, self.recent_headlines = self._get_recent_brief_topics()

    HEADLINE_SIMILARITY_THRESHOLD = 0.7

    def _get_recent_brief_topics(self) -> Tuple[List[int], List[str]]:
        """Get topic IDs and headlines featured in briefs in last N days"""
        cutoff_date = self.brief_date - timedelta(days=self.EXCLUSION_DAYS)

        recent_items = BriefItem.query.join(DailyBrief).filter(
            DailyBrief.date >= cutoff_date,
            DailyBrief.status.in_(['published', 'ready'])
        ).all()

        topic_ids = [item.trending_topic_id for item in recent_items if item.trending_topic_id]
        headlines = [item.headline.lower().strip() for item in recent_items if item.headline]
        return topic_ids, headlines

    @staticmethod
    def _headline_similarity(a: str, b: str) -> float:
        """Calculate word-overlap similarity between two headlines (Jaccard)."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def _is_headline_duplicate(self, title: str) -> bool:
        """Check if a topic title is too similar to a recently featured headline."""
        title_lower = title.lower().strip()
        for recent_headline in self.recent_headlines:
            if self._headline_similarity(title_lower, recent_headline) >= self.HEADLINE_SIMILARITY_THRESHOLD:
                return True
        return False

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
            cutoff = utcnow_naive() - timedelta(hours=hours)
            
            # Get all potentially eligible topics (basic filters)
            # Order by published_at desc to ensure most recent topics are considered first
            candidates = TrendingTopic.query.filter(
                TrendingTopic.status == 'published',
                TrendingTopic.published_at >= cutoff,
                TrendingTopic.source_count >= self.MIN_SOURCES,
                ~TrendingTopic.id.in_(self.recent_topic_ids)  # Exclude recently featured
            ).order_by(TrendingTopic.published_at.desc()).all()
            
            if candidates:
                if hours > 24:
                    logger.info(f"Extended lookback to {hours}h to find {len(candidates)} candidates")
                break
        
        if not candidates:
            logger.warning("No candidates found even with 72h lookback")

        pre_headline_count = len(candidates)
        candidates = [
            t for t in candidates
            if not self._is_headline_duplicate(t.title)
        ]
        if len(candidates) < pre_headline_count:
            logger.info(
                f"Headline similarity filter removed {pre_headline_count - len(candidates)} "
                f"duplicate-story candidates"
            )

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


    # =========================================================================
    # SECTION-BASED SELECTION (New)
    # =========================================================================

    def select_topics_by_section(self) -> Dict[str, List[Tuple[TrendingTopic, str]]]:
        """
        Select topics organized by brief section with assigned depth levels.

        This is the new entry point for sectioned briefs. Returns topics grouped
        by section, each with an assigned depth level.

        Returns:
            Dict mapping section keys to lists of (TrendingTopic, depth) tuples.
            Example:
            {
                'lead': [(topic, 'full')],
                'politics': [(topic, 'standard')],
                'economy': [(topic, 'standard')],
                'society': [(topic, 'standard')],
                'science': [(topic, 'standard')],
                'global_roundup': [(topic, 'quick'), (topic, 'quick'), ...],
            }
        """
        # Get all candidates (reuse existing filtering logic)
        candidates = self._get_candidate_topics()

        if not candidates:
            logger.warning(f"No candidate topics for sectioned brief on {self.brief_date}")
            return {}

        # Score all candidates
        scored = [(topic, self._calculate_brief_score(topic)) for topic in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)

        logger.info(f"Sectioned selection: {len(scored)} scored candidates")

        # Phase 1: Select lead story (highest score overall)
        result = OrderedDict()
        used_topic_ids = set()

        if scored:
            lead_topic, lead_score = scored[0]
            result['lead'] = [(lead_topic, DEPTH_FULL)]
            used_topic_ids.add(lead_topic.id)
            logger.info(f"Lead story: '{lead_topic.title[:50]}...' (score={lead_score:.2f})")

        # Phase 2: Fill themed sections (politics, economy, society, science)
        themed_sections = ['politics', 'economy', 'society', 'science']
        for section_key in themed_sections:
            section_config = SECTIONS[section_key]
            max_items = section_config['max_items']

            # Find best topics for this section
            section_topics = self._select_for_section(
                scored, section_key, max_items, used_topic_ids
            )

            if section_topics:
                result[section_key] = [(t, DEPTH_STANDARD) for t in section_topics]
                used_topic_ids.update(t.id for t in section_topics)

        # Phase 3: Fill global roundup (geographic gap-fill)
        all_selected_topics = []
        for section_items in result.values():
            all_selected_topics.extend([t for t, _ in section_items])

        global_topics = self._select_global_roundup(
            scored, all_selected_topics, used_topic_ids
        )
        if global_topics:
            result['global_roundup'] = [(t, DEPTH_QUICK) for t in global_topics]
            used_topic_ids.update(t.id for t in global_topics)

        # Ensure minimum item count (same guarantee as legacy selector)
        total = sum(len(items) for items in result.values())
        if total < self.MIN_ITEMS and len(scored) >= self.MIN_ITEMS:
            logger.warning(
                f"Sectioned selection only found {total} topics, below minimum "
                f"of {self.MIN_ITEMS}. Backfilling from top-scored candidates."
            )
            # Backfill from highest-scored unused candidates into the lead section
            for topic, score in scored:
                if topic.id in used_topic_ids:
                    continue
                if total >= self.MIN_ITEMS:
                    break
                # Add as full-depth to lead section (or create one)
                if 'lead' not in result:
                    result['lead'] = []
                result['lead'].append((topic, DEPTH_FULL))
                used_topic_ids.add(topic.id)
                total += 1
                logger.info(
                    f"Backfill: '{topic.title[:50]}...' (score={score:.2f})"
                )

        # Log summary
        total = sum(len(items) for items in result.values())
        sections_filled = [k for k in result if result[k]]
        logger.info(
            f"Sectioned selection complete: {total} topics across "
            f"{len(sections_filled)} sections ({', '.join(sections_filled)})"
        )

        # Return empty if still below minimum (let caller fall back to legacy)
        if total < self.MIN_ITEMS:
            logger.warning(
                f"Still only {total} topics after backfill — returning empty "
                f"to trigger legacy fallback"
            )
            return {}

        return result

    def _select_for_section(
        self,
        scored_topics: List[Tuple[TrendingTopic, float]],
        section_key: str,
        max_items: int,
        exclude_ids: set
    ) -> List[TrendingTopic]:
        """
        Select the best topics for a specific section.

        Args:
            scored_topics: All scored candidates (sorted by score desc)
            section_key: Section to fill (e.g., 'politics')
            max_items: Maximum items for this section
            exclude_ids: Topic IDs already used in other sections

        Returns:
            List of selected TrendingTopic instances
        """
        selected = []
        used_categories = set()  # Prevent category duplication within section

        for topic, score in scored_topics:
            if len(selected) >= max_items:
                break

            if topic.id in exclude_ids:
                continue

            # Check if this topic belongs in this section
            topic_section = get_section_for_category(topic.primary_topic)
            if topic_section != section_key:
                continue

            # Prevent duplicate categories within section
            if topic.primary_topic and topic.primary_topic in used_categories:
                continue

            selected.append(topic)
            if topic.primary_topic:
                used_categories.add(topic.primary_topic)

            logger.debug(f"Section '{section_key}': selected '{topic.title[:40]}...' (score={score:.2f})")

        return selected

    def _select_global_roundup(
        self,
        scored_topics: List[Tuple[TrendingTopic, float]],
        already_selected: List[TrendingTopic],
        exclude_ids: set,
        max_items: int = 5
    ) -> List[TrendingTopic]:
        """
        Select topics for the "Around the World" global roundup section.

        Fills geographic gaps by identifying which regions are not covered
        by the main sections, then selecting stories from those regions.

        Uses a lower civic score threshold (0.5) since these are quick-hit items.

        Args:
            scored_topics: All scored candidates
            already_selected: Topics already selected for other sections
            exclude_ids: Topic IDs to exclude
            max_items: Max items for global roundup

        Returns:
            List of selected TrendingTopic instances
        """
        # Identify which regions are already covered
        covered_regions = get_covered_regions(already_selected)
        uncovered_regions = set(REGIONS.keys()) - covered_regions

        logger.info(
            f"Global roundup: covered regions={covered_regions}, "
            f"uncovered={uncovered_regions}"
        )

        selected = []
        used_regions = set()

        # First pass: prioritize uncovered regions
        for topic, score in scored_topics:
            if len(selected) >= max_items:
                break

            if topic.id in exclude_ids:
                continue

            # Lower threshold for global roundup (these get quick-hit treatment)
            if topic.civic_score and topic.civic_score < 0.5:
                continue

            geo_countries = getattr(topic, 'geographic_countries', None)
            if not geo_countries:
                continue

            region = get_region_for_countries(geo_countries)
            if region == 'global':
                continue  # Skip global-scope stories (not region-specific)

            # Prioritize uncovered regions first
            if region in uncovered_regions and region not in used_regions:
                selected.append(topic)
                used_regions.add(region)
                exclude_ids.add(topic.id)
                logger.info(f"Global roundup (gap-fill): '{topic.title[:40]}...' [{region}]")

        # Second pass: fill remaining slots with any region-specific stories
        if len(selected) < max_items:
            for topic, score in scored_topics:
                if len(selected) >= max_items:
                    break

                if topic.id in exclude_ids:
                    continue

                if topic.civic_score and topic.civic_score < 0.5:
                    continue

                geo_countries = getattr(topic, 'geographic_countries', None)
                if not geo_countries:
                    continue

                region = get_region_for_countries(geo_countries)
                if region == 'global':
                    continue

                # Allow max 2 from same region
                region_count = sum(
                    1 for t in selected
                    if get_region_for_countries(
                        getattr(t, 'geographic_countries', '') or ''
                    ) == region
                )
                if region_count >= 2:
                    continue

                selected.append(topic)
                exclude_ids.add(topic.id)
                logger.debug(f"Global roundup (fill): '{topic.title[:40]}...' [{region}]")

        logger.info(f"Global roundup: selected {len(selected)} topics")
        return selected


def select_todays_topics(limit: int = 5) -> List[TrendingTopic]:
    """
    Convenience function to select topics for today's brief (legacy flat mode).

    Args:
        limit: Maximum topics to select (default 5)

    Returns:
        List of selected TrendingTopic instances
    """
    selector = TopicSelector()
    return selector.select_topics(limit)


def select_topics_for_date(brief_date: date, limit: int = 5) -> List[TrendingTopic]:
    """
    Select topics for a specific date (legacy flat mode).

    Args:
        brief_date: Date to generate brief for
        limit: Maximum topics to select

    Returns:
        List of selected TrendingTopic instances
    """
    selector = TopicSelector(brief_date)
    return selector.select_topics(limit)


def select_sectioned_topics_for_date(brief_date: date) -> Dict[str, List[Tuple[TrendingTopic, str]]]:
    """
    Select topics organized by section for a specific date (new sectioned mode).

    Args:
        brief_date: Date to generate brief for

    Returns:
        Dict mapping section keys to lists of (TrendingTopic, depth) tuples
    """
    selector = TopicSelector(brief_date)
    return selector.select_topics_by_section()
