"""
Balanced Seed Statement Generator

Generates diverse seed statements for trending topics or raw content
to kick-start nuanced discussions.

Supports two modes:
1. TrendingTopic mode: Pass a TrendingTopic object to generate statements from its articles
2. Raw content mode: Pass title, excerpt, and optionally source_name to generate statements
"""

import os
import logging
import json
from typing import List, Dict, Optional
from functools import partial

from app.models import TrendingTopic

logger = logging.getLogger(__name__)


def generate_seed_statements(
    topic: Optional[TrendingTopic] = None,
    title: Optional[str] = None,
    excerpt: Optional[str] = None,
    source_name: Optional[str] = None,
    count: int = 5
) -> List[Dict]:
    """
    Generate balanced seed statements for a topic or from raw content.

    Returns list of {"content": str, "position": "pro"/"con"/"neutral"}

    Args:
        topic: TrendingTopic object (existing behavior)
        title: Article/topic title for raw content mode
        excerpt: Article excerpt/summary for raw content mode
        source_name: Optional source attribution for raw content mode
        count: Number of statements to generate (default 5)

    Usage:
        - For TrendingTopic: generate_seed_statements(topic=my_topic)
        - For raw content: generate_seed_statements(title="...", excerpt="...")

    Raises:
        ValueError: If neither topic nor title is provided
    """
    if not topic and not title:
        raise ValueError("Either topic or title must be provided")

    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if api_key:
            return _generate_with_anthropic(
                topic=topic,
                title=title,
                excerpt=excerpt,
                source_name=source_name,
                count=count,
                api_key=api_key
            )
        return []

    return _generate_with_openai(
        topic=topic,
        title=title,
        excerpt=excerpt,
        source_name=source_name,
        count=count,
        api_key=api_key
    )


# Convenience alias for raw content mode
generate_seed_statements_from_content = partial(generate_seed_statements, topic=None)


def _build_prompt(
    topic: Optional[TrendingTopic],
    title: Optional[str],
    excerpt: Optional[str],
    source_name: Optional[str],
    count: int
) -> str:
    """Build the prompt for seed statement generation."""
    if topic:
        # Extract from TrendingTopic
        topic_title = topic.title
        article_titles = [ta.article.title for ta in topic.articles if ta.article][:5]
        context_section = f"Related news:\n{chr(10).join(f'- {t}' for t in article_titles)}"
    else:
        # Use raw content
        topic_title = title
        context_parts = []
        if excerpt:
            context_parts.append(f"Summary:\n{excerpt}")
        if source_name:
            context_parts.append(f"Source: {source_name}")
        context_section = "\n\n".join(context_parts) if context_parts else ""

    prompt = f"""Generate {count} diverse seed statements for a public deliberation on this topic:

Topic: {topic_title}

{context_section}

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
    return prompt


def _parse_and_validate_statements(response_text: str, count: int) -> List[Dict]:
    """
    Parse raw LLM response into validated statement dicts.
    Strips markdown code fences, parses JSON, validates position and content.
    """
    content = response_text.strip()
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


def _generate_with_openai(
    topic: Optional[TrendingTopic],
    title: Optional[str],
    excerpt: Optional[str],
    source_name: Optional[str],
    count: int,
    api_key: str
) -> List[Dict]:
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

    prompt = _build_prompt(topic, title, excerpt, source_name, count)

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
        return _parse_and_validate_statements(content, count)
    
    except (SystemExit, KeyboardInterrupt):
        logger.error("OpenAI call was interrupted (SystemExit/KeyboardInterrupt)")
        return []
    except Exception as e:
        logger.error(f"Seed generation failed: {e}")
        return []


def _generate_with_anthropic(
    topic: Optional[TrendingTopic],
    title: Optional[str],
    excerpt: Optional[str],
    source_name: Optional[str],
    count: int,
    api_key: str
) -> List[Dict]:
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

    prompt = _build_prompt(topic, title, excerpt, source_name, count)

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        
        content = message.content[0].text
        return _parse_and_validate_statements(content, count)
    
    except (SystemExit, KeyboardInterrupt):
        logger.error("Anthropic call was interrupted (SystemExit/KeyboardInterrupt)")
        return []
    except Exception as e:
        logger.error(f"Seed generation failed: {e}")
        return []
