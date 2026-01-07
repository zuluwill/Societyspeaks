"""
Coverage Analysis Utility

Analyzes political coverage distribution for news topics based on source leanings.
Provides defensible metrics without claiming "truth" or "bias".
"""

from typing import Dict, List, Optional
from app.models import TrendingTopic, NewsArticle, NewsSource
from app.trending.allsides_seed import get_leaning_label, get_leaning_color
from app.trending.scorer import get_system_api_key, extract_json
import logging

logger = logging.getLogger(__name__)


class CoverageAnalyzer:
    """
    Analyzes coverage distribution across political perspectives.

    Uses AllSides/manual source ratings to show:
    - Which perspectives covered a story
    - Balance of coverage across left/center/right
    - Source diversity metrics
    """

    # Leaning thresholds for categorization
    LEFT_THRESHOLD = -0.5
    RIGHT_THRESHOLD = 0.5

    def __init__(self, trending_topic: TrendingTopic):
        self.topic = trending_topic
        self.articles = self._get_topic_articles()

    def _get_topic_articles(self) -> List[NewsArticle]:
        """Get all articles associated with this topic"""
        # TrendingTopic.articles returns TrendingTopicArticle instances
        # We need to extract the actual NewsArticle objects
        if not hasattr(self.topic, 'articles'):
            return []

        article_links = self.topic.articles.all()  # lazy='dynamic' requires .all()
        return [link.article for link in article_links if link.article]

    def calculate_distribution(self) -> Dict:
        """
        Calculate coverage distribution across political leanings.

        Returns:
            dict: {
                'distribution': {'left': 0.25, 'center': 0.50, 'right': 0.25},
                'imbalance_score': 0.25,  # 0=balanced, 1=single perspective
                'source_count': 8,
                'sources_by_leaning': {
                    'left': ['The Guardian', 'The New Yorker'],
                    'center': ['BBC News', 'Financial Times', 'Reuters', 'Axios'],
                    'right': ['The Telegraph', 'The Economist']
                },
                'sensationalism_avg': 0.35,
                'unknown_sources': ['Source X', 'Source Y'],  # Sources without leaning data
                'coverage_notes': 'Coverage from 8 sources across perspectives'
            }
        """
        if not self.articles:
            return self._empty_distribution()

        # Group sources by leaning
        left_sources = []
        center_sources = []
        right_sources = []
        unknown_sources = []

        sensationalism_scores = []

        for article in self.articles:
            source = article.source

            if not source:
                continue

            # Track sensationalism
            if article.sensationalism_score is not None:
                sensationalism_scores.append(article.sensationalism_score)

            # Categorize by leaning
            if source.political_leaning is None:
                if source.name not in [s.name for s in unknown_sources]:
                    unknown_sources.append(source)
            elif source.political_leaning < self.LEFT_THRESHOLD:
                if source.name not in [s.name for s in left_sources]:
                    left_sources.append(source)
            elif source.political_leaning > self.RIGHT_THRESHOLD:
                if source.name not in [s.name for s in right_sources]:
                    right_sources.append(source)
            else:
                if source.name not in [s.name for s in center_sources]:
                    center_sources.append(source)

        # Calculate distribution (only count sources with known leanings)
        total_known = len(left_sources) + len(center_sources) + len(right_sources)

        if total_known == 0:
            return self._empty_distribution()

        distribution = {
            'left': len(left_sources) / total_known,
            'center': len(center_sources) / total_known,
            'right': len(right_sources) / total_known
        }

        # Calculate imbalance (0 = perfectly balanced, 1 = single perspective)
        # Perfect balance would be 0.33/0.33/0.33
        max_pct = max(distribution.values())
        imbalance = (max_pct - 0.33) / 0.67  # Normalize to 0-1 scale
        imbalance = max(0.0, min(1.0, imbalance))  # Clamp to 0-1

        # Average sensationalism
        avg_sensationalism = sum(sensationalism_scores) / len(sensationalism_scores) if sensationalism_scores else None

        # Generate human-readable notes
        coverage_notes = self._generate_coverage_notes(
            len(left_sources),
            len(center_sources),
            len(right_sources),
            len(unknown_sources)
        )

        return {
            'distribution': distribution,
            'imbalance_score': round(imbalance, 2),
            'source_count': total_known,
            'total_articles': len(self.articles),
            'sources_by_leaning': {
                'left': [s.name for s in left_sources],
                'center': [s.name for s in center_sources],
                'right': [s.name for s in right_sources]
            },
            'sensationalism_avg': round(avg_sensationalism, 2) if avg_sensationalism else None,
            'unknown_sources': [s.name for s in unknown_sources],
            'coverage_notes': coverage_notes,
            'has_sufficient_coverage': total_known >= 2  # Need at least 2 sources
        }

    def _empty_distribution(self) -> Dict:
        """Return empty distribution when no articles or sources"""
        return {
            'distribution': {'left': 0, 'center': 0, 'right': 0},
            'imbalance_score': 0,
            'source_count': 0,
            'total_articles': 0,
            'sources_by_leaning': {'left': [], 'center': [], 'right': []},
            'sensationalism_avg': None,
            'unknown_sources': [],
            'coverage_notes': 'No coverage data available',
            'has_sufficient_coverage': False
        }

    def _generate_coverage_notes(
        self,
        left_count: int,
        center_count: int,
        right_count: int,
        unknown_count: int
    ) -> str:
        """
        Generate human-readable coverage notes.

        Examples:
        - "Coverage from 5 sources across perspectives"
        - "Primarily covered by center outlets (BBC, FT, Reuters)"
        - "Covered by left-leaning outlets (Guardian, Atlantic)"
        """
        total = left_count + center_count + right_count

        if total == 0:
            return "No coverage data available"

        if total == 1:
            if left_count == 1:
                return "Covered by 1 left-leaning outlet"
            elif right_count == 1:
                return "Covered by 1 right-leaning outlet"
            else:
                return "Covered by 1 center outlet"

        # Determine primary perspective
        if left_count > center_count + right_count:
            primary = "left-leaning"
        elif right_count > center_count + left_count:
            primary = "right-leaning"
        elif center_count > left_count + right_count:
            primary = "center"
        else:
            return f"Coverage from {total} sources across perspectives"

        return f"Primarily covered by {primary} outlets ({left_count}L, {center_count}C, {right_count}R)"

    def get_sensationalism_label(self, score: Optional[float]) -> str:
        """
        Convert sensationalism score to human-readable label.

        Args:
            score: 0-1 score (higher = more sensational)

        Returns:
            str: 'low', 'medium', or 'high'
        """
        if score is None:
            return 'unknown'
        elif score < 0.3:
            return 'low'
        elif score < 0.7:
            return 'medium'
        else:
            return 'high'

    def analyze_coverage_gap(self, gap_side: str) -> Optional[str]:
        """
        Use LLM to explain why one perspective might not be covering this story.

        Args:
            gap_side: 'left' or 'right' - which side has low coverage

        Returns:
            str: One-sentence hypothesis for why this gap exists, or None if analysis fails
        """
        try:
            api_key, provider = get_system_api_key()
            if not api_key:
                logger.warning("No LLM API key available for blindspot analysis")
                return None

            # Get article summaries for context
            article_summaries = []
            for article in self.articles[:5]:  # Limit to 5 articles for context
                source_name = article.source.name if article.source else 'Unknown'
                summary = article.summary[:200] if article.summary else article.title
                article_summaries.append(f"[{source_name}] {summary}")

            articles_text = '\n'.join(article_summaries)

            # Calculate current distribution
            distribution_data = self.calculate_distribution()
            dist = distribution_data['distribution']
            left_pct = round(dist['left'] * 100)
            center_pct = round(dist['center'] * 100)
            right_pct = round(dist['right'] * 100)

            prompt = f"""Analyze this news story's coverage gap and provide a neutral, one-sentence hypothesis for why {gap_side}-leaning outlets have minimal coverage.

STORY: {self.topic.title}
SUMMARY: {self.topic.description or 'N/A'}

COVERAGE DISTRIBUTION:
- Left-leaning: {left_pct}%
- Center: {center_pct}%
- Right-leaning: {right_pct}%

SAMPLE ARTICLES:
{articles_text}

Provide a brief, neutral hypothesis (max 30 words) explaining why {gap_side}-leaning outlets might not be covering this story prominently. Consider:
- Editorial priorities (what stories each side typically emphasizes)
- Narrative fit (does this story challenge or support their usual frames?)
- Audience interests
- Timing or news cycle factors

Be specific and neutral. Don't judge - just explain the likely editorial reasoning.

Respond with ONLY JSON:
{{
  "hypothesis": "One sentence explaining the coverage gap (max 30 words)"
}}"""

            # Call LLM
            if provider == 'openai':
                import openai
                client = openai.OpenAI(api_key=api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a media analyst explaining coverage patterns. Be neutral and specific. Respond only in valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=150,
                    temperature=0.3
                )
                content = response.choices[0].message.content
            else:  # anthropic
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                message = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=150,
                    temperature=0.3,
                    system="You are a media analyst explaining coverage patterns. Be neutral and specific. Respond only in valid JSON.",
                    messages=[{"role": "user", "content": prompt}]
                )
                content = None
                for block in message.content:
                    if hasattr(block, 'text') and block.text:
                        content = block.text
                        break
                if not content:
                    logger.warning("Anthropic response had no text content blocks")
                    return None

            # Extract JSON
            if not content:
                return None
            data = extract_json(content)
            hypothesis = data.get('hypothesis', '')

            if hypothesis:
                logger.info(f"Generated blindspot explanation for {gap_side}: {hypothesis[:50]}...")
                return hypothesis
            else:
                return None

        except Exception as e:
            logger.warning(f"Failed to generate blindspot explanation: {e}")
            return None

    @staticmethod
    def format_for_display(distribution_data: Dict) -> Dict:
        """
        Format distribution data for UI display.

        Adds:
        - Color codes for visualization
        - Percentage strings
        - Readable labels

        Args:
            distribution_data: Raw distribution dict from calculate_distribution()

        Returns:
            dict: Display-ready data with colors, labels, percentages
        """
        dist = distribution_data['distribution']

        return {
            'raw': distribution_data,
            'display': {
                'left': {
                    'pct': round(dist['left'] * 100),
                    'pct_str': f"{round(dist['left'] * 100)}%",
                    'color': '#0066CC',  # Blue
                    'sources': distribution_data['sources_by_leaning']['left']
                },
                'center': {
                    'pct': round(dist['center'] * 100),
                    'pct_str': f"{round(dist['center'] * 100)}%",
                    'color': '#9933CC',  # Purple
                    'sources': distribution_data['sources_by_leaning']['center']
                },
                'right': {
                    'pct': round(dist['right'] * 100),
                    'pct_str': f"{round(dist['right'] * 100)}%",
                    'color': '#CC0000',  # Red
                    'sources': distribution_data['sources_by_leaning']['right']
                },
                'imbalance_label': (
                    'Balanced' if distribution_data['imbalance_score'] < 0.3 else
                    'Somewhat unbalanced' if distribution_data['imbalance_score'] < 0.7 else
                    'Heavily weighted'
                ),
                'notes': distribution_data['coverage_notes']
            }
        }


def analyze_topic_coverage(trending_topic: TrendingTopic) -> Dict:
    """
    Convenience function to analyze coverage for a topic.

    Args:
        trending_topic: TrendingTopic instance

    Returns:
        dict: Coverage analysis data
    """
    analyzer = CoverageAnalyzer(trending_topic)
    return analyzer.calculate_distribution()


def analyze_and_format(trending_topic: TrendingTopic) -> Dict:
    """
    Analyze and format for display in one call.

    Args:
        trending_topic: TrendingTopic instance

    Returns:
        dict: Display-ready coverage data
    """
    analyzer = CoverageAnalyzer(trending_topic)
    raw_data = analyzer.calculate_distribution()
    return CoverageAnalyzer.format_for_display(raw_data)
