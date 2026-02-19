"""
Topic Signals Service

Detects trending topics from quality sources (podcasts, premium publications)
and uses them to boost article relevance scoring.
"""

import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive
from typing import List, Dict, Set

from app import db
from app.models import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

PREMIUM_SOURCES = [
    'The Economist', 'Financial Times', 'The New Yorker', 'Foreign Affairs',
    'UnHerd', 'The Atlantic', 'The News Agents', 'The Rest Is Politics',
    'Triggernometry', 'All-In Podcast', 'The Tim Ferriss Show',
    'Diary of a CEO', 'Modern Wisdom'
]

STOP_WORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
    'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as',
    'into', 'through', 'during', 'before', 'after', 'above', 'below',
    'and', 'but', 'or', 'nor', 'so', 'yet', 'both', 'either', 'neither',
    'not', 'only', 'own', 'same', 'than', 'too', 'very', 'just', 'also',
    'now', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each',
    'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
    'this', 'that', 'these', 'those', 'what', 'which', 'who', 'whom',
    'new', 'says', 'said', 'year', 'years', 'time', 'way', 'day', 'days',
    'first', 'last', 'long', 'great', 'little', 'own', 'old', 'right',
    'big', 'high', 'different', 'small', 'large', 'next', 'early', 'young',
    'important', 'few', 'public', 'bad', 'same', 'able', 'news', 'world',
    'going', 'come', 'make', 'made', 'take', 'get', 'got', 'back', 'still',
    'even', 'well', 'much', 'want', 'give', 'use', 'find', 'tell', 'ask',
    'work', 'seem', 'feel', 'try', 'leave', 'call', 'keep', 'let', 'begin',
    'show', 'hear', 'play', 'run', 'move', 'like', 'live', 'believe', 'hold',
    'bring', 'happen', 'write', 'provide', 'sit', 'stand', 'lose', 'pay',
    'meet', 'include', 'continue', 'set', 'learn', 'change', 'lead', 'understand',
    'watch', 'follow', 'stop', 'create', 'speak', 'read', 'allow', 'add',
    'spend', 'grow', 'open', 'walk', 'win', 'offer', 'remember', 'love',
    'consider', 'appear', 'buy', 'wait', 'serve', 'die', 'send', 'expect',
    'build', 'stay', 'fall', 'cut', 'reach', 'kill', 'remain', 'people',
    'latest', 'breaking', 'today', 'tomorrow', 'week', 'month', 'live',
    'video', 'watch', 'podcast', 'episode', 'show', 'full', 'best', 'top'
}


def extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from text."""
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    keywords = [w for w in words if w not in STOP_WORDS and len(w) >= 4]
    return keywords


def get_trending_topics_from_premium_sources(hours: int = 48) -> Dict[str, int]:
    """
    Analyze recent articles from premium sources to find trending topics.
    Returns dict of topic keywords with their frequency count.
    """
    cutoff = utcnow_naive() - timedelta(hours=hours)
    
    premium_source_ids = db.session.query(NewsSource.id).filter(
        NewsSource.name.in_(PREMIUM_SOURCES),
        NewsSource.is_active == True
    ).all()
    premium_ids = [s[0] for s in premium_source_ids]
    
    if not premium_ids:
        return {}
    
    articles = NewsArticle.query.filter(
        NewsArticle.source_id.in_(premium_ids),
        NewsArticle.fetched_at >= cutoff
    ).all()
    
    keyword_counts = Counter()
    for article in articles:
        title_keywords = extract_keywords(article.title)
        for kw in title_keywords:
            keyword_counts[kw] += 2
        
        if article.summary:
            summary_keywords = extract_keywords(article.summary)
            for kw in summary_keywords:
                keyword_counts[kw] += 1
    
    trending = {kw: count for kw, count in keyword_counts.most_common(50) if count >= 3}
    
    return trending


def calculate_topic_signal_score(title: str, summary: str = None, trending: Dict[str, int] = None) -> float:
    """
    Calculate how well an article aligns with trending topics from premium sources.
    Returns 0-1 score where 1 = high alignment.
    
    Args:
        title: Article title
        summary: Article summary (optional)
        trending: Pre-fetched trending keywords dict (optional, for batch processing)
    """
    if not title:
        return 0.3
    
    if trending is None:
        trending = get_trending_topics_from_premium_sources(48)
    
    if not trending:
        return 0.5
    
    article_keywords = set(extract_keywords(title))
    if summary:
        article_keywords.update(extract_keywords(summary))
    
    if not article_keywords:
        return 0.3
    
    max_score = max(trending.values()) if trending else 1
    
    signal_score = 0
    matches = 0
    for kw in article_keywords:
        if kw in trending:
            signal_score += trending[kw] / max_score
            matches += 1
    
    if matches == 0:
        return 0.3
    
    normalized = min((signal_score / max(len(article_keywords), 1)) * 2, 1.0)
    
    return normalized


def get_hot_topics_summary() -> List[Dict]:
    """
    Get a summary of current hot topics from premium sources.
    Useful for admin dashboard display.
    """
    trending = get_trending_topics_from_premium_sources(hours=24)
    
    topics = []
    for keyword, count in sorted(trending.items(), key=lambda x: -x[1])[:20]:
        topics.append({
            'keyword': keyword,
            'mentions': count,
            'sources': 'premium'
        })
    
    return topics
