"""
Article and Topic Scoring Pipeline

Uses LLM to score:
- Sensationalism (clickbait detection)
- Civic relevance (worth debating?)
- Quality (factual, multi-perspective)
- Risk flags (culture war, defamation)
"""

import os
import logging
import json
import re
from typing import Dict, List, Optional, Tuple

from app.models import NewsArticle, TrendingTopic

logger = logging.getLogger(__name__)


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


def score_articles_with_llm(articles: List[NewsArticle]) -> List[NewsArticle]:
    """Score multiple articles using LLM for sensationalism."""
    api_key, provider = get_system_api_key()
    
    if not api_key:
        for article in articles:
            article.sensationalism_score = score_sensationalism(article.title)
        return articles
    
    try:
        if provider == 'openai':
            return _score_with_openai(articles, api_key)
        elif provider == 'anthropic':
            return _score_with_anthropic(articles, api_key)
    except Exception as e:
        logger.error(f"LLM scoring failed: {e}")
        for article in articles:
            article.sensationalism_score = score_sensationalism(article.title)
    
    return articles


def _score_with_openai(articles: List[NewsArticle], api_key: str) -> List[NewsArticle]:
    """Score articles using OpenAI."""
    import openai
    
    client = openai.OpenAI(api_key=api_key)
    
    headlines = [f"{i+1}. {a.title}" for i, a in enumerate(articles)]
    
    prompt = f"""Rate each headline for sensationalism on a scale of 0-1 where:
- 0 = neutral, factual, professional journalism
- 0.5 = slightly attention-grabbing but acceptable
- 1 = clickbait, sensationalist, emotionally manipulative

Headlines:
{chr(10).join(headlines)}

Return ONLY a JSON array of numbers in order, e.g. [0.2, 0.5, 0.1]"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a media quality analyst."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=200,
        temperature=0.3
    )
    
    content = response.choices[0].message.content
    scores = json.loads(content)
    
    for i, article in enumerate(articles):
        if i < len(scores):
            article.sensationalism_score = float(scores[i])
        else:
            article.sensationalism_score = score_sensationalism(article.title)
    
    return articles


def _score_with_anthropic(articles: List[NewsArticle], api_key: str) -> List[NewsArticle]:
    """Score articles using Anthropic."""
    import anthropic
    
    client = anthropic.Anthropic(api_key=api_key)
    
    headlines = [f"{i+1}. {a.title}" for i, a in enumerate(articles)]
    
    prompt = f"""Rate each headline for sensationalism on a scale of 0-1 where:
- 0 = neutral, factual, professional journalism
- 0.5 = slightly attention-grabbing but acceptable
- 1 = clickbait, sensationalist, emotionally manipulative

Headlines:
{chr(10).join(headlines)}

Return ONLY a JSON array of numbers in order, e.g. [0.2, 0.5, 0.1]"""

    message = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    
    content = message.content[0].text
    scores = json.loads(content)
    
    for i, article in enumerate(articles):
        if i < len(scores):
            article.sensationalism_score = float(scores[i])
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
        
        data = json.loads(result)
        
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
    return response.choices[0].message.content


def _call_anthropic(api_key: str, prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text
