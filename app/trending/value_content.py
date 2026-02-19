"""
Value-First Content Generator (80/20 Rule)

Generates educational, value-first content for social media.
Part of 80/20 strategy: 80% value, 20% promotion.

These posts educate, inform, and engage without directly promoting.
"""

import logging
from typing import List, Optional
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive

logger = logging.getLogger(__name__)


def generate_weekly_insights_post(platform: str = 'x') -> Optional[str]:
    """
    Generate weekly insights post (value-first content).
    
    Part of 80/20 strategy: This is the 80% value content.
    Educates about consensus, bridges, nuance without direct promotion.
    
    Returns single post (for X) or can be expanded to thread.
    """
    from app.models import Discussion, ConsensusAnalysis
    from app.trending.social_insights import get_discussion_insights
    
    week_ago = utcnow_naive() - timedelta(days=7)
    
    # Get discussions from last week
    recent_discussions = Discussion.query.filter(
        Discussion.created_at >= week_ago,
        Discussion.has_native_statements == True,
        Discussion.partner_env != 'test'
    ).limit(10).all()
    
    if not recent_discussions:
        return None
    
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
                top_consensus = top['content'][:80]
    
    # Build post
    max_length = 280 if platform == 'x' else 300
    
    from app.trending.social_insights import PARTICIPANT_DISPLAY_THRESHOLD

    if top_consensus and total_participants >= PARTICIPANT_DISPLAY_THRESHOLD:
        post = f"📊 Weekly Insight:\n\n{total_participants} people across {total_discussions} discussions this week.\n\nTop finding: {int(top_consensus_rate * 100)}% agree that:\n\n\"{top_consensus}...\"\n\nThis is why nuanced debate matters. #CivicEngagement"
    elif top_consensus:
        post = f"📊 Weekly Insight:\n\nTop finding: {int(top_consensus_rate * 100)}% agree that:\n\n\"{top_consensus}...\"\n\nNuanced debate reveals consensus where headlines show division. #CivicEngagement"
    else:
        logger.info(
            f"Skipping weekly insights post: {total_participants} participants, "
            f"no consensus findings — not enough to share"
        )
        return None
    
    return post[:max_length]


def generate_educational_post(platform: str = 'x') -> Optional[str]:
    """
    Generate educational post about consensus, bridges, or nuance.
    
    Value-first content that educates without promoting.
    """
    educational_topics = [
        "Consensus isn't the absence of disagreement—it's finding where people actually agree despite their differences.",
        "Bridge statements unite different opinion groups. They're the ideas that resonate across political divides.",
        "Nuanced debate reveals three things: consensus (where we agree), bridges (common ground), and divisions (genuine fault lines).",
        "Traditional polls ask: 'Do you agree?' Our platform asks: 'What do you think?' The difference reveals nuance.",
        "Most people aren't as divided as headlines suggest. Consensus exists—you just need to look for it."
    ]
    
    import random
    topic = random.choice(educational_topics)
    
    max_length = 280 if platform == 'x' else 300
    
    post = f"💡 {topic}\n\n#CivicEngagement #PublicDebate"
    
    return post[:max_length]
