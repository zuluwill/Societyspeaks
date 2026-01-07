"""
Underreported Stories Detection

Identifies stories with high civic importance but low media coverage.
Similar to Ground News "Blindspot" feature.
"""

from datetime import datetime, timedelta
from typing import List, Dict
from app.models import TrendingTopic, DailyBrief, BriefItem
from app.brief.coverage_analyzer import CoverageAnalyzer
import logging

logger = logging.getLogger(__name__)


class UnderreportedDetector:
    """
    Detects underreported stories based on:
    - High civic importance (score >= 0.7)
    - Low source count (< 4 sources)
    - Not recently featured in brief
    - Published recently (within lookback window)
    """

    MIN_CIVIC_SCORE = 0.7
    MAX_SOURCES = 3
    LOOKBACK_DAYS = 7

    def __init__(self, lookback_days: int = LOOKBACK_DAYS):
        self.lookback_days = lookback_days
        self.cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)

    def find_underreported_stories(self, limit: int = 10) -> List[Dict]:
        """
        Find underreported stories.

        Args:
            limit: Maximum stories to return

        Returns:
            List of dicts with story info and metadata
        """
        # Get recent topics with high civic score but low coverage
        candidates = TrendingTopic.query.filter(
            TrendingTopic.status == 'published',
            TrendingTopic.published_at >= self.cutoff_date,
            TrendingTopic.civic_score >= self.MIN_CIVIC_SCORE,
            TrendingTopic.source_count <= self.MAX_SOURCES
        ).order_by(
            TrendingTopic.civic_score.desc()
        ).limit(limit * 2).all()  # Get extras for filtering

        # Filter out stories already featured in brief
        recent_brief_topics = self._get_recent_brief_topics()

        stories = []
        for topic in candidates:
            if topic.id in recent_brief_topics:
                continue

            # Calculate underreporting metrics
            story_data = self._analyze_story(topic)

            if story_data:
                stories.append(story_data)

            if len(stories) >= limit:
                break

        logger.info(f"Found {len(stories)} underreported stories from {len(candidates)} candidates")

        return stories

    def _get_recent_brief_topics(self) -> List[int]:
        """Get topic IDs featured in recent briefs"""
        cutoff = datetime.utcnow() - timedelta(days=self.lookback_days)

        items = BriefItem.query.join(DailyBrief).filter(
            DailyBrief.date >= cutoff.date(),
            DailyBrief.status == 'published'
        ).all()

        return [item.trending_topic_id for item in items if item.trending_topic_id]

    def _analyze_story(self, topic: TrendingTopic) -> Dict:
        """
        Analyze a story to determine underreporting metrics.

        Returns:
            dict with story data and metrics, or None if not underreported
        """
        # Get coverage analysis
        analyzer = CoverageAnalyzer(topic)
        coverage = analyzer.calculate_distribution()

        if coverage['source_count'] == 0:
            return None

        # Calculate underreporting score
        # Higher civic importance + lower coverage = more underreported
        underreporting_score = (
            topic.civic_score * 0.6 +  # Civic importance
            (1 - min(coverage['source_count'] / 10, 1.0)) * 0.4  # Inverse coverage (max 10 sources)
        )

        # Identify coverage gaps
        gaps = self._identify_coverage_gaps(coverage)

        return {
            'topic': topic,
            'civic_score': topic.civic_score,
            'source_count': coverage['source_count'],
            'coverage_distribution': coverage['distribution'],
            'sources_by_leaning': coverage['sources_by_leaning'],
            'underreporting_score': round(underreporting_score, 2),
            'coverage_gaps': gaps,
            'published_at': topic.published_at,
            'primary_topic': topic.primary_topic,
            'geographic_scope': topic.geographic_scope
        }

    def _identify_coverage_gaps(self, coverage: Dict) -> List[str]:
        """
        Identify which perspectives are missing coverage.

        Args:
            coverage: Coverage distribution dict

        Returns:
            List of gap descriptions (e.g., ["No right-leaning coverage", "Limited overall coverage"])
        """
        gaps = []

        dist = coverage['distribution']
        total_sources = coverage['source_count']

        # Check for missing perspectives
        if dist['left'] == 0 and total_sources > 0:
            gaps.append("No left-leaning coverage")

        if dist['center'] == 0 and total_sources > 0:
            gaps.append("No center coverage")

        if dist['right'] == 0 and total_sources > 0:
            gaps.append("No right-leaning coverage")

        # Check for low overall coverage
        if total_sources <= 2:
            gaps.append(f"Only {total_sources} source{'s' if total_sources != 1 else ''}")

        # Check for heavily imbalanced coverage
        if coverage['imbalance_score'] > 0.8:
            dominant = max(dist, key=dist.get)
            gaps.append(f"Coverage dominated by {dominant} outlets")

        return gaps


def get_underreported_stories(days: int = 7, limit: int = 10) -> List[Dict]:
    """
    Convenience function to get underreported stories.

    Args:
        days: Lookback window in days
        limit: Maximum stories to return

    Returns:
        List of underreported story dicts
    """
    detector = UnderreportedDetector(lookback_days=days)
    return detector.find_underreported_stories(limit=limit)


def get_underreported_by_perspective(days: int = 7) -> Dict[str, List[Dict]]:
    """
    Get underreported stories grouped by which perspective is missing.

    Args:
        days: Lookback window in days

    Returns:
        dict: {
            'left_blindspot': [stories only covered by left],
            'right_blindspot': [stories only covered by right],
            'center_blindspot': [stories only covered by center],
            'uncovered': [stories with minimal coverage overall]
        }
    """
    detector = UnderreportedDetector(lookback_days=days)
    all_stories = detector.find_underreported_stories(limit=50)

    blindspots = {
        'left_blindspot': [],  # Only right/center covered
        'right_blindspot': [],  # Only left/center covered
        'center_blindspot': [],  # Only left/right covered
        'uncovered': []  # Very few sources overall
    }

    for story in all_stories:
        dist = story['coverage_distribution']
        sources = story['source_count']

        if sources <= 2:
            blindspots['uncovered'].append(story)
        elif dist['left'] == 0 and (dist['center'] > 0 or dist['right'] > 0):
            blindspots['left_blindspot'].append(story)
        elif dist['right'] == 0 and (dist['left'] > 0 or dist['center'] > 0):
            blindspots['right_blindspot'].append(story)
        elif dist['center'] == 0 and (dist['left'] > 0 or dist['right'] > 0):
            blindspots['center_blindspot'].append(story)

    # Limit each category
    for key in blindspots:
        blindspots[key] = blindspots[key][:5]

    return blindspots
