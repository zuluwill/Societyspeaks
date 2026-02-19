# app/sources/utils.py
"""
Utility functions for source profile statistics and data aggregation.
"""
from app.lib.time import utcnow_naive
from sqlalchemy import func, distinct
from sqlalchemy.orm import joinedload
from app import db
from app.models import (
    NewsSource, NewsArticle, Discussion, DiscussionSourceArticle,
    StatementVote, ConsensusAnalysis
)


def get_source_discussions(source_id, page=1, per_page=12):
    """
    Get all discussions that have at least one article from this source.

    Uses: DiscussionSourceArticle -> NewsArticle -> NewsSource

    Returns:
        Paginated list of Discussion objects
    """
    return Discussion.query.join(
        DiscussionSourceArticle,
        Discussion.id == DiscussionSourceArticle.discussion_id
    ).join(
        NewsArticle,
        DiscussionSourceArticle.article_id == NewsArticle.id
    ).filter(
        NewsArticle.source_id == source_id,
        Discussion.partner_env != 'test'
    ).distinct().order_by(
        Discussion.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)


def get_source_discussion_ids(source_id):
    """
    Get IDs of all discussions that have articles from this source.

    Returns:
        List of discussion IDs
    """
    results = db.session.query(distinct(DiscussionSourceArticle.discussion_id)).join(
        NewsArticle,
        DiscussionSourceArticle.article_id == NewsArticle.id
    ).filter(
        NewsArticle.source_id == source_id
    ).all()

    return [r[0] for r in results]


def get_source_stats(source_id):
    """
    Calculate engagement statistics for a source.

    Returns dict:
    {
        'discussion_count': int,
        'total_participants': int,  # Sum across all discussions
        'total_votes': int,
        'avg_opinion_groups': float,  # Average from ConsensusAnalysis
        'discussions_with_consensus': int,  # How many have been analyzed
        'article_count': int,  # Number of articles from this source
    }
    """
    # Get discussion IDs for this source
    discussion_ids = get_source_discussion_ids(source_id)

    if not discussion_ids:
        return {
            'discussion_count': 0,
            'total_participants': 0,
            'total_votes': 0,
            'avg_opinion_groups': 0,
            'discussions_with_consensus': 0,
            'article_count': NewsArticle.query.filter_by(source_id=source_id).count()
        }

    # Count discussions
    discussion_count = len(discussion_ids)

    # Count unique participants (users who voted on statements in these discussions)
    participant_count = db.session.query(
        func.count(distinct(StatementVote.user_id))
    ).filter(
        StatementVote.discussion_id.in_(discussion_ids),
        StatementVote.user_id.isnot(None)
    ).scalar() or 0

    # Also count anonymous participants by session fingerprint
    anonymous_count = db.session.query(
        func.count(distinct(StatementVote.session_fingerprint))
    ).filter(
        StatementVote.discussion_id.in_(discussion_ids),
        StatementVote.user_id.is_(None),
        StatementVote.session_fingerprint.isnot(None)
    ).scalar() or 0

    total_participants = participant_count + anonymous_count

    # Count total votes
    total_votes = db.session.query(
        func.count(StatementVote.id)
    ).filter(
        StatementVote.discussion_id.in_(discussion_ids)
    ).scalar() or 0

    # Get consensus analysis stats
    consensus_analyses = ConsensusAnalysis.query.filter(
        ConsensusAnalysis.discussion_id.in_(discussion_ids)
    ).all()

    discussions_with_consensus = len(consensus_analyses)
    avg_opinion_groups = 0

    if consensus_analyses:
        total_groups = sum(ca.num_clusters or 0 for ca in consensus_analyses)
        avg_opinion_groups = round(total_groups / len(consensus_analyses), 1)

    # Count articles
    article_count = NewsArticle.query.filter_by(source_id=source_id).count()

    # Calculate engagement score
    # Formula: (discussion_count * total_participants) / days_since_first_discussion
    # This rewards both quantity of discussions AND participants while normalizing for time on platform
    engagement_score = 0
    avg_participants = total_participants / max(1, discussion_count)
    
    if discussion_count > 0:
        # Get the oldest discussion date
        oldest_discussion = Discussion.query.join(
            DiscussionSourceArticle,
            Discussion.id == DiscussionSourceArticle.discussion_id
        ).join(
            NewsArticle,
            DiscussionSourceArticle.article_id == NewsArticle.id
        ).filter(
            NewsArticle.source_id == source_id,
            Discussion.partner_env != 'test'
        ).order_by(Discussion.created_at.asc()).first()
        
        if oldest_discussion:
            days_since_first = max(1, (utcnow_naive() - oldest_discussion.created_at).days)
            # Score = discussions * participants / days (both factors matter independently)
            engagement_score = round((discussion_count * total_participants) / days_since_first, 2)

    return {
        'discussion_count': discussion_count,
        'total_participants': total_participants,
        'total_votes': total_votes,
        'avg_opinion_groups': avg_opinion_groups,
        'discussions_with_consensus': discussions_with_consensus,
        'article_count': article_count,
        'avg_participants': round(avg_participants, 1),
        'engagement_score': engagement_score
    }


def get_all_sources_with_stats(
    category=None,
    country=None,
    leaning=None,
    search=None,
    sort_by='name',
    page=1,
    per_page=24
):
    """
    Get paginated list of sources with discussion counts.

    Args:
        category: Filter by source_category ('podcast', 'newspaper', etc.)
        country: Filter by country
        leaning: Filter by political leaning ('left', 'center', 'right')
        search: Search term for source name
        sort_by: 'name', 'discussions', 'recent'
        page: Page number
        per_page: Items per page

    Returns:
        Tuple of (sources_with_stats, pagination)
    """
    # Build base query with eager loading to prevent N+1 queries
    query = NewsSource.query.options(
        joinedload(NewsSource.claimed_by)
    ).filter(NewsSource.is_active == True)

    # Apply filters
    if category:
        query = query.filter(NewsSource.source_category == category)

    if country:
        query = query.filter(NewsSource.country == country)

    if leaning:
        if leaning == 'left':
            query = query.filter(NewsSource.political_leaning < -0.5)
        elif leaning == 'center':
            query = query.filter(
                NewsSource.political_leaning >= -0.5,
                NewsSource.political_leaning <= 0.5
            )
        elif leaning == 'right':
            query = query.filter(NewsSource.political_leaning > 0.5)

    if search:
        query = query.filter(NewsSource.name.ilike(f'%{search}%'))

    # Subquery for discussion count
    discussion_count_subq = db.session.query(
        NewsArticle.source_id,
        func.count(distinct(DiscussionSourceArticle.discussion_id)).label('discussion_count')
    ).join(
        DiscussionSourceArticle,
        NewsArticle.id == DiscussionSourceArticle.article_id
    ).group_by(
        NewsArticle.source_id
    ).subquery()

    # Join with discussion count
    query = query.outerjoin(
        discussion_count_subq,
        NewsSource.id == discussion_count_subq.c.source_id
    ).add_columns(
        func.coalesce(discussion_count_subq.c.discussion_count, 0).label('discussion_count')
    )

    # Apply sorting
    if sort_by == 'discussions':
        query = query.order_by(func.coalesce(discussion_count_subq.c.discussion_count, 0).desc())
    elif sort_by == 'recent':
        query = query.order_by(NewsSource.updated_at.desc())
    else:  # Default to name
        query = query.order_by(NewsSource.name.asc())

    # Paginate
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    # Transform results
    sources_with_stats = []
    for item in paginated.items:
        if hasattr(item, '__iter__') and len(item) == 2:
            source, disc_count = item
        else:
            source = item
            disc_count = 0

        sources_with_stats.append({
            'source': source,
            'discussion_count': disc_count
        })

    return sources_with_stats, paginated


def get_unique_countries():
    """Get list of unique countries from active sources."""
    results = db.session.query(distinct(NewsSource.country)).filter(
        NewsSource.is_active == True,
        NewsSource.country.isnot(None)
    ).order_by(NewsSource.country).all()

    return [r[0] for r in results if r[0]]


def get_unique_categories():
    """Get list of unique source categories."""
    results = db.session.query(distinct(NewsSource.source_category)).filter(
        NewsSource.is_active == True,
        NewsSource.source_category.isnot(None)
    ).order_by(NewsSource.source_category).all()

    return [r[0] for r in results if r[0]]
