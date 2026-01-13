"""
Perspective Generation for News Transparency Page

Generates perspective analysis for topics not in the daily brief.
Reuses BriefGenerator LLM infrastructure for consistency.
"""

from datetime import date, datetime
from typing import Dict
import os
import json
import re
from app.models import TrendingTopic, NewsPerspectiveCache, NewsArticle, db
import logging

logger = logging.getLogger(__name__)


def generate_perspective_analysis(topic: TrendingTopic) -> Dict:
    """
    Generate perspective analysis for a topic.

    Reuses BriefGenerator LLM patterns but simplified (no headline/bullets).
    Caches result in NewsPerspectiveCache for reuse.

    Args:
        topic: TrendingTopic to analyze

    Returns:
        dict: {
            'perspectives': {'left': '...', 'center': '...', 'right': '...'},
            'so_what': str,
            'personal_impact': str
        }

    Raises:
        ValueError: If LLM generation fails
    """
    # Check cache first (shouldn't happen since routes.py checks, but be safe)
    cached = NewsPerspectiveCache.query.filter_by(
        trending_topic_id=topic.id,
        generated_date=date.today()
    ).first()

    if cached:
        logger.info(f"Using cached perspective for topic {topic.id}")
        return {
            'perspectives': cached.perspectives,
            'so_what': cached.so_what,
            'personal_impact': cached.personal_impact
        }

    # Get articles for this topic
    article_links = topic.articles.all() if hasattr(topic, 'articles') else []
    articles = [link.article for link in article_links if link.article]

    if not articles:
        logger.warning(f"Topic {topic.id} has no articles - cannot generate perspectives")
        raise ValueError("No articles available for perspective generation")

    # Prepare prompt (simplified from brief generation)
    prompt = _build_perspective_prompt(topic, articles[:8])

    try:
        # Call LLM using our own client (not BriefGenerator's private method)
        response = _call_llm(prompt)
        data = _extract_json(response)

        # Validate required fields
        if 'perspectives' not in data:
            logger.warning("LLM response missing perspectives field")
            data['perspectives'] = {'left': 'Not available', 'center': 'Not available', 'right': 'Not available'}

        if 'so_what' not in data:
            data['so_what'] = None

        if 'personal_impact' not in data:
            data['personal_impact'] = None

        # Cache the result (with proper error handling)
        cache_entry = NewsPerspectiveCache(
            trending_topic_id=topic.id,
            generated_date=date.today(),
            perspectives=data['perspectives'],
            so_what=data['so_what'],
            personal_impact=data['personal_impact']
        )

        try:
            db.session.add(cache_entry)
            db.session.commit()
            logger.info(f"Generated and cached perspective for topic {topic.id}")
        except Exception as cache_error:
            db.session.rollback()
            logger.warning(
                f"Failed to cache perspective for topic {topic.id}: {cache_error}. "
                "Returning generated data without caching."
            )
            # Continue and return the data even if caching fails

        return {
            'perspectives': data['perspectives'],
            'so_what': data['so_what'],
            'personal_impact': data['personal_impact']
        }

    except Exception as e:
        logger.error(f"Failed to generate perspective for topic {topic.id}: {e}", exc_info=True)
        raise


def _build_perspective_prompt(topic: TrendingTopic, articles: list) -> str:
    """
    Build LLM prompt for perspective generation.

    Simplified from brief generator - focuses only on perspectives and analysis.
    """
    current_date = datetime.now()
    current_year = current_date.year
    date_context = current_date.strftime('%d %B %Y')

    # Prepare article summaries organized by political leaning
    article_context = []
    source_perspectives = {'left': [], 'center': [], 'right': []}

    for i, article in enumerate(articles, start=1):
        summary = article.summary[:300] if article.summary else article.title
        source_name = article.source.name if article.source else 'Unknown'

        pub_date = ""
        if article.published_at:
            pub_date = f" ({article.published_at.strftime('%d %b %Y')})"

        # Get political leaning (-2 to +2 scale)
        leaning_score = article.source.political_leaning if article.source and article.source.political_leaning is not None else 0

        article_context.append(f"{i}. [{source_name}]{pub_date} {article.title}\n   {summary}")

        # Group by leaning
        if leaning_score <= -1:  # Left
            source_perspectives['left'].append(f"{source_name}: {summary[:150]}")
        elif leaning_score >= 1:  # Right
            source_perspectives['right'].append(f"{source_name}: {summary[:150]}")
        else:  # Center
            source_perspectives['center'].append(f"{source_name}: {summary[:150]}")

    article_text = '\n'.join(article_context)

    # Build source breakdowns
    left_sources = '\n'.join(source_perspectives['left'][:3]) if source_perspectives['left'] else "No left-leaning sources"
    center_sources = '\n'.join(source_perspectives['center'][:3]) if source_perspectives['center'] else "No center sources"
    right_sources = '\n'.join(source_perspectives['right'][:3]) if source_perspectives['right'] else "No right-leaning sources"

    prompt = f"""You are a senior news analyst creating perspective analysis for our news transparency platform.

TODAY'S DATE: {date_context}
CURRENT YEAR: {current_year}

TOPIC: {topic.title}

ARTICLES FROM DIFFERENT SOURCES:
{article_text}

SOURCE BREAKDOWNS BY POLITICAL LEANING:

LEFT-LEANING SOURCES:
{left_sources}

CENTER SOURCES:
{center_sources}

RIGHT-LEANING SOURCES:
{right_sources}

Generate perspective analysis with:

1. PERSONAL IMPACT: Two-part explanation (2 sentences max, 50 words total).
   - MICRO/LOCAL: Direct impact on those in the affected region
   - MACRO/GLOBAL: Why this matters globally (for international stories, emphasise this)

   Examples:
   ✓ "For Ukrainians: 1.5 million face weeks without heating. Globally: this escalation could push European gas prices up 10-15% and tests NATO's resolve."
   ✓ "For UK residents: council tax bills may rise £200/year. Internationally: this signals how wealthy nations are funding climate transition costs."

2. SO WHAT: One paragraph (2-3 sentences) explaining concrete, real-world impact.
   - BE SPECIFIC: Include numbers, dates, affected groups
   - Show second-order effects
   - Make it personal and concrete

   Example:
   ✓ "So what? 17 million Americans in red states will lose Medicaid expansion by March if governors don't reverse course. Last time federal funding changed (2017), 8 states took 2+ years to respond."

3. PERSPECTIVES: How different outlets are framing this story (one sentence each):
   - Left-leaning view: How left/lean-left sources frame it
   - Centre view: How center sources frame it
   - Right-leaning view: How right/lean-right sources frame it

   For each perspective:
   - Summarise the emphasis, angle, or framing
   - Note what they highlight or downplay
   - Keep it neutral - describe the framing, don't judge it

Guidelines:
- Use British English (analyse, centre, organisation)
- No em dashes. Use commas, colons, or periods
- Neutral, calm tone
- Focus on facts, not opinion
- Be specific with numbers, dates, names
- Only use information from the articles provided

Return JSON:
{{
  "personal_impact": "Two-part explanation (micro + macro)...",
  "so_what": "So what? [Specific, concrete analysis]...",
  "perspectives": {{
    "left": "Left-leaning outlets emphasise...",
    "center": "Centre outlets focus on...",
    "right": "Right-leaning outlets highlight..."
  }}
}}"""

    return prompt


def _call_llm(prompt: str) -> str:
    """
    Call LLM API (OpenAI or Anthropic).

    Tries OpenAI first, falls back to Anthropic if available.

    Args:
        prompt: User prompt

    Returns:
        str: LLM response text

    Raises:
        ValueError: If no LLM provider is available
    """
    openai_key = os.environ.get('OPENAI_API_KEY')
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')

    if openai_key:
        try:
            return _call_openai(prompt, openai_key)
        except Exception as e:
            logger.warning(f"OpenAI call failed: {e}, trying Anthropic")
            if anthropic_key:
                return _call_anthropic(prompt, anthropic_key)
            raise

    elif anthropic_key:
        return _call_anthropic(prompt, anthropic_key)

    else:
        raise ValueError("No LLM API key configured (OPENAI_API_KEY or ANTHROPIC_API_KEY)")


def _call_openai(prompt: str, api_key: str) -> str:
    """Call OpenAI API"""
    import openai

    client = openai.OpenAI(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a news editor creating calm, neutral briefings. Respond only in valid JSON."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,  # Slightly more than brief for perspectives
            temperature=0.3
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from OpenAI")

        return content

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        raise


def _call_anthropic(prompt: str, api_key: str) -> str:
    """Call Anthropic API"""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=600,
            temperature=0.3,
            system="You are a news editor creating calm, neutral briefings. Respond only in valid JSON.",
            messages=[{"role": "user", "content": prompt}]
        )

        content_block = message.content[0]
        content = getattr(content_block, 'text', None) or str(content_block)

        if not content:
            raise ValueError("Empty response from Anthropic")

        return content

    except Exception as e:
        logger.error(f"Anthropic API error: {e}")
        raise


def _extract_json(text: str) -> Dict:
    """
    Extract JSON from LLM response text.

    Handles responses wrapped in markdown code blocks.

    Args:
        text: LLM response (may contain markdown)

    Returns:
        dict: Parsed JSON

    Raises:
        ValueError: If JSON parsing fails
    """
    # Remove markdown code blocks if present
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing failed: {e}\nText: {text[:500]}")
        raise ValueError(f"Invalid JSON from LLM: {e}")
