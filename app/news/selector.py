"""
Automated Topic Selection for News Transparency Page

Selects ALL published topics from last 24 hours that meet quality thresholds.
Unlike the brief selector (which picks 3-5), this shows comprehensive coverage
organized by political spectrum diversity.
"""

from datetime import datetime, timedelta
from typing import List
from app.models import TrendingTopic, AdminSettings
from app.brief.coverage_analyzer import CoverageAnalyzer
import logging

logger = logging.getLogger(__name__)


class NewsPageSelector:
    """
    Automated selection of topics for news transparency page.

    Key differences from BriefSelector:
    - Shows ALL topics meeting thresholds (not just 3-5)
    - Lower quality bar (0.5 vs 0.6 civic score)
    - No exclusion period (show everything from today)
    - Organizes by source leaning diversity (interleave left/center/right)
    """

    # Default thresholds (can be overridden by AdminSettings)
    DEFAULT_MIN_CIVIC_SCORE = 0.5
    DEFAULT_MIN_QUALITY_SCORE = 0.4
    DEFAULT_MAX_SENSATIONALISM = 0.8
    DEFAULT_LOOKBACK_HOURS = 24
    DEFAULT_MIN_SOURCES = 1

    def __init__(self):
        """Initialize selector with thresholds from AdminSettings or defaults."""
        # Load thresholds from admin settings
        settings = AdminSettings.get('news_page_thresholds', {})

        self.min_civic_score = settings.get('min_civic_score', self.DEFAULT_MIN_CIVIC_SCORE)
        self.min_quality_score = settings.get('min_quality_score', self.DEFAULT_MIN_QUALITY_SCORE)
        self.max_sensationalism = settings.get('max_sensationalism', self.DEFAULT_MAX_SENSATIONALISM)
        self.lookback_hours = settings.get('lookback_hours', self.DEFAULT_LOOKBACK_HOURS)
        self.min_sources = settings.get('min_sources', self.DEFAULT_MIN_SOURCES)

    def select_topics(self) -> List[TrendingTopic]:
        """
        Get all published topics from last 24h that meet quality thresholds.

        Returns topics organized by source leaning diversity (interleaved).
        """
        cutoff = datetime.utcnow() - timedelta(hours=self.lookback_hours)

        # Query topics (articles relationship is lazy='dynamic', accessed on-demand)
        candidates = TrendingTopic.query.filter(
            TrendingTopic.status == 'published',
            TrendingTopic.published_at >= cutoff,
            TrendingTopic.civic_score >= self.min_civic_score,
            TrendingTopic.quality_score >= self.min_quality_score,
            TrendingTopic.source_count >= self.min_sources
        ).order_by(TrendingTopic.published_at.desc()).all()

        # Apply additional filters
        filtered = []
        for topic in candidates:
            # Check sensationalism
            avg_sensationalism = self._get_avg_sensationalism(topic)
            if avg_sensationalism > self.max_sensationalism:
                logger.debug(f"Excluding topic {topic.id}: sensationalism {avg_sensationalism:.2f} > {self.max_sensationalism}")
                continue

            # Exclude topics with defamation risk
            if topic.risk_flag and topic.risk_reason and 'defamation' in topic.risk_reason.lower():
                logger.debug(f"Excluding topic {topic.id}: defamation risk")
                continue

            filtered.append(topic)

        logger.info(f"Selected {len(filtered)} topics for news page (from {len(candidates)} candidates)")

        # Organize by source diversity (interleave left/center/right)
        return self._organize_by_source_diversity(filtered)

    def _get_avg_sensationalism(self, topic: TrendingTopic) -> float:
        """Calculate average sensationalism score from topic's articles."""
        if not topic.articles:
            return 0.0

        scores = [
            article.article.sensationalism_score
            for article in topic.articles
            if article.article and article.article.sensationalism_score is not None
        ]

        if not scores:
            return 0.0

        return sum(scores) / len(scores)

    def _organize_by_source_diversity(self, topics: List[TrendingTopic]) -> List[TrendingTopic]:
        """
        Organize topics to ensure balanced representation across political spectrum.

        Strategy:
        1. Calculate coverage distribution for each topic
        2. Classify as left/center/right based on dominant coverage
        3. Interleave topics: center, left, right, center, left, right...

        This ensures users see a balanced diet of perspectives.
        """
        left_topics = []
        center_topics = []
        right_topics = []

        for topic in topics:
            try:
                analyzer = CoverageAnalyzer(topic)
                coverage = analyzer.calculate_distribution()
                dist = coverage.get('distribution', {})

                # Classify by dominant perspective (most coverage)
                left_pct = dist.get('left', 0)
                center_pct = dist.get('center', 0)
                right_pct = dist.get('right', 0)

                if left_pct > max(center_pct, right_pct):
                    left_topics.append(topic)
                elif right_pct > max(center_pct, left_pct):
                    right_topics.append(topic)
                else:
                    center_topics.append(topic)

            except Exception as e:
                logger.warning(f"Error analyzing coverage for topic {topic.id}: {e}")
                # Default to center if analysis fails
                center_topics.append(topic)

        # Interleave topics for balanced display
        organized = []
        max_len = max(len(left_topics), len(center_topics), len(right_topics))

        for i in range(max_len):
            # Interleave: center, left, right, center, left, right...
            if i < len(center_topics):
                organized.append(center_topics[i])
            if i < len(left_topics):
                organized.append(left_topics[i])
            if i < len(right_topics):
                organized.append(right_topics[i])

        logger.info(
            f"Organized {len(organized)} topics by diversity: "
            f"{len(left_topics)} left, {len(center_topics)} center, {len(right_topics)} right"
        )

        return organized

    def get_current_settings(self) -> dict:
        """Get current threshold settings (for admin UI)."""
        return {
            'min_civic_score': self.min_civic_score,
            'min_quality_score': self.min_quality_score,
            'max_sensationalism': self.max_sensationalism,
            'lookback_hours': self.lookback_hours,
            'min_sources': self.min_sources
        }


def get_topic_leaning(topic: TrendingTopic) -> str:
    """
    Helper function to determine a topic's dominant political leaning.

    Returns: 'left', 'center', or 'right'
    """
    try:
        analyzer = CoverageAnalyzer(topic)
        coverage = analyzer.calculate_distribution()
        dist = coverage.get('distribution', {})

        left_pct = dist.get('left', 0)
        center_pct = dist.get('center', 0)
        right_pct = dist.get('right', 0)

        if left_pct > max(center_pct, right_pct):
            return 'left'
        elif right_pct > max(center_pct, left_pct):
            return 'right'
        else:
            return 'center'

    except Exception:
        return 'center'  # Default to center if analysis fails
