"""
Brief Generator

Generates daily briefs from selected topics using LLM.
Creates concise headlines, bullet summaries, and extracts verification links.
"""

import os
import logging
import json
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple, Any
from app.models import DailyBrief, BriefItem, TrendingTopic, NewsArticle, db
from app.brief.coverage_analyzer import CoverageAnalyzer
from app.trending.scorer import extract_json, get_system_api_key
import re

logger = logging.getLogger(__name__)


class BriefGenerator:
    """
    Generates daily brief content using LLM.

    Creates:
    - Brief title
    - Intro text (calm framing)
    - Per-item headlines (shorter than topic titles)
    - Per-item bullet summaries (2-3 bullets)
    - Verification links (extracted from articles)
    - CTA text for discussions
    """

    def __init__(self):
        self.api_key, self.provider = get_system_api_key()
        if not self.api_key:
            raise ValueError("No LLM API key found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY")

    def generate_brief(
        self,
        brief_date: date,
        selected_topics: List[TrendingTopic],
        auto_publish: bool = True
    ) -> DailyBrief:
        """
        Generate complete daily brief from selected topics.

        Args:
            brief_date: Date of the brief
            selected_topics: List of TrendingTopic instances (pre-selected)
            auto_publish: If True, set status to 'ready' (default True)

        Returns:
            DailyBrief instance (saved to database)
        """
        if not selected_topics:
            raise ValueError("Cannot generate brief with no topics")

        logger.info(f"Generating brief for {brief_date} with {len(selected_topics)} topics")

        # Check if brief already exists
        existing = DailyBrief.query.filter_by(date=brief_date).first()
        if existing:
            logger.warning(f"Brief already exists for {brief_date}, updating...")
            brief = existing
        else:
            brief = DailyBrief(
                date=brief_date,
                status='draft',
                auto_selected=True
            )
            db.session.add(brief)
            db.session.flush()  # Get brief.id

        # Generate brief-level content
        brief.title = self._generate_brief_title(selected_topics)
        brief.intro_text = self._generate_intro_text(selected_topics)

        # Generate items
        for position, topic in enumerate(selected_topics, start=1):
            try:
                item = self._generate_brief_item(brief, topic, position)
                db.session.add(item)
                logger.info(f"Generated item {position}: {item.headline}")
            except Exception as e:
                logger.error(f"Failed to generate item for topic {topic.id}: {e}")
                # Continue with other items
                continue

        # Set status
        brief.status = 'ready' if auto_publish else 'draft'
        brief.created_at = datetime.utcnow()

        db.session.commit()

        logger.info(f"Brief generated successfully: {brief.title} ({brief.item_count} items)")

        return brief

    def _generate_brief_title(self, topics: List[TrendingTopic]) -> str:
        """
        Generate brief title from topic categories.

        Examples:
        - "Tuesday's Brief: Climate, Tech, Healthcare"
        - "Today's Brief: UK Politics, Global Trade"
        """
        # Get topic categories
        categories = []
        for topic in topics:
            if topic.primary_topic and topic.primary_topic not in categories:
                categories.append(topic.primary_topic.title() if topic.primary_topic else 'News')

        # Fallback if no categories
        if not categories:
            categories = ['News', 'Politics', 'Economy'][:len(topics)]

        # Get day name
        day_name = datetime.now().strftime('%A')

        # Format title
        category_str = ', '.join(categories[:4])  # Max 4 categories
        if len(categories) > 4:
            category_str += ', More'

        return f"{day_name}'s Brief: {category_str}"

    def _generate_intro_text(self, topics: List[TrendingTopic]) -> str:
        """
        Generate calm, neutral intro text.

        Example:
        "Today's brief covers 4 stories that matter for sense-making.
        Not comprehensive news—just what's worth understanding today."
        """
        count = len(topics)

        intros = [
            f"Today's brief covers {count} stories that matter for sense-making. Not comprehensive news—just what's worth understanding today.",
            f"{count} stories from today's news, with context for sense-making. Coverage analysis and primary sources included.",
            f"Your evening brief: {count} stories worth understanding. We show which outlets covered each story and link to primary sources.",
            f"{count} topics from today, selected for civic importance and coverage across perspectives. This isn't all the news—it's what matters."
        ]

        # Simple selection based on day
        import random
        random.seed(datetime.now().day)  # Same intro all day
        return random.choice(intros)

    def _generate_brief_item(
        self,
        brief: DailyBrief,
        topic: TrendingTopic,
        position: int
    ) -> BriefItem:
        """
        Generate a single brief item from a trending topic.

        Args:
            brief: Parent DailyBrief instance
            topic: TrendingTopic to generate from
            position: Display position (1-5)

        Returns:
            BriefItem instance (not yet saved)
        """
        # Get articles for this topic
        article_links = topic.articles.all() if hasattr(topic, 'articles') else []
        articles = [link.article for link in article_links if link.article]

        # Calculate coverage
        analyzer = CoverageAnalyzer(topic)
        coverage_data = analyzer.calculate_distribution()

        # Generate content via LLM
        llm_content = self._generate_item_content(topic, articles)

        # Extract verification links
        verification_links = self._extract_verification_links(articles)

        # Calculate average sensationalism
        sensationalism_scores = [a.sensationalism_score for a in articles if a.sensationalism_score is not None]
        avg_sensationalism = sum(sensationalism_scores) / len(sensationalism_scores) if sensationalism_scores else None

        # Generate CTA text
        cta_text = self._generate_cta_text(topic)

        # Create item
        item = BriefItem(
            brief_id=brief.id,
            position=position,
            trending_topic_id=topic.id,
            headline=llm_content['headline'],
            summary_bullets=llm_content['bullets'],
            coverage_distribution=coverage_data['distribution'],
            coverage_imbalance=coverage_data['imbalance_score'],
            source_count=coverage_data['source_count'],
            sources_by_leaning=coverage_data['sources_by_leaning'],
            sensationalism_score=avg_sensationalism,
            sensationalism_label=analyzer.get_sensationalism_label(avg_sensationalism),
            verification_links=verification_links,
            discussion_id=topic.discussion_id,  # Link to discussion if topic was published
            cta_text=cta_text
        )

        return item

    def _generate_item_content(
        self,
        topic: TrendingTopic,
        articles: List[NewsArticle]
    ) -> Dict[str, Any]:
        """
        Generate headline and bullets using LLM.

        Returns:
            dict: {
                'headline': str (10 words max),
                'bullets': list of str (2-3 bullets)
            }
        """
        # Prepare article summaries for context
        article_context = []
        for i, article in enumerate(articles[:5], start=1):  # Max 5 articles
            summary = article.summary[:200] if article.summary else article.title
            article_context.append(f"{i}. {article.source.name}: {article.title}\n   {summary}")

        article_text = '\n'.join(article_context)

        prompt = f"""Generate a brief news item from these articles about the same story.

ARTICLES:
{article_text}

Generate:
1. A concise headline (8-12 words, neutral tone, no sensationalism)
2. 2-3 bullet points summarizing what happened (factual, no opinion)

Guidelines:
- Headline should be shorter and punchier than article titles
- Bullets should be "what happened" not "why it matters"
- Use neutral language (avoid "bombshell", "shocking", etc.)
- Focus on facts, not speculation
- Each bullet should be 10-20 words

Return JSON:
{{
  "headline": "...",
  "bullets": ["bullet 1", "bullet 2", "bullet 3"]
}}"""

        try:
            response = self._call_llm(prompt)
            data = extract_json(response)

            # Validate response
            if 'headline' not in data or 'bullets' not in data:
                raise ValueError("Missing headline or bullets in LLM response")

            if not isinstance(data['bullets'], list) or len(data['bullets']) < 2:
                raise ValueError("Bullets must be a list with at least 2 items")

            # Trim bullets to 3 max
            data['bullets'] = data['bullets'][:3]

            return data

        except Exception as e:
            logger.error(f"LLM content generation failed: {e}")
            # Fallback to topic title and description
            return {
                'headline': topic.title[:100],  # Truncate if needed
                'bullets': [
                    topic.description[:150] if topic.description else "Details unavailable",
                    f"Covered by {len(articles)} sources",
                    "See sources for full context"
                ]
            }

    def _extract_verification_links(
        self,
        articles: List[NewsArticle]
    ) -> List[Dict]:
        """
        Extract verification links from articles using LLM.

        Looks for:
        - Government documents
        - Academic studies
        - Official statements
        - Primary source datasets

        Returns:
            list: [
                {
                    'tier': 'primary' | 'reporting' | 'verification',
                    'url': str,
                    'type': str (government_document, study, news_article, etc.),
                    'description': str,
                    'is_paywalled': bool
                }
            ]
        """
        # Start with source articles as "reporting" tier
        links = []

        for article in articles[:3]:  # Top 3 articles
            # Check if likely paywalled
            is_paywalled = any(domain in article.url for domain in [
                'ft.com', 'economist.com', 'wsj.com', 'nytimes.com',
                'telegraph.co.uk', 'thetimes.co.uk'
            ])

            links.append({
                'tier': 'reporting',
                'url': article.url,
                'type': 'news_article',
                'description': f"{article.source.name} coverage",
                'is_paywalled': is_paywalled
            })

        # Try to extract primary sources via LLM
        try:
            summaries = [a.summary for a in articles if a.summary]
            if summaries:
                primary_sources = self._llm_extract_primary_sources(summaries[:3])
                links.extend(primary_sources)
        except Exception as e:
            logger.warning(f"Failed to extract primary sources: {e}")

        return links

    def _llm_extract_primary_sources(self, summaries: List[str]) -> List[Dict]:
        """
        Use LLM to extract primary source citations from article summaries.

        Returns:
            list: Primary source links
        """
        summaries_text = '\n\n---\n\n'.join(summaries)

        prompt = f"""Analyze these article summaries and extract any primary sources mentioned.

SUMMARIES:
{summaries_text}

Look for:
- Government reports, legislation, official statements
- Academic studies, research papers
- Court documents, legal filings
- Official datasets, statistics
- Press releases from official organizations

Return JSON array of sources (empty array if none found):
[
  {{
    "url": "https://...",
    "type": "government_report" | "study" | "official_statement" | "dataset" | "court_document",
    "description": "Brief description",
    "confidence": 0.0-1.0
  }}
]

Only include sources explicitly mentioned or cited. Do NOT guess URLs."""

        try:
            response = self._call_llm(prompt)
            data = extract_json(response)

            if not isinstance(data, list):
                return []

            # Convert to our format
            primary_links = []
            for source in data:
                if source.get('confidence', 0) >= 0.7:  # High confidence only
                    primary_links.append({
                        'tier': 'primary',
                        'url': source['url'],
                        'type': source['type'],
                        'description': source['description'],
                        'is_paywalled': False  # Primary sources usually free
                    })

            return primary_links

        except Exception as e:
            logger.warning(f"Primary source extraction failed: {e}")
            return []

    def _generate_cta_text(self, topic: TrendingTopic) -> str:
        """
        Generate call-to-action text for discussion.

        Returns:
            str: CTA text (e.g., "What do you think about this policy?")
        """
        if topic.seed_statements:
            # Use first seed statement as basis
            try:
                statements = json.loads(topic.seed_statements) if isinstance(topic.seed_statements, str) else topic.seed_statements
                if statements and len(statements) > 0:
                    first_statement = statements[0].get('text', '') if isinstance(statements[0], dict) else str(statements[0])
                    if first_statement:
                        return f"Vote: {first_statement[:80]}..."
            except:
                pass

        # Fallback CTA
        return "Share your view on this topic"

    def _call_llm(self, prompt: str) -> str:
        """
        Call LLM API (OpenAI or Anthropic).

        Args:
            prompt: User prompt

        Returns:
            str: LLM response text
        """
        if self.provider == 'openai':
            return self._call_openai(prompt)
        elif self.provider == 'anthropic':
            return self._call_anthropic(prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API"""
        import openai

        client = openai.OpenAI(api_key=self.api_key)

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a news editor creating calm, neutral briefings. Respond only in valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.3
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from OpenAI")

            return content

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic API"""
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        try:
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=500,
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


def generate_daily_brief(brief_date: Optional[date] = None, auto_publish: bool = True) -> Optional[DailyBrief]:
    """
    Convenience function to generate today's brief.

    Args:
        brief_date: Date to generate for (default: today)
        auto_publish: Set to 'ready' status if True

    Returns:
        DailyBrief instance, or None if no topics available
    """
    from app.brief.topic_selector import select_topics_for_date

    if brief_date is None:
        brief_date = date.today()

    # Select topics
    selector_import = select_topics_for_date
    topics = selector_import(brief_date, limit=5)

    if not topics:
        logger.warning(f"No topics available for brief on {brief_date} - skipping generation")
        return None

    # Generate brief
    generator = BriefGenerator()
    return generator.generate_brief(brief_date, topics, auto_publish)
