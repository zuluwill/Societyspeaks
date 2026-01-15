"""
Diversity Monitor

Monitors political balance in discussions and alerts when imbalances occur.
Supports the mission: "Making Disagreement Useful Again"
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List

from app import db
from app.models import Discussion, DiscussionSourceArticle, NewsArticle, NewsSource
from app.trending.constants import (
    DIVERSITY_BALANCED_MIN,
    DIVERSITY_BALANCED_MAX,
    DIVERSITY_IMBALANCED_MIN,
    DIVERSITY_IMBALANCED_MAX,
    DIVERSITY_DEFAULT_DAYS,
    DIVERSITY_DEFAULT_TARGET_DISCUSSIONS,
    DIVERSITY_STATS_LIMIT,
)

logger = logging.getLogger(__name__)


def get_political_leaning_label(value: float) -> str:
    """Convert numeric political leaning to label."""
    if value is None:
        return 'unknown'
    if value <= -1.5:
        return 'Left'
    elif value < -0.5:
        return 'Centre-Left'
    elif value <= 0.5:
        return 'Centre'
    elif value < 1.5:
        return 'Centre-Right'
    else:
        return 'Right'


def get_discussion_diversity_stats(days: int = DIVERSITY_DEFAULT_DAYS, limit: int = DIVERSITY_STATS_LIMIT) -> Dict:
    """
    Calculate diversity statistics for recent discussions.

    Args:
        days: Number of days to look back for discussions
        limit: Maximum number of discussion records to process (prevents slow queries)

    Returns:
        Dict with source counts, discussion counts, and balance metrics
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    source_stats = db.session.query(
        NewsSource.political_leaning,
        db.func.count(db.func.distinct(NewsSource.id)).label('source_count')
    ).filter(
        NewsSource.is_active == True,
        NewsSource.political_leaning.isnot(None)
    ).group_by(NewsSource.political_leaning).all()

    # Use subquery with limit to prevent full table scan on large datasets
    discussion_ids_subquery = db.session.query(
        Discussion.id
    ).filter(
        Discussion.created_at >= cutoff
    ).order_by(
        Discussion.created_at.desc()
    ).limit(limit).subquery()

    discussion_stats = db.session.query(
        NewsSource.political_leaning,
        db.func.count(db.func.distinct(Discussion.id)).label('discussion_count')
    ).join(
        NewsArticle, NewsArticle.source_id == NewsSource.id
    ).join(
        DiscussionSourceArticle, DiscussionSourceArticle.article_id == NewsArticle.id
    ).join(
        Discussion, Discussion.id == DiscussionSourceArticle.discussion_id
    ).filter(
        NewsSource.political_leaning.isnot(None),
        Discussion.id.in_(discussion_ids_subquery)
    ).group_by(NewsSource.political_leaning).all()
    
    source_by_leaning = {}
    for pl, count in source_stats:
        label = get_political_leaning_label(pl)
        source_by_leaning[label] = source_by_leaning.get(label, 0) + count
    
    discussion_by_leaning = {}
    for pl, count in discussion_stats:
        label = get_political_leaning_label(pl)
        discussion_by_leaning[label] = discussion_by_leaning.get(label, 0) + count
    
    total_sources = sum(source_by_leaning.values())
    total_discussions = sum(discussion_by_leaning.values())
    
    left_sources = source_by_leaning.get('Left', 0) + source_by_leaning.get('Centre-Left', 0)
    right_sources = source_by_leaning.get('Right', 0) + source_by_leaning.get('Centre-Right', 0)
    
    left_discussions = discussion_by_leaning.get('Left', 0) + discussion_by_leaning.get('Centre-Left', 0)
    right_discussions = discussion_by_leaning.get('Right', 0) + discussion_by_leaning.get('Centre-Right', 0)
    
    if right_sources == 0:
        source_balance = float('inf') if left_sources > 0 else 1.0
    else:
        source_balance = left_sources / right_sources
    
    if right_discussions == 0:
        discussion_balance = float('inf') if left_discussions > 0 else 1.0
    else:
        discussion_balance = left_discussions / right_discussions
    
    def safe_round(val: float) -> float:
        if val == float('inf') or val != val:
            return 99.99
        return round(val, 2)
    
    return {
        'period_days': days,
        'sources': {
            'by_leaning': source_by_leaning,
            'total': total_sources,
            'left_right_ratio': safe_round(source_balance)
        },
        'discussions': {
            'by_leaning': discussion_by_leaning,
            'total': total_discussions,
            'left_right_ratio': safe_round(discussion_balance)
        },
        'balance_assessment': assess_balance(source_balance, discussion_balance)
    }


def assess_balance(source_ratio: float, discussion_ratio: float) -> Dict:
    """
    Assess whether the platform is balanced.

    A ratio of 1.0 means perfect left-right balance.
    Thresholds are configurable via constants.py:
    - DIVERSITY_BALANCED_MIN/MAX: Warning thresholds
    - DIVERSITY_IMBALANCED_MIN/MAX: Imbalance thresholds
    """
    issues = []
    status = 'balanced'

    if discussion_ratio > DIVERSITY_IMBALANCED_MAX:
        issues.append(f"Discussion ratio heavily favors left-leaning sources ({discussion_ratio:.1f}:1)")
        status = 'imbalanced'
    elif discussion_ratio > DIVERSITY_BALANCED_MAX:
        issues.append(f"Discussion ratio slightly favors left-leaning sources ({discussion_ratio:.1f}:1)")
        status = 'warning'
    elif discussion_ratio < DIVERSITY_IMBALANCED_MIN:
        issues.append(f"Discussion ratio heavily favors right-leaning sources (1:{1/discussion_ratio:.1f})")
        status = 'imbalanced'
    elif discussion_ratio < DIVERSITY_BALANCED_MIN:
        issues.append(f"Discussion ratio slightly favors right-leaning sources (1:{1/discussion_ratio:.1f})")
        status = 'warning'

    if source_ratio > DIVERSITY_IMBALANCED_MAX:
        issues.append(f"Source ratio favors left-leaning sources ({source_ratio:.1f}:1)")
    elif source_ratio < DIVERSITY_IMBALANCED_MIN:
        issues.append(f"Source ratio favors right-leaning sources (1:{1/source_ratio:.1f})")

    return {
        'status': status,
        'issues': issues,
        'recommendation': _get_recommendation(status, discussion_ratio)
    }


def _get_recommendation(status: str, discussion_ratio: float) -> str:
    """Get actionable recommendation based on balance status."""
    if status == 'balanced':
        return "No action needed. Diversity is healthy."
    elif discussion_ratio > DIVERSITY_BALANCED_MAX:
        return "Consider adding more discussions from right-leaning sources (The Telegraph, National Review, The Dispatch, etc.)"
    elif discussion_ratio < DIVERSITY_BALANCED_MIN:
        return "Consider adding more discussions from left-leaning sources (The Guardian, The Atlantic, etc.)"
    return "Monitor closely and adjust content selection criteria."


def get_underrepresented_sources(target_discussions: int = DIVERSITY_DEFAULT_TARGET_DISCUSSIONS) -> List[Dict]:
    """
    Find sources that are underrepresented in discussions.

    Args:
        target_discussions: Minimum expected discussions per source

    Returns:
        List of sources with fewer than target_discussions that have available articles.
    """
    results = db.session.query(
        NewsSource.id,
        NewsSource.name,
        NewsSource.source_category,
        NewsSource.political_leaning,
        db.func.count(db.func.distinct(DiscussionSourceArticle.discussion_id)).label('discussion_count'),
        db.func.count(db.func.distinct(NewsArticle.id)).label('article_count')
    ).outerjoin(
        NewsArticle, NewsArticle.source_id == NewsSource.id
    ).outerjoin(
        DiscussionSourceArticle, DiscussionSourceArticle.article_id == NewsArticle.id
    ).filter(
        NewsSource.is_active == True
    ).group_by(
        NewsSource.id, NewsSource.name, NewsSource.source_category, NewsSource.political_leaning
    ).having(
        db.func.count(db.func.distinct(DiscussionSourceArticle.discussion_id)) < target_discussions
    ).having(
        db.func.count(db.func.distinct(NewsArticle.id)) >= target_discussions
    ).order_by(
        NewsSource.political_leaning.desc().nullslast()
    ).all()
    
    return [
        {
            'id': r.id,
            'name': r.name,
            'category': r.source_category,
            'leaning': get_political_leaning_label(r.political_leaning),
            'discussion_count': r.discussion_count,
            'article_count': r.article_count,
            'gap': target_discussions - r.discussion_count
        }
        for r in results
    ]


def run_diversity_check(days: int = DIVERSITY_DEFAULT_DAYS, target_discussions: int = DIVERSITY_DEFAULT_TARGET_DISCUSSIONS) -> Dict:
    """
    Run a complete diversity check and log results.
    Called by scheduler daily.

    Args:
        days: Number of days to look back for statistics
        target_discussions: Minimum expected discussions per source
    """
    logger.info("Running daily diversity check")

    stats = get_discussion_diversity_stats(days=days)
    underrepresented = get_underrepresented_sources(target_discussions=target_discussions)
    
    status = stats['balance_assessment']['status']
    
    if status == 'balanced':
        logger.info(f"Diversity check PASSED: Left-Right ratio is {stats['discussions']['left_right_ratio']:.2f}:1")
    elif status == 'warning':
        logger.warning(f"Diversity check WARNING: {stats['balance_assessment']['issues']}")
        logger.warning(f"Recommendation: {stats['balance_assessment']['recommendation']}")
    else:
        logger.error(f"Diversity check FAILED: {stats['balance_assessment']['issues']}")
        logger.error(f"Recommendation: {stats['balance_assessment']['recommendation']}")
    
    if underrepresented:
        right_leaning = [s for s in underrepresented if s['leaning'] in ('Right', 'Centre-Right')]
        if right_leaning:
            logger.info(f"Underrepresented right-leaning sources: {[s['name'] for s in right_leaning[:5]]}")
    
    return {
        'stats': stats,
        'underrepresented_sources': underrepresented,
        'checked_at': datetime.utcnow().isoformat()
    }
