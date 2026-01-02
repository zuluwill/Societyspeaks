"""
Balanced Seed Statement Generator

Generates diverse seed statements for trending topics
to kick-start nuanced discussions.
"""

import os
import logging
import json
from typing import List, Dict, Optional

from app.models import TrendingTopic

logger = logging.getLogger(__name__)


def generate_seed_statements(topic: TrendingTopic, count: int = 5) -> List[Dict]:
    """
    Generate balanced seed statements for a topic.
    Returns list of {"content": str, "position": "pro"/"con"/"neutral"}
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if api_key:
            return _generate_with_anthropic(topic, count, api_key)
        return []
    
    return _generate_with_openai(topic, count, api_key)


def _generate_with_openai(topic: TrendingTopic, count: int, api_key: str) -> List[Dict]:
    """Generate seeds using OpenAI."""
    try:
        import openai
    except ImportError:
        logger.error("OpenAI library not installed")
        return []
    
    try:
        client = openai.OpenAI(api_key=api_key, timeout=60.0)
    except Exception as e:
        logger.error(f"Failed to create OpenAI client: {e}")
        return []
    
    article_titles = [ta.article.title for ta in topic.articles if ta.article][:5]
    
    prompt = f"""Generate {count} diverse seed statements for a public deliberation on this topic:

Topic: {topic.title}

Related news:
{chr(10).join(f'- {t}' for t in article_titles)}

Requirements:
- Generate statements representing DIFFERENT viewpoints (some pro, some con, some neutral/questioning)
- Each statement should be 20-80 words
- Statements should be substantive and invite thoughtful responses
- Avoid strawman arguments - represent each position charitably
- Include at least one statement from each perspective

Return as JSON array:
[
    {{"content": "statement text", "position": "pro"}},
    {{"content": "statement text", "position": "con"}},
    {{"content": "statement text", "position": "neutral"}},
    ...
]

Return ONLY valid JSON array."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a civic discourse facilitator who presents all viewpoints fairly."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,
            temperature=0.8
        )
        
        content = response.choices[0].message.content
        
        content = content.strip()
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        
        statements = json.loads(content)
        
        valid_positions = ['pro', 'con', 'neutral']
        validated = []
        for stmt in statements:
            if isinstance(stmt, dict) and 'content' in stmt:
                position = stmt.get('position', 'neutral').lower()
                if position not in valid_positions:
                    position = 'neutral'
                validated.append({
                    'content': stmt['content'][:500],
                    'position': position
                })
        
        return validated[:count]
    
    except (SystemExit, KeyboardInterrupt):
        logger.error("OpenAI call was interrupted (SystemExit/KeyboardInterrupt)")
        return []
    except Exception as e:
        logger.error(f"Seed generation failed: {e}")
        return []


def _generate_with_anthropic(topic: TrendingTopic, count: int, api_key: str) -> List[Dict]:
    """Generate seeds using Anthropic."""
    try:
        import anthropic
    except ImportError:
        logger.error("Anthropic library not installed")
        return []
    
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=60.0)
    except Exception as e:
        logger.error(f"Failed to create Anthropic client: {e}")
        return []
    
    article_titles = [ta.article.title for ta in topic.articles if ta.article][:5]
    
    prompt = f"""Generate {count} diverse seed statements for a public deliberation on this topic:

Topic: {topic.title}

Related news:
{chr(10).join(f'- {t}' for t in article_titles)}

Requirements:
- Generate statements representing DIFFERENT viewpoints (some pro, some con, some neutral/questioning)
- Each statement should be 20-80 words
- Statements should be substantive and invite thoughtful responses
- Avoid strawman arguments - represent each position charitably
- Include at least one statement from each perspective

Return as JSON array:
[
    {{"content": "statement text", "position": "pro"}},
    {{"content": "statement text", "position": "con"}},
    {{"content": "statement text", "position": "neutral"}},
    ...
]

Return ONLY valid JSON array."""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        
        content = message.content[0].text
        
        content = content.strip()
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        
        statements = json.loads(content)
        
        valid_positions = ['pro', 'con', 'neutral']
        validated = []
        for stmt in statements:
            if isinstance(stmt, dict) and 'content' in stmt:
                position = stmt.get('position', 'neutral').lower()
                if position not in valid_positions:
                    position = 'neutral'
                validated.append({
                    'content': stmt['content'][:500],
                    'position': position
                })
        
        return validated[:count]
    
    except (SystemExit, KeyboardInterrupt):
        logger.error("Anthropic call was interrupted (SystemExit/KeyboardInterrupt)")
        return []
    except Exception as e:
        logger.error(f"Seed generation failed: {e}")
        return []
