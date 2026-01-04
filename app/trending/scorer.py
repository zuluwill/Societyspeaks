"""
Article and Topic Scoring Pipeline

Philosophy: We WANT sensationalist/polarizing topics - these are the debates
people are already having. Our goal is to bring nuance, balance, and 
structured deliberation to hot-button issues.

Uses LLM to score:
- Debate potential (is this generating discussion?)
- Civic relevance (policy, society, public interest)
- Quality (can we generate balanced seed statements?)
- Risk flags (defamation, hate speech - these we avoid)

We SKIP: celebrity gossip, lifestyle fluff, shopping content
We KEEP: polarizing political/social debates that need nuance
"""

import os
import logging
import json
import re
from typing import Dict, List, Optional, Tuple, Any

from app.models import NewsArticle, TrendingTopic

logger = logging.getLogger(__name__)


def extract_json(text: str) -> Any:
    """
    Robustly extract JSON from LLM response.
    Handles markdown code blocks, trailing text, and other artifacts.
    """
    if not text:
        raise ValueError("Empty response from LLM")
    
    text = text.strip()
    
    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if code_block_match:
        text = code_block_match.group(1).strip()
    
    if text.startswith('['):
        bracket_match = re.search(r'(\[[\s\S]*?\])', text)
        if bracket_match:
            text = bracket_match.group(1)
    elif text.startswith('{'):
        brace_count = 0
        end_pos = 0
        for i, char in enumerate(text):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_pos = i + 1
                    break
        if end_pos > 0:
            text = text[:end_pos]
    
    return json.loads(text)


def get_system_api_key() -> Tuple[Optional[str], str]:
    """Get system-level API key for trending topics processing."""
    openai_key = os.environ.get('OPENAI_API_KEY')
    if openai_key:
        return openai_key, 'openai'
    
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    if anthropic_key:
        return anthropic_key, 'anthropic'
    
    return None, ''


def score_sensationalism(headline: str) -> float:
    """
    Score headline for sensationalism (0-1, higher = more clickbait).
    Uses heuristics first, then LLM if available.
    """
    score = 0.0
    
    if headline.isupper():
        score += 0.3
    
    caps_ratio = sum(1 for c in headline if c.isupper()) / max(len(headline), 1)
    if caps_ratio > 0.4:
        score += 0.2
    
    clickbait_phrases = [
        "you won't believe", "shocking", "breaking", "must see",
        "this is why", "here's what", "the truth about",
        "what happened next", "gone wrong", "epic fail",
        "mind-blowing", "insane", "unbelievable"
    ]
    headline_lower = headline.lower()
    for phrase in clickbait_phrases:
        if phrase in headline_lower:
            score += 0.15
    
    if headline.count('!') > 1:
        score += 0.1
    if headline.count('?') > 2:
        score += 0.1
    
    if re.search(r'\d+\s+(things|ways|reasons|facts|secrets)', headline_lower):
        score += 0.1
    
    return min(score, 1.0)


LOW_VALUE_KEYWORDS = [
    'celebrity', 'kardashian', 'royal family', 'gossip', 'dating', 'breakup',
    'divorce', 'wedding', 'red carpet', 'fashion week', 'reality tv', 'bachelor',
    'love island', 'influencer', 'tiktok star', 'instagram', 'viral video',
    'horoscope', 'astrology', 'lottery', 'game show', 'quiz', 'recipe',
    'best deals', 'discount', 'sale', 'shopping', 'gift guide',
    'best vacuums', 'best trimmers', 'best headphones', 'best laptops', 'best phones',
    'tested for', 'buyer guide', 'gift ideas', 'deals of the day', 'review:',
    'premier league', 'championship', 'fa cup', 'champions league', 'europa league',
    'man united', 'liverpool', 'arsenal', 'chelsea', 'man city', 'tottenham',
    'crystal palace', 'leeds draw', 'brentford', 'everton', 'newcastle', 'aston villa',
    'quarter-final', 'semi-final', 'penalty', 'goal scorer', 'hat-trick', 'clean sheet',
    'transfer news', 'transfer window', 'deadline day', 'signing', 'loan deal',
    'pet hair', 'beard trimmer', 'styling versatility', 'kitchen gadget',
    'world darts', 'darts championship', 'snooker', 'golf tournament', 'wimbledon',
    'formula 1', 'f1 grand prix', 'race winner', 'nfl', 'nba', 'mlb', 'nhl',
    'match report', 'post-match', 'player rating', 'team news', 'starting lineup'
]

PRODUCT_REVIEW_PATTERNS = [
    r'the \d+ best', r'\d+ best', r'best .* for', r'top \d+', r'review:',
    r'tested.*for', r'buying guide', r'vs\.?$', r'versus',
]

HIGH_VALUE_KEYWORDS = [
    'policy', 'legislation', 'parliament', 'congress', 'senate', 'government',
    'economy', 'inflation', 'interest rate', 'gdp', 'unemployment', 'trade',
    'climate', 'environment', 'renewable', 'emissions', 'sustainability',
    'healthcare', 'nhs', 'medicare', 'public health', 'pandemic',
    'education', 'university', 'school', 'curriculum', 'student',
    'technology', 'artificial intelligence', 'regulation', 'antitrust',
    'housing', 'infrastructure', 'transport', 'immigration', 'foreign policy',
    'democracy', 'election', 'referendum', 'diplomacy', 'geopolitics'
]


def pre_filter_articles(articles: List[NewsArticle]) -> Tuple[List[NewsArticle], List[NewsArticle]]:
    """
    Pre-filter articles to find debate-worthy topics.
    
    Philosophy: Sensationalism is a SIGNAL that people care about a topic.
    We WANT hot-button issues - our job is to bring nuance to them.
    
    We SKIP only: celebrity gossip, lifestyle fluff, shopping content, sports scores
    We KEEP: polarizing debates on policy, society, politics, culture
    
    Returns (articles_to_score, articles_to_skip).
    Also sets initial relevance_score on skipped articles.
    """
    from app.trending.topic_signals import (
        calculate_topic_signal_score,
        get_trending_topics_from_premium_sources
    )
    
    try:
        trending_keywords = get_trending_topics_from_premium_sources(48)
    except Exception as e:
        logger.warning(f"Failed to fetch trending topics, using neutral scoring: {e}")
        trending_keywords = {}
    
    to_score = []
    to_skip = []
    
    for article in articles:
        if not article.title:
            article.relevance_score = 0.0
            to_skip.append(article)
            continue
            
        title_lower = article.title.lower()
        
        if any(kw in title_lower for kw in LOW_VALUE_KEYWORDS):
            article.relevance_score = 0.1
            to_skip.append(article)
            continue
        
        if any(re.search(pattern, title_lower) for pattern in PRODUCT_REVIEW_PATTERNS):
            article.relevance_score = 0.1
            to_skip.append(article)
            continue
        
        if any(kw in title_lower for kw in HIGH_VALUE_KEYWORDS):
            article.relevance_score = 0.9
            to_score.append(article)
            continue
        
        topic_signal = calculate_topic_signal_score(
            article.title, article.summary, trending=trending_keywords
        )
        if topic_signal >= 0.5:
            article.relevance_score = 0.7 + (topic_signal * 0.3)
            to_score.append(article)
            continue
        
        heuristic_score = score_sensationalism(article.title)
        if heuristic_score >= 0.4:
            article.relevance_score = 0.5
            to_score.append(article)
            continue
        
        if article.source and article.source.reputation_score >= 0.7:
            article.relevance_score = 0.4
            to_score.append(article)
        else:
            article.relevance_score = 0.2
            to_skip.append(article)
    
    return to_score, to_skip


def score_articles_with_llm(articles: List[NewsArticle]) -> List[NewsArticle]:
    """
    Score articles using LLM for sensationalism.
    Pre-filters to reduce LLM costs - only quality candidates get scored.
    """
    to_score, skipped = pre_filter_articles(articles)
    
    logger.info(f"Pre-filter: {len(to_score)} to score, {len(skipped)} skipped")
    
    if not to_score:
        return articles
    
    api_key, provider = get_system_api_key()
    
    if not api_key:
        for article in to_score:
            article.sensationalism_score = score_sensationalism(article.title)
        return articles
    
    try:
        if provider == 'openai':
            _score_with_openai(to_score, api_key)
        elif provider == 'anthropic':
            _score_with_anthropic(to_score, api_key)
    except Exception as e:
        logger.error(f"LLM scoring failed: {e}")
        for article in to_score:
            article.sensationalism_score = score_sensationalism(article.title)
    
    return articles


def _score_with_openai(articles: List[NewsArticle], api_key: str) -> List[NewsArticle]:
    """Score articles using OpenAI for sensationalism and relevance."""
    import openai
    
    client = openai.OpenAI(api_key=api_key)
    
    headlines = [f"{i+1}. {a.title}" for i, a in enumerate(articles)]
    
    prompt = f"""Rate each headline on two scales (0-1):

1. SENSATIONALISM:
- 0 = neutral, factual, professional journalism
- 0.5 = slightly attention-grabbing but acceptable
- 1 = clickbait, sensationalist, emotionally manipulative

2. RELEVANCE (discussion potential for civic debate platform):
- 0 = product reviews, sports scores, celebrity gossip, lifestyle content
- 0.5 = interesting but not policy-relevant
- 1 = policy debates, societal issues, political/economic topics worth deliberating

Headlines:
{chr(10).join(headlines)}

Return ONLY a JSON array of objects, e.g. [{{"s": 0.2, "r": 0.8}}, {{"s": 0.5, "r": 0.3}}]"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a media quality analyst for a civic debate platform."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=500,
        temperature=0.3
    )
    
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from OpenAI")
    scores = extract_json(content)
    
    for i, article in enumerate(articles):
        if i < len(scores):
            article.sensationalism_score = float(scores[i].get('s', 0.5))
            article.relevance_score = float(scores[i].get('r', article.relevance_score or 0.5))
        else:
            article.sensationalism_score = score_sensationalism(article.title)
    
    return articles


def _score_with_anthropic(articles: List[NewsArticle], api_key: str) -> List[NewsArticle]:
    """Score articles using Anthropic for sensationalism and relevance."""
    import anthropic
    
    client = anthropic.Anthropic(api_key=api_key)
    
    headlines = [f"{i+1}. {a.title}" for i, a in enumerate(articles)]
    
    prompt = f"""Rate each headline on two scales (0-1):

1. SENSATIONALISM:
- 0 = neutral, factual, professional journalism
- 0.5 = slightly attention-grabbing but acceptable
- 1 = clickbait, sensationalist, emotionally manipulative

2. RELEVANCE (discussion potential for civic debate platform):
- 0 = product reviews, sports scores, celebrity gossip, lifestyle content
- 0.5 = interesting but not policy-relevant
- 1 = policy debates, societal issues, political/economic topics worth deliberating

Headlines:
{chr(10).join(headlines)}

Return ONLY a JSON array of objects, e.g. [{{"s": 0.2, "r": 0.8}}, {{"s": 0.5, "r": 0.3}}]"""

    message = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    
    content_block = message.content[0]
    content = getattr(content_block, 'text', None) or str(content_block)
    scores = extract_json(content)
    
    for i, article in enumerate(articles):
        if i < len(scores):
            article.sensationalism_score = float(scores[i].get('s', 0.5))
            article.relevance_score = float(scores[i].get('r', article.relevance_score or 0.5))
        else:
            article.sensationalism_score = score_sensationalism(article.title)
    
    return articles


VALID_TOPICS = [
    'Healthcare', 'Environment', 'Education', 'Technology', 'Economy', 
    'Politics', 'Society', 'Infrastructure', 'Geopolitics', 'Business', 'Culture'
]

TARGET_AUDIENCE_DESCRIPTION = """
Our target audience follows podcasts like: The Rest is Politics, Newsagents, Triggernometry, 
All-In Podcast, UnHerd, Diary of a CEO, Modern Wisdom, Tim Ferriss Show, Louis Theroux.

They value:
- Nuanced political/policy discussion (not partisan culture war)
- Geopolitics and international affairs
- Technology, economics, and entrepreneurship
- Intellectual depth over sensationalism
- Contrarian or heterodox perspectives
- Long-form substantive debate
"""


def score_topic(topic: TrendingTopic) -> TrendingTopic:
    """
    Score a topic for civic relevance, quality, risk, and audience alignment.
    """
    api_key, provider = get_system_api_key()
    
    if not api_key:
        topic.civic_score = 0.5
        topic.quality_score = 0.5
        topic.audience_score = 0.5
        topic.primary_topic = 'Society'
        topic.risk_flag = False
        return topic
    
    article_titles = [ta.article.title for ta in topic.articles if ta.article][:5]
    
    prompt = f"""Analyze this news topic cluster for a civic debate platform.

{TARGET_AUDIENCE_DESCRIPTION}

Topic: {topic.title}
Source articles:
{chr(10).join(f'- {t}' for t in article_titles)}

Rate on 0-1 scale and respond in JSON:
{{
    "civic_score": <0-1: how valuable is this for civic discussion? 1=very important public policy issue, 0=trivial/celebrity gossip>,
    "quality_score": <0-1: how factual and substantive? 1=well-sourced news, 0=rumor/opinion>,
    "audience_score": <0-1: how appealing to our target audience? 1=perfect fit for intellectual podcast listeners, 0=tabloid/celebrity content>,
    "risk_flag": <true/false: is this culture war bait, defamation risk, or likely to cause more division than insight?>,
    "risk_reason": "<if risk_flag is true, explain briefly>",
    "primary_topic": "<one of: Healthcare, Environment, Education, Technology, Economy, Politics, Society, Infrastructure, Geopolitics, Business, Culture>",
    "canonical_tags": ["<tag1>", "<tag2>", "<tag3>"] (normalized lowercase topic identifiers for deduplication)
}}

Respond with ONLY valid JSON."""

    try:
        if provider == 'openai':
            result = _call_openai(api_key, prompt)
        else:
            result = _call_anthropic(api_key, prompt)
        
        data = extract_json(result)
        
        topic.civic_score = float(data.get('civic_score', 0.5))
        topic.quality_score = float(data.get('quality_score', 0.5))
        topic.audience_score = float(data.get('audience_score', 0.5))
        topic.risk_flag = bool(data.get('risk_flag', False))
        topic.risk_reason = data.get('risk_reason', '')[:200] if data.get('risk_reason') else None
        topic.canonical_tags = data.get('canonical_tags', [])
        
        primary_topic = data.get('primary_topic', 'Society')
        if primary_topic in VALID_TOPICS:
            topic.primary_topic = primary_topic
        else:
            topic.primary_topic = 'Society'
        
        if topic.canonical_tags:
            topic.topic_slug = '_'.join(topic.canonical_tags[:4])
        
    except Exception as e:
        logger.error(f"Topic scoring failed: {e}")
        topic.civic_score = 0.5
        topic.quality_score = 0.5
        topic.audience_score = 0.5
        topic.primary_topic = 'Society'
        topic.risk_flag = False
    
    return topic


def _call_openai(api_key: str, prompt: str) -> str:
    import openai
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a civic media analyst. Respond only in valid JSON."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=300,
        temperature=0.3
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from OpenAI")
    return content


def _call_anthropic(api_key: str, prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    content_block = message.content[0]
    content = getattr(content_block, 'text', None) or str(content_block)
    if not content:
        raise ValueError("Empty response from Anthropic")
    return content
