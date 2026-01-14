"""
Social Media Insights Generator

Leverages existing discussion data (consensus, votes, statements) to create
engaging social media posts that stay true to our mission of revealing
consensus, finding bridge ideas, and understanding nuance.

DRY Principle: Reuses existing models, properties, and data structures.
"""

import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from functools import lru_cache
import time
import threading

logger = logging.getLogger(__name__)

# =============================================================================
# DISPLAY THRESHOLDS
# =============================================================================
# Hide low counts to avoid cold start perception problem
# Only show participant/vote counts when above these thresholds

PARTICIPANT_DISPLAY_THRESHOLD = 20  # Show "X people" only if >= 20
VOTE_DISPLAY_THRESHOLD = 20  # Show vote counts only if >= 20
CONSENSUS_DISPLAY_THRESHOLD = 50  # Show consensus stats only if >= 50 participants


# =============================================================================
# INSIGHTS CACHE (Thread-Safe)
# =============================================================================
# TTL-based cache for discussion insights to avoid repeated DB queries
# Cache expires after 5 minutes (insights don't change frequently)
# Uses threading lock for thread-safety in multi-worker environments

_insights_cache: Dict[int, Tuple[Dict, float]] = {}
_cache_lock = threading.Lock()
INSIGHTS_CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_cached_insights(discussion_id: int) -> Optional[Dict]:
    """Get insights from cache if not expired. Thread-safe."""
    with _cache_lock:
        if discussion_id in _insights_cache:
            insights, cached_at = _insights_cache[discussion_id]
            if time.time() - cached_at < INSIGHTS_CACHE_TTL_SECONDS:
                logger.debug(f"Cache hit for discussion {discussion_id} insights")
                # Return a copy to prevent mutation issues
                return insights.copy()
            else:
                # Expired - remove from cache
                del _insights_cache[discussion_id]
    return None


def _cache_insights(discussion_id: int, insights: Dict) -> None:
    """Store insights in cache with timestamp. Thread-safe."""
    with _cache_lock:
        # Store a copy to prevent external mutation
        _insights_cache[discussion_id] = (insights.copy(), time.time())

        # Cleanup: Remove old entries if cache grows too large (>100 entries)
        if len(_insights_cache) > 100:
            now = time.time()
            expired_ids = [
                did for did, (_, cached_at) in _insights_cache.items()
                if now - cached_at >= INSIGHTS_CACHE_TTL_SECONDS
            ]
            for did in expired_ids:
                del _insights_cache[did]


def clear_insights_cache(discussion_id: Optional[int] = None) -> None:
    """Clear insights cache. If discussion_id provided, only clear that entry. Thread-safe."""
    global _insights_cache
    with _cache_lock:
        if discussion_id is not None:
            _insights_cache.pop(discussion_id, None)
        else:
            _insights_cache = {}


def get_discussion_insights(discussion, use_cache: bool = True) -> Dict:
    """
    Extract insights from a discussion using existing data structures.

    Reuses:
    - ConsensusAnalysis.cluster_data (consensus/bridge/divisive statements)
    - Statement.agreement_rate, controversy_score properties
    - StatementVote counts
    - Discussion.participant_count

    Args:
        discussion: Discussion model instance
        use_cache: If True, check cache before querying (default True)

    Returns dict with insights ready for social media posts.
    """
    # Check cache first
    if use_cache:
        cached = _get_cached_insights(discussion.id)
        if cached is not None:
            return cached

    from app.models import ConsensusAnalysis, Statement, StatementVote

    insights = {
        'has_consensus_data': False,
        'participant_count': discussion.participant_count or 0,
        'total_statements': 0,
        'total_votes': 0,
        'consensus_statements': [],
        'bridge_statements': [],
        'divisive_statements': [],
        'surprising_findings': [],
        'hook_candidates': []
    }
    
    # Get latest consensus analysis (reuse existing structure)
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion.id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        # Fallback: Use statement-level data if no consensus analysis
        statements = Statement.query.filter_by(
            discussion_id=discussion.id,
            mod_status=1,
            is_deleted=False
        ).all()
        
        insights['total_statements'] = len(statements)
        insights['total_votes'] = sum(s.total_votes for s in statements)
        
        # Find high-agreement statements (potential consensus)
        for stmt in statements:
            if stmt.total_votes >= 10 and stmt.agreement_rate >= 0.7:
                insights['consensus_statements'].append({
                    'content': stmt.content,
                    'agreement_rate': stmt.agreement_rate,
                    'total_votes': stmt.total_votes
                })
        
        # Find controversial statements (divisive)
        for stmt in statements:
            if stmt.total_votes >= 10 and stmt.controversy_score >= 0.8:
                insights['divisive_statements'].append({
                    'content': stmt.content,
                    'agreement_rate': stmt.agreement_rate,
                    'controversy_score': stmt.controversy_score,
                    'total_votes': stmt.total_votes
                })

        # Cache before returning
        _cache_insights(discussion.id, insights)
        return insights
    
    # Use consensus analysis data (reuse existing JSON structure)
    insights['has_consensus_data'] = True
    insights['participant_count'] = analysis.participants_count or discussion.participant_count or 0
    insights['total_statements'] = analysis.statements_count or 0
    
    cluster_data = analysis.cluster_data or {}
    
    # Extract consensus statements (reuse existing structure)
    consensus_data = cluster_data.get('consensus_statements', [])
    consensus_stmt_ids = [s['statement_id'] for s in consensus_data]
    consensus_stmts = Statement.query.filter(Statement.id.in_(consensus_stmt_ids)).all() if consensus_stmt_ids else []
    
    for stmt in consensus_stmts:
        stmt_data = next((s for s in consensus_data if s['statement_id'] == stmt.id), {})
        insights['consensus_statements'].append({
            'content': stmt.content,
            'agreement_rate': stmt_data.get('agreement_rate', stmt.agreement_rate),
            'total_votes': stmt.total_votes
        })
    
    # Extract bridge statements (reuse existing structure)
    bridge_data = cluster_data.get('bridge_statements', [])
    bridge_stmt_ids = [s['statement_id'] for s in bridge_data]
    bridge_stmts = Statement.query.filter(Statement.id.in_(bridge_stmt_ids)).all() if bridge_stmt_ids else []
    
    for stmt in bridge_stmts:
        stmt_data = next((s for s in bridge_data if s['statement_id'] == stmt.id), {})
        insights['bridge_statements'].append({
            'content': stmt.content,
            'bridge_score': stmt_data.get('bridge_score', 0),
            'agreement_rate': stmt_data.get('agreement_rate', stmt.agreement_rate),
            'total_votes': stmt.total_votes
        })
    
    # Extract divisive statements (reuse existing structure)
    divisive_data = cluster_data.get('divisive_statements', [])
    divisive_stmt_ids = [s['statement_id'] for s in divisive_data]
    divisive_stmts = Statement.query.filter(Statement.id.in_(divisive_stmt_ids)).all() if divisive_stmt_ids else []
    
    for stmt in divisive_stmts:
        stmt_data = next((s for s in divisive_data if s['statement_id'] == stmt.id), {})
        insights['divisive_statements'].append({
            'content': stmt.content,
            'agreement_rate': stmt_data.get('agreement_rate', stmt.agreement_rate),
            'total_votes': stmt.total_votes
        })
    
    # Calculate total votes (reuse existing relationship)
    insights['total_votes'] = StatementVote.query.filter_by(
        discussion_id=discussion.id
    ).count()
    
    # Generate surprising findings (leverages existing data)
    insights['surprising_findings'] = _generate_surprising_findings(insights)

    # Generate hook candidates (leverages existing data)
    insights['hook_candidates'] = _generate_hook_candidates(insights, discussion)

    # Cache before returning
    _cache_insights(discussion.id, insights)
    return insights


def _generate_surprising_findings(insights: Dict) -> List[str]:
    """
    Generate surprising findings from consensus data.
    Stays true to mission: reveal consensus, find bridges, show nuance.
    """
    findings = []
    
    # Finding 1: Consensus exists where people think there's division
    if insights['consensus_statements']:
        top_consensus = max(insights['consensus_statements'], 
                          key=lambda x: x['agreement_rate'])
        if top_consensus['agreement_rate'] >= 0.8:
            findings.append(
                f"{int(top_consensus['agreement_rate'] * 100)}% agree: "
                f"{top_consensus['content'][:80]}..."
            )
    
    # Finding 2: Bridge statements (common ground)
    if insights['bridge_statements']:
        top_bridge = max(insights['bridge_statements'],
                        key=lambda x: x.get('bridge_score', 0))
        findings.append(
            f"Common ground found: {top_bridge['content'][:80]}..."
        )
    
    # Finding 3: Participation level (only show if above threshold)
    if insights['participant_count'] >= CONSENSUS_DISPLAY_THRESHOLD:
        findings.append(
            f"{insights['participant_count']}+ people have shared their perspective"
        )
    
    # Finding 4: Nuance revealed
    if insights['divisive_statements'] and insights['consensus_statements']:
        findings.append(
            "Both consensus and division revealed—nuance matters"
        )
    
    return findings


def _generate_hook_candidates(insights: Dict, discussion) -> List[str]:
    """
    Generate engaging hooks from discussion data.
    Mission-aligned: surprising stats, consensus, bridges, nuance.
    """
    hooks = []

    # Hook 1: Surprising consensus
    if insights['consensus_statements']:
        top_consensus = max(insights['consensus_statements'],
                          key=lambda x: x['agreement_rate'])
        if top_consensus['agreement_rate'] >= 0.75:
            hooks.append(
                f"{int(top_consensus['agreement_rate'] * 100)}% of people agree on this—"
                f"but you'd never know from the headlines."
            )

    # Hook 2: Bridge statement (common ground)
    if insights['bridge_statements']:
        top_bridge = insights['bridge_statements'][0]
        hooks.append(
            f"Here's what unites people across different views: "
            f"{top_bridge['content'][:60]}..."
        )

    # Hook 3: Participation milestone (only show if above threshold)
    if insights['participant_count'] >= 100:
        hooks.append(
            f"{insights['participant_count']} people shared their perspective. "
            f"Here's what we learned:"
        )
    elif insights['participant_count'] >= CONSENSUS_DISPLAY_THRESHOLD:
        hooks.append(
            f"{insights['participant_count']}+ perspectives revealed something surprising:"
        )

    # Hook 4: Nuance revealed
    if insights['consensus_statements'] and insights['divisive_statements']:
        hooks.append(
            f"The debate isn't as simple as it seems. "
            f"Here's where people agree—and where they don't:"
        )

    # Hook 5: Question format (if title is a question)
    if '?' in discussion.title or discussion.title.lower().startswith(('should', 'can', 'will', 'do')):
        hooks.append(
            f"{discussion.title}"
        )

    # Fallback: Generic but mission-aligned
    if not hooks:
        hooks.append(
            f"New debate: {discussion.title[:80]}..."
        )

    return hooks


# =============================================================================
# A/B TESTING FOR HOOK STYLES
# =============================================================================
# Different hook variants to test for engagement optimization

HOOK_VARIANTS = {
    'consensus_surprise': {
        'name': 'Consensus Surprise',
        'description': 'Lead with surprising consensus percentage',
        'template': "{pct}% of people agree on this—but you'd never know from the headlines.",
        'requires': 'consensus',
        'weight': 1.0,
    },
    'bridge_unity': {
        'name': 'Bridge Unity',
        'description': 'Lead with common ground statement',
        'template': "Here's what unites people across different views: {content}...",
        'requires': 'bridge',
        'weight': 1.0,
    },
    'participation_social_proof': {
        'name': 'Participation Social Proof',
        'description': 'Lead with participation numbers',
        'template': "{count} people shared their perspective. Here's what we learned:",
        'requires': 'participation',
        'weight': 1.0,
    },
    'nuance_reveal': {
        'name': 'Nuance Reveal',
        'description': 'Emphasize complexity and nuance',
        'template': "The debate isn't as simple as it seems. Here's where people agree—and where they don't:",
        'requires': 'nuance',
        'weight': 1.0,
    },
    'question_direct': {
        'name': 'Question Direct',
        'description': 'Use the discussion title directly',
        'template': "{title}",
        'requires': 'question_title',
        'weight': 1.0,
    },
    'curiosity_gap': {
        'name': 'Curiosity Gap',
        'description': 'Create curiosity about what people think',
        'template': "We asked {count} people about this. The results might surprise you:",
        'requires': 'participation',
        'weight': 1.0,
    },
    'contrarian': {
        'name': 'Contrarian',
        'description': 'Challenge conventional wisdom',
        'template': "Everyone assumes we're divided on this. But {pct}% actually agree.",
        'requires': 'consensus',
        'weight': 1.0,
    },
}


def _get_available_variants(insights: Dict, discussion) -> List[Tuple[str, str]]:
    """
    Get available hook variants based on available data.

    Returns list of (variant_id, generated_hook) tuples.
    """
    available = []

    # Check what data we have
    has_consensus = bool(insights.get('consensus_statements'))
    has_bridge = bool(insights.get('bridge_statements'))
    has_participation = (insights.get('participant_count', 0) >= CONSENSUS_DISPLAY_THRESHOLD)
    has_nuance = has_consensus and bool(insights.get('divisive_statements'))
    is_question = '?' in discussion.title or discussion.title.lower().startswith(
        ('should', 'can', 'will', 'do', 'is', 'are', 'would')
    )

    # Generate hooks for each available variant
    if has_consensus:
        top_consensus = max(insights['consensus_statements'], key=lambda x: x['agreement_rate'])
        pct = int(top_consensus['agreement_rate'] * 100)

        if pct >= 70:
            available.append((
                'consensus_surprise',
                f"{pct}% of people agree on this—but you'd never know from the headlines."
            ))
            available.append((
                'contrarian',
                f"Everyone assumes we're divided on this. But {pct}% actually agree."
            ))

    if has_bridge:
        top_bridge = insights['bridge_statements'][0]
        content = top_bridge['content'][:60]
        available.append((
            'bridge_unity',
            f"Here's what unites people across different views: {content}..."
        ))

    if has_participation:
        count = insights['participant_count']
        available.append((
            'participation_social_proof',
            f"{count} people shared their perspective. Here's what we learned:"
        ))
        available.append((
            'curiosity_gap',
            f"We asked {count} people about this. The results might surprise you:"
        ))

    if has_nuance:
        available.append((
            'nuance_reveal',
            "The debate isn't as simple as it seems. Here's where people agree—and where they don't:"
        ))

    if is_question:
        available.append((
            'question_direct',
            discussion.title
        ))

    return available


def select_hook_with_ab_test(
    insights: Dict,
    discussion,
    force_variant: Optional[str] = None
) -> Tuple[str, str]:
    """
    Select a hook using A/B testing logic.

    Uses weighted random selection, with weights adjusted based on
    past performance (if engagement data is available).

    Args:
        insights: Discussion insights dict
        discussion: Discussion model instance
        force_variant: Force a specific variant (for testing)

    Returns:
        Tuple of (variant_id, hook_text)
    """
    import random

    available = _get_available_variants(insights, discussion)

    if not available:
        # Fallback
        return ('default', f"New debate: {discussion.title[:80]}...")

    # If variant forced, use it if available
    if force_variant:
        for variant_id, hook in available:
            if variant_id == force_variant:
                return (variant_id, hook)

    # Try to get performance data to weight selection
    try:
        from app.trending.engagement_tracker import get_best_performing_variant
        best_variant = get_best_performing_variant(content_type='discussion', days=30)

        if best_variant:
            # Boost weight of best performing variant
            for variant_id, hook in available:
                if variant_id == best_variant:
                    # 50% chance to use the best variant
                    if random.random() < 0.5:
                        logger.info(f"A/B test: Selected best performer '{variant_id}'")
                        return (variant_id, hook)
    except Exception as e:
        logger.debug(f"Could not get performance data for A/B test: {e}")

    # Random selection from available variants
    selected = random.choice(available)
    logger.info(f"A/B test: Selected variant '{selected[0]}'")
    return selected


def generate_data_driven_post(
    discussion,
    platform: str = 'x',
    use_insights: bool = True,
    use_ab_test: bool = True,
    return_variant: bool = False
):
    """
    Generate a social media post using existing discussion data.

    Optimized for conversion: includes clear CTAs and value propositions.
    Supports A/B testing of different hook styles.

    Leverages:
    - ConsensusAnalysis data (if available)
    - Statement agreement rates
    - Participant counts
    - Bridge/consensus/divisive statements

    Stays true to mission: reveal consensus, find bridges, show nuance.

    Args:
        discussion: Discussion model instance
        platform: 'x' or 'bluesky'
        use_insights: Whether to use insights data (default True)
        use_ab_test: Whether to use A/B testing for hook selection (default True)
        return_variant: If True, returns (post_text, variant_id) tuple

    Returns:
        str: Post text (if return_variant=False)
        tuple: (post_text, variant_id) if return_variant=True
    """
    from app.trending.social_poster import get_topic_hashtags, generate_post_text

    variant_id = 'default'

    # Get insights from existing data
    if use_insights:
        insights = get_discussion_insights(discussion)

        # Select hook using A/B testing or use first candidate
        if use_ab_test:
            variant_id, hook = select_hook_with_ab_test(insights, discussion)
        elif insights['hook_candidates']:
            hook = insights['hook_candidates'][0]
            variant_id = 'first_candidate'
        else:
            hook = f"New debate: {discussion.title[:80]}..."

        # Add surprising finding if available (value)
        finding = ""
        if insights['surprising_findings']:
            finding = f"\n\n💡 {insights['surprising_findings'][0]}"

        # Add participation count if significant (social proof)
        # Skip if hook already mentions participation or below threshold
        participation = ""
        if insights['participant_count'] >= PARTICIPANT_DISPLAY_THRESHOLD and 'people' not in hook.lower():
            participation = f"\n\n👥 {insights['participant_count']}+ people have shared their perspective"

        # CTA optimized for conversion (action-oriented)
        cta = "\n\nWhere do YOU stand? Join the debate:"

        # Build post with UTM parameters for tracking
        base_url = f"https://societyspeaks.io/discussions/{discussion.id}/{discussion.slug}"
        discussion_url = _add_utm_params(base_url, platform, 'social', 'discussion')
        hashtags = get_topic_hashtags(discussion.topic or 'Society')

        max_length = 280 if platform == 'x' else 300

        post = f"{hook}{finding}{participation}{cta}\n\n{discussion_url}\n\n{' '.join(hashtags[:2])}"

        # Truncate if needed (prioritize hook, CTA, and URL)
        if len(post) > max_length:
            # Smart truncation: keep hook, CTA, URL; trim finding/participation
            overhead = len(f"{hook}{cta}\n\n{discussion_url}\n\n{' '.join(hashtags[:2])}")
            remaining = max_length - overhead - 10
            if remaining > 20 and insights['surprising_findings']:
                finding = f"\n\n💡 {insights['surprising_findings'][0][:remaining]}..."
                post = f"{hook}{finding}{cta}\n\n{discussion_url}\n\n{' '.join(hashtags[:2])}"
            else:
                post = f"{hook}{cta}\n\n{discussion_url}\n\n{' '.join(hashtags[:2])}"

        final_post = post[:max_length]

        if return_variant:
            return (final_post, variant_id)
        return final_post

    # Fallback to existing function
    fallback_post = generate_post_text(
        title=discussion.title,
        topic=discussion.topic or 'Society',
        discussion_url=f"https://societyspeaks.io/discussions/{discussion.id}/{discussion.slug}",
        platform=platform
    )

    if return_variant:
        return (fallback_post, 'fallback')
    return fallback_post


def _add_utm_params(url: str, source: str, medium: str, campaign: str) -> str:
    """
    Add UTM parameters for conversion tracking.
    """
    from urllib.parse import urlencode, urlparse, urlunparse
    
    parsed = urlparse(url)
    params = {
        'utm_source': source,  # 'twitter', 'bluesky'
        'utm_medium': medium,  # 'social'
        'utm_campaign': campaign  # 'discussion', 'daily_question', 'daily_brief'
    }
    
    query = urlencode(params)
    new_url = urlunparse(parsed._replace(query=query))
    
    return new_url


def get_consensus_summary_for_post(discussion) -> Optional[str]:
    """
    Get a short summary of consensus findings for social posts.
    Reuses ConsensusAnalysis data.
    """
    insights = get_discussion_insights(discussion)
    
    if not insights['has_consensus_data']:
        return None
    
    summary_parts = []
    
    # Consensus count
    if insights['consensus_statements']:
        summary_parts.append(
            f"{len(insights['consensus_statements'])} areas of consensus found"
        )
    
    # Bridge count
    if insights['bridge_statements']:
        summary_parts.append(
            f"{len(insights['bridge_statements'])} bridge statements"
        )
    
    # Participation
    if insights['participant_count'] >= 20:
        summary_parts.append(
            f"{insights['participant_count']} participants"
        )
    
    if summary_parts:
        return " · ".join(summary_parts)
    
    return None


def get_top_consensus_statement(discussion, max_length: int = 100) -> Optional[str]:
    """
    Get the top consensus statement for use in posts.
    Reuses Statement model and ConsensusAnalysis data.
    """
    insights = get_discussion_insights(discussion)
    
    if not insights['consensus_statements']:
        return None
    
    top = max(insights['consensus_statements'],
             key=lambda x: x['agreement_rate'])
    
    content = top['content']
    if len(content) > max_length:
        content = content[:max_length].rsplit(' ', 1)[0] + "..."
    
    return f"{int(top['agreement_rate'] * 100)}% agree: {content}"


def get_bridge_statement(discussion, max_length: int = 100) -> Optional[str]:
    """
    Get a bridge statement for use in posts.
    Reuses Statement model and ConsensusAnalysis data.
    """
    insights = get_discussion_insights(discussion)
    
    if not insights['bridge_statements']:
        return None
    
    top_bridge = insights['bridge_statements'][0]
    content = top_bridge['content']
    
    if len(content) > max_length:
        content = content[:max_length].rsplit(' ', 1)[0] + "..."
    
    return f"Common ground: {content}"


def generate_weekly_insights_thread() -> List[str]:
    """
    Generate weekly insights thread (value-first content, 80/20 rule).
    
    Part of 80/20 strategy: 80% value, 20% promotion.
    This is value-first content that educates and engages.
    
    Returns list of thread tweets (5 tweets).
    """
    from app.models import Discussion, ConsensusAnalysis, StatementVote
    from datetime import datetime, timedelta
    
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    # Get discussions from last week
    recent_discussions = Discussion.query.filter(
        Discussion.created_at >= week_ago,
        Discussion.has_native_statements == True
    ).all()
    
    # Calculate insights
    total_participants = sum(d.participant_count or 0 for d in recent_discussions)
    total_discussions = len(recent_discussions)
    
    # Get top consensus finding
    top_consensus = None
    top_consensus_rate = 0
    
    for discussion in recent_discussions:
        insights = get_discussion_insights(discussion)
        if insights['consensus_statements']:
            top = max(insights['consensus_statements'], key=lambda x: x['agreement_rate'])
            if top['agreement_rate'] > top_consensus_rate:
                top_consensus_rate = top['agreement_rate']
                top_consensus = top['content'][:100]
    
    # Get top bridge
    top_bridge = None
    top_bridge_score = 0
    
    for discussion in recent_discussions:
        insights = get_discussion_insights(discussion)
        if insights['bridge_statements']:
            top = max(insights['bridge_statements'], key=lambda x: x.get('bridge_score', 0))
            if top.get('bridge_score', 0) > top_bridge_score:
                top_bridge_score = top.get('bridge_score', 0)
                top_bridge = top['content'][:100]
    
    # Get top divisive
    top_divisive = None
    top_divisive_controversy = 0
    
    for discussion in recent_discussions:
        insights = get_discussion_insights(discussion)
        if insights['divisive_statements']:
            # Divisive statements have agreement_rate close to 0.5
            for stmt in insights['divisive_statements']:
                controversy = abs(stmt['agreement_rate'] - 0.5)
                if controversy < 0.1 and controversy > top_divisive_controversy:
                    top_divisive_controversy = controversy
                    top_divisive = stmt['content'][:100]
    
    # Build thread
    thread = [
        "1/5 🧵 Weekly Insights: What We Learned This Week",
        "",
        f"From {total_participants} people across {total_discussions} discussions:",
        "",
        "2/5 Top Consensus Finding:",
        f"{top_consensus or 'People found common ground on multiple issues'}",
        "",
        "3/5 Most Surprising Bridge:",
        f"{top_bridge or 'Different groups found ways to unite'}",
        "",
        "4/5 Key Division:",
        f"{top_divisive or 'Some issues remain genuinely divisive'}",
        "",
        "5/5 This is why nuanced debate matters.",
        "",
        "See all discussions: https://societyspeaks.io"
    ]
    
    return thread


def generate_daily_question_post(
    question,
    platform: str = 'x'
) -> str:
    """
    Generate daily question post optimized for engagement.
    
    Best practices (2025):
    - X: 280 chars, URLs count as 23 chars
    - Bluesky: 300 chars, URL in link card embed (not in text)
    - 1-2 hashtags max, never start with hashtag
    
    Goal: Drive responses and subscriptions.
    """
    # Character limits
    URL_CHARS = 23  # X shortens all URLs to 23 chars
    MAX_CHARS = 280 if platform == 'x' else 300
    
    # For Bluesky, URL goes in link card embed, not in text
    # This saves ~23 chars for more content
    include_url_in_text = (platform == 'x')
    
    # Get response stats for social proof
    response_count = question.response_count or 0
    
    # Build components
    # Truncate question text if too long (keep it readable)
    question_text = question.question_text
    max_question_len = 150 if platform == 'x' else 180
    if len(question_text) > max_question_len:
        question_text = question_text[:max_question_len-3].rsplit(' ', 1)[0] + "..."
    
    hook = f"Today's Daily Question:\n\n\"{question_text}\""
    
    # Social proof (only if meaningful count)
    social_proof = ""
    if response_count >= PARTICIPANT_DISPLAY_THRESHOLD:
        social_proof = f"\n\n{response_count} responses"
    
    # Short CTA
    cta = "\n\nWhere do YOU stand?"
    
    # Single hashtag, placed at end
    hashtag = " #DailyQuestion"
    
    if include_url_in_text:
        # X: Include URL in text (counts as 23 chars)
        base_url = f"https://societyspeaks.io/daily/{question.question_date.strftime('%Y-%m-%d')}"
        question_url = _add_utm_params(base_url, platform, 'social', 'daily_question')
        
        # Calculate available space
        available = MAX_CHARS - URL_CHARS - len(hashtag) - 4  # 4 for newlines
        
        # Build post fitting within limit
        core = f"{hook}{social_proof}{cta}"
        if len(core) > available:
            # Truncate hook (question text)
            core = f"{hook}{cta}"
            if len(core) > available:
                excess = len(core) - available + 3
                question_text = question_text[:len(question_text)-excess].rsplit(' ', 1)[0] + "..."
                hook = f"Today's Daily Question:\n\n\"{question_text}\""
                core = f"{hook}{cta}"
        
        post = f"{core}{hashtag}\n\n{question_url}"
    else:
        # Bluesky: No URL in text (goes in embed)
        available = MAX_CHARS - len(hashtag) - 2
        
        core = f"{hook}{social_proof}{cta}"
        if len(core) > available:
            core = f"{hook}{cta}"
            if len(core) > available:
                excess = len(core) - available + 3
                question_text = question_text[:len(question_text)-excess].rsplit(' ', 1)[0] + "..."
                hook = f"Today's Daily Question:\n\n\"{question_text}\""
                core = f"{hook}{cta}"
        
        post = f"{core}{hashtag}"
    
    return post[:MAX_CHARS]


def generate_daily_brief_post(
    brief,
    platform: str = 'x'
) -> str:
    """
    Generate daily brief post optimized for engagement.
    
    Best practices (2025):
    - X: 280 chars, URLs count as 23 chars
    - Bluesky: 300 chars, URL in link card embed (not in text)
    - 1-2 hashtags max, never start with hashtag
    
    Goal: Drive brief views and subscriptions.
    """
    from app.models import BriefItem
    
    # Character limits
    URL_CHARS = 23
    MAX_CHARS = 280 if platform == 'x' else 300
    
    # For Bluesky, URL goes in link card embed
    include_url_in_text = (platform == 'x')
    
    # Get first item for teaser
    item = BriefItem.query.filter_by(
        brief_id=brief.id
    ).order_by(BriefItem.position.asc()).first()
    
    # Build hook with story count
    hook = f"Today's Brief: {brief.item_count} stories that matter"
    
    # One headline teaser
    teaser = ""
    headline = None  # Initialize headline
    if item:
        if item.trending_topic:
            headline = item.trending_topic.title[:80]
        elif item.discussion:
            headline = item.discussion.title[:80]
        if headline:
            teaser = f"\n\n📰 {headline}"
    
    # Short CTA
    cta = "\n\nRead the full brief:"
    
    # Single hashtag
    hashtag = " #DailyBrief"
    
    if include_url_in_text:
        # X: Include URL in text
        base_url = f"https://societyspeaks.io/brief/{brief.date.strftime('%Y-%m-%d')}"
        brief_url = _add_utm_params(base_url, platform, 'social', 'daily_brief')
        
        available = MAX_CHARS - URL_CHARS - len(hashtag) - 4
        
        core = f"{hook}{teaser}{cta}"
        if len(core) > available:
            # Truncate teaser
            if teaser:
                remaining = available - len(f"{hook}{cta}") - 5
                if remaining > 30 and item:
                    headline_text = headline[:remaining-3] + "..." if headline and len(headline) > remaining else (headline or "")
                    teaser = f"\n\n📰 {headline_text}"
                    core = f"{hook}{teaser}{cta}"
                else:
                    core = f"{hook}{cta}"
            else:
                core = f"{hook}{cta}"
        
        if len(core) > available:
            core = core[:available-3] + "..."
        
        post = f"{core}{hashtag}\n\n{brief_url}"
    else:
        # Bluesky: No URL in text
        available = MAX_CHARS - len(hashtag) - 2
        
        core = f"{hook}{teaser}{cta}"
        if len(core) > available:
            if teaser:
                remaining = available - len(f"{hook}{cta}") - 5
                if remaining > 30 and headline:
                    headline_text = headline[:remaining-3] + "..." if len(headline) > remaining else headline
                    teaser = f"\n\n📰 {headline_text}"
                    core = f"{hook}{teaser}{cta}"
                else:
                    core = f"{hook}{cta}"
            else:
                core = f"{hook}{cta}"
        
        if len(core) > available:
            core = core[:available-3] + "..."
        
        post = f"{core}{hashtag}"
    
    return post[:MAX_CHARS]
