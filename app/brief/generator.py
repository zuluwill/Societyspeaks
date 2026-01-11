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
    
    Handles missing LLM keys gracefully by using fallback content generation.
    """

    def __init__(self):
        self.api_key, self.provider = get_system_api_key()
        self.llm_available = bool(self.api_key)
        
        if not self.llm_available:
            logger.warning("No LLM API key found. Brief will use fallback content generation.")

    def generate_brief(
        self,
        brief_date: date,
        selected_topics: List[TrendingTopic],
        auto_publish: bool = True,
        include_underreported: bool = True
    ) -> DailyBrief:
        """
        Generate complete daily brief from selected topics.

        Args:
            brief_date: Date of the brief
            selected_topics: List of TrendingTopic instances (pre-selected)
            auto_publish: If True, set status to 'ready' (default True)
            include_underreported: If True, add "Under the Radar" bonus item (default True)

        Returns:
            DailyBrief instance (saved to database)
        """
        if not selected_topics:
            raise ValueError("Cannot generate brief with no topics")

        valid_topics = [t for t in selected_topics if t.id is not None]
        if len(valid_topics) < len(selected_topics):
            logger.warning(f"Filtered out {len(selected_topics) - len(valid_topics)} topics without database IDs")
        
        if not valid_topics:
            raise ValueError("No valid topics with database IDs")
        
        selected_topics = valid_topics

        logger.info(f"Generating brief for {brief_date} with {len(selected_topics)} topics")

        # Check if brief already exists with row-level locking to prevent race conditions
        try:
            existing = DailyBrief.query.filter_by(date=brief_date).with_for_update().first()
            if existing:
                if existing.status in ('ready', 'published'):
                    logger.info(f"Brief for {brief_date} already {existing.status}, skipping generation")
                    return existing
                logger.warning(f"Brief already exists for {brief_date} with status '{existing.status}', updating...")
                brief = existing
            else:
                brief = DailyBrief(
                    date=brief_date,
                    status='draft',
                    auto_selected=True
                )
                db.session.add(brief)
                db.session.flush()  # Get brief.id
        except Exception as e:
            # Handle race condition - another process may have created the brief
            db.session.rollback()
            existing = DailyBrief.query.filter_by(date=brief_date).first()
            if existing:
                logger.info(f"Brief for {brief_date} was created by another process, returning existing")
                return existing
            raise e

        # Generate brief-level content
        brief.title = self._generate_brief_title(selected_topics)
        brief.intro_text = self._generate_intro_text(selected_topics)

        # Generate main items
        items_created = 0
        for position, topic in enumerate(selected_topics, start=1):
            try:
                item = self._generate_brief_item(brief, topic, position)
                db.session.add(item)
                logger.info(f"Generated item {position}: {item.headline}")
                items_created += 1
            except Exception as e:
                logger.error(f"Failed to generate item for topic {topic.id}: {e}")
                # Continue with other items
                continue

        # Add underreported "Under the Radar" bonus item
        if include_underreported and items_created > 0:
            try:
                underreported_item = self._generate_underreported_item(brief, items_created + 1, selected_topics)
                if underreported_item:
                    db.session.add(underreported_item)
                    logger.info(f"Generated Under the Radar item: {underreported_item.headline}")
            except Exception as e:
                logger.warning(f"Failed to generate underreported item: {e}")
                # Non-critical - continue without it

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
        if topic.id is None:
            raise ValueError(f"Topic has no ID (not persisted to database): '{topic.title}'")
        if brief.id is None:
            raise ValueError(f"Brief has no ID (not persisted to database)")
        
        # Get articles for this topic
        article_links = topic.articles.all() if hasattr(topic, 'articles') else []
        articles = [link.article for link in article_links if link.article]
        
        # Check for empty articles list
        if not articles:
            logger.warning(f"Topic '{topic.title}' has no articles - using fallback content")
            # Create minimal item with fallback content
            articles = []  # Continue with empty list, will use fallback

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

        # Generate blindspot explanation if needed
        blindspot_explanation = None
        if coverage_data['distribution']:
            left_pct = coverage_data['distribution'].get('left', 0)
            right_pct = coverage_data['distribution'].get('right', 0)

            # Check for blindspot (< 15% coverage from one side when other side has > 30%)
            if left_pct < 0.15 and right_pct > 0.30:
                logger.info(f"Detected left blindspot for topic {topic.id}, generating explanation...")
                blindspot_explanation = analyzer.analyze_coverage_gap('left')
            elif right_pct < 0.15 and left_pct > 0.30:
                logger.info(f"Detected right blindspot for topic {topic.id}, generating explanation...")
                blindspot_explanation = analyzer.analyze_coverage_gap('right')

        # Generate CTA text
        cta_text = self._generate_cta_text(topic)

        # Create item
        item = BriefItem(
            brief_id=brief.id,
            position=position,
            trending_topic_id=topic.id,
            headline=llm_content['headline'],
            summary_bullets=llm_content['bullets'],
            personal_impact=llm_content.get('personal_impact'),
            so_what=llm_content.get('so_what'),
            perspectives=llm_content.get('perspectives'),
            coverage_distribution=coverage_data['distribution'],
            coverage_imbalance=coverage_data['imbalance_score'],
            source_count=coverage_data['source_count'],
            sources_by_leaning=coverage_data['sources_by_leaning'],
            blindspot_explanation=blindspot_explanation,
            sensationalism_score=avg_sensationalism,
            sensationalism_label=analyzer.get_sensationalism_label(avg_sensationalism),
            verification_links=verification_links,
            discussion_id=topic.discussion_id,  # Link to discussion if topic was published
            cta_text=cta_text
        )

        return item

    def _generate_underreported_item(
        self,
        brief: DailyBrief,
        position: int,
        exclude_topics: List[TrendingTopic]
    ) -> Optional[BriefItem]:
        """
        Generate a special "Under the Radar" item for underreported stories.

        Args:
            brief: DailyBrief instance
            position: Position in brief (usually 6)
            exclude_topics: Topics already in the brief (to avoid duplicates)

        Returns:
            BriefItem instance or None if no underreported story found
        """
        from app.brief.underreported import UnderreportedDetector

        detector = UnderreportedDetector(lookback_days=7)
        stories = detector.find_underreported_stories(limit=10)

        # Exclude topics already in brief
        exclude_ids = {t.id for t in exclude_topics}
        available_stories = [s for s in stories if s['topic'].id not in exclude_ids]

        if not available_stories:
            logger.info("No underreported stories found for Under the Radar item")
            return None

        # Take the highest-scored underreported story
        story = available_stories[0]
        topic = story['topic']

        logger.info(f"Selected underreported topic: {topic.title} (civic={story['civic_score']:.2f}, sources={story['source_count']})")

        # Get articles for this topic
        article_links = topic.articles.all() if hasattr(topic, 'articles') else []
        articles = [link.article for link in article_links if link.article]

        if not articles:
            return None

        # Generate coverage data
        analyzer = CoverageAnalyzer(topic)
        coverage_data = analyzer.calculate_distribution()

        # Generate content via LLM (same as regular items)
        llm_content = self._generate_item_content(topic, articles)

        # Extract verification links
        verification_links = self._extract_verification_links(articles)

        # Calculate sensationalism
        sensationalism_scores = [a.sensationalism_score for a in articles if a.sensationalism_score is not None]
        avg_sensationalism = sum(sensationalism_scores) / len(sensationalism_scores) if sensationalism_scores else None

        # Generate blindspot explanation if applicable
        blindspot_explanation = None
        if coverage_data['distribution']:
            left_pct = coverage_data['distribution'].get('left', 0)
            right_pct = coverage_data['distribution'].get('right', 0)

            if left_pct < 0.15 and right_pct > 0.30:
                blindspot_explanation = analyzer.analyze_coverage_gap('left')
            elif right_pct < 0.15 and left_pct > 0.30:
                blindspot_explanation = analyzer.analyze_coverage_gap('right')

        # Create item with is_underreported flag
        item = BriefItem(
            brief_id=brief.id,
            position=position,
            trending_topic_id=topic.id,
            headline=llm_content['headline'],
            summary_bullets=llm_content['bullets'],
            personal_impact=llm_content.get('personal_impact'),
            so_what=llm_content.get('so_what'),
            perspectives=llm_content.get('perspectives'),
            coverage_distribution=coverage_data['distribution'],
            coverage_imbalance=coverage_data['imbalance_score'],
            source_count=coverage_data['source_count'],
            sources_by_leaning=coverage_data['sources_by_leaning'],
            blindspot_explanation=blindspot_explanation,
            sensationalism_score=avg_sensationalism,
            sensationalism_label=analyzer.get_sensationalism_label(avg_sensationalism),
            verification_links=verification_links,
            discussion_id=topic.discussion_id,
            cta_text=None,  # No CTA for underreported items
            is_underreported=True  # Mark as special "Under the Radar" item
        )

        return item

    def _validate_item_content(
        self,
        content: Dict[str, Any],
        topic_title: str
    ) -> Tuple[bool, List[str], int]:
        """
        Validate generated content using opposite LLM provider for peer review.

        Args:
            content: Generated content dict with headline, bullets, personal_impact, so_what
            topic_title: Topic title for context

        Returns:
            Tuple of (passes_validation, list_of_issues, quality_score_0_to_10)
        """
        # Use opposite provider for validation
        validation_provider = 'anthropic' if self.provider == 'openai' else 'openai'

        # Check if validation provider is available
        if validation_provider == 'openai':
            validation_key = os.environ.get('OPENAI_API_KEY')
        else:
            validation_key = os.environ.get('ANTHROPIC_API_KEY')

        if not validation_key:
            logger.info(f"Validation provider {validation_provider} not available - skipping multi-model validation")
            return (True, [], 7)  # Accept without validation, score 7/10

        critique_prompt = f"""You are a senior editor reviewing news briefing content for quality issues.

TOPIC: {topic_title}

GENERATED CONTENT:
Headline: {content.get('headline', 'N/A')}

Bullets:
{chr(10).join(f"- {b}" for b in content.get('bullets', []))}

Personal Impact: {content.get('personal_impact', 'N/A')}

So What: {content.get('so_what', 'N/A')}

Review this content and check for these quality problems:

1. VAGUE LANGUAGE: Uses words like "could", "might", "some people say", "appears to"
2. MISSING SPECIFICS: Lacks numbers, dates, named people/organizations, or concrete details
3. GENERIC IMPACT: Impact statements are generic ("will affect many people") rather than specific ("17 million Americans by March 2026")
4. SENSATIONAL FRAMING: Uses emotional language, exaggeration, or clickbait patterns
5. UNCLEAR REFERENCES: Uses "this", "it", "they" without clear antecedents
6. PASSIVE VOICE: Uses passive constructions that obscure responsibility
7. MISSING PERSONAL RELEVANCE: Personal impact statement doesn't explain direct relevance to readers

Respond ONLY with valid JSON:
{{
  "passes": true or false (true if quality_score >= 7),
  "quality_score": 0-10 (10 = excellent, specific, concrete; 0 = vague, generic, poor),
  "issues": ["Specific issue 1", "Specific issue 2", ...]
}}

Be strict but fair. If content is specific, concrete, and well-written, give credit."""

        try:
            # Call opposite LLM for validation
            if validation_provider == 'openai':
                response = self._call_openai(critique_prompt)
            else:
                response = self._call_anthropic(critique_prompt)

            data = extract_json(response)

            passes = data.get('passes', False)
            quality_score = data.get('quality_score', 0)
            issues = data.get('issues', [])

            logger.info(f"Content validation: passes={passes}, score={quality_score}, issues={len(issues)}")

            return (passes, issues, quality_score)

        except Exception as e:
            logger.warning(f"Content validation failed: {e}. Accepting content by default.")
            # If validation fails, accept the content (don't block on validation errors)
            return (True, [], 7)

    def _generate_item_content(
        self,
        topic: TrendingTopic,
        articles: List[NewsArticle]
    ) -> Dict[str, Any]:
        """
        Generate headline, bullets, and analysis using LLM.

        Returns:
            dict: {
                'headline': str (10 words max),
                'bullets': list of str (3-4 bullets),
                'so_what': str (why this matters),
                'perspectives': dict with 'left', 'center', 'right' viewpoints
            }
        """
        # Prepare article summaries for context
        article_context = []
        source_perspectives = {'left': [], 'center': [], 'right': []}
        
        for i, article in enumerate(articles[:8], start=1):  # Max 8 articles for richer context
            summary = article.summary[:300] if article.summary else article.title
            source_name = article.source.name if article.source else 'Unknown'
            
            # Get political leaning from source (-2 to +2 scale)
            leaning_score = article.source.political_leaning if article.source and article.source.political_leaning is not None else 0
            
            article_context.append(f"{i}. [{source_name}] {article.title}\n   {summary}")
            
            # Collect perspectives by leaning score
            if leaning_score <= -1:  # Left or Lean Left
                source_perspectives['left'].append(f"{source_name}: {summary[:150]}")
            elif leaning_score >= 1:  # Right or Lean Right
                source_perspectives['right'].append(f"{source_name}: {summary[:150]}")
            else:  # Center
                source_perspectives['center'].append(f"{source_name}: {summary[:150]}")

        article_text = '\n'.join(article_context)

        prompt = f"""You are a senior news analyst creating a Tortoise Media-style briefing. Generate rich, analytical content from these articles about the same story.

ARTICLES:
{article_text}

Generate a comprehensive news item with:

1. HEADLINE: A concise, active headline (6-10 words maximum).
   - Use active voice, present tense
   - Include concrete noun + action verb
   - No questions, no clickbait, no metaphors
   - Be specific, not generic

   Examples:
   ✓ GOOD: "Treasury Plans £50bn Green Investment Fund"
   ✓ GOOD: "Meta Fined €1.2bn for Data Violations"
   ✗ BAD: "Government Faces Pressure on Climate Policy" (passive, vague)
   ✗ BAD: "Tech Companies Under Fire" (metaphor, unclear)

2. KEY POINTS: 3-4 bullet points covering the essential facts:
   - What happened (the core news with specific details)
   - Key figures, numbers, dates, or quotes (be concrete)
   - Important context or timeline (when does this take effect?)
   - What happens next (specific next steps if known)

   Each bullet must include at least one concrete detail (number, date, named person/organization).

3. PERSONAL IMPACT: One sentence (max 25 words) explaining direct personal relevance.
   - Must be specific and actionable
   - Target: ordinary citizens, not policy wonks
   - Include timeframe if relevant

   Examples:
   ✓ GOOD: "If you have student loans, this changes your repayment timeline by 6-18 months."
   ✓ GOOD: "Your local council will need to implement this by June 2026."
   ✓ GOOD: "Mortgage holders could see rates drop 0.25-0.5% within 3 months."
   ✗ BAD: "This could affect many people." (vague, no specifics)

4. SO WHAT: One paragraph (2-3 sentences) explaining concrete, real-world impact.
   - BE SPECIFIC: Include numbers, dates, affected groups, or measurable outcomes
   - Show second-order effects: "If this continues, watch for..."
   - Make it personal: "You'll notice this when..." or "This affects [group] by..."
   - Add historical context when relevant: "Last time this happened (year), the result was..."

   Examples:
   ✓ GOOD: "So what? 17 million Americans in red states will lose Medicaid expansion by March if governors don't reverse course. Last time federal funding changed (2017), 8 states took 2+ years to respond, leaving 3 million temporarily uninsured."
   ✗ BAD: "So what? This decision could impact healthcare access and affect millions of people across the country." (vague, no specifics)

   ✓ GOOD: "So what? If you have student loans, this changes your repayment timeline by 6-18 months depending on your balance. The new rules take effect in August 2026, with applications opening in June."
   ✗ BAD: "So what? This policy will have implications for people with student debt." (generic, no actionable info)

5. PERSPECTIVES: How different outlets are framing this story:
   - Left-leaning view (if available): One sentence summary
   - Centre view: One sentence summary
   - Right-leaning view (if available): One sentence summary

Guidelines:
- Use British English (analyse, centre, organisation)
- No em dashes. Use commas, colons, or periods instead
- Neutral, calm tone throughout
- Focus on facts and analysis, not opinion
- Avoid vague language (could, might, some say, appears to)
- Every claim should have a number, date, or named source
- Make the "So what?" genuinely insightful and concrete, not generic

Return JSON:
{{
  "headline": "...",
  "bullets": ["bullet 1", "bullet 2", "bullet 3", "bullet 4"],
  "personal_impact": "One sentence personal relevance (max 25 words)",
  "so_what": "So what? [Your specific, concrete analysis here]",
  "perspectives": {{
    "left": "Left-leaning outlets emphasise...",
    "center": "Centrist outlets focus on...",
    "right": "Right-leaning outlets highlight..."
  }}
}}"""

        # Try generation up to 2 times with validation
        max_attempts = 2
        last_data = None
        last_issues = []

        for attempt in range(1, max_attempts + 1):
            try:
                # Generate content
                response = self._call_llm(prompt)
                data = extract_json(response)

                # Basic validation
                if 'headline' not in data or 'bullets' not in data:
                    raise ValueError("Missing headline or bullets in LLM response")

                if not isinstance(data['bullets'], list) or len(data['bullets']) < 2:
                    raise ValueError("Bullets must be a list with at least 2 items")

                # Trim bullets to 4 max
                data['bullets'] = data['bullets'][:4]

                # Ensure optional fields exist
                if 'personal_impact' not in data:
                    data['personal_impact'] = None
                if 'so_what' not in data:
                    data['so_what'] = None
                if 'perspectives' not in data:
                    data['perspectives'] = None

                last_data = data

                # Multi-model validation
                passes, issues, quality_score = self._validate_item_content(data, topic.title)

                if passes:
                    logger.info(f"Content passed validation on attempt {attempt} with score {quality_score}")
                    return data
                else:
                    logger.warning(f"Content failed validation on attempt {attempt}. Score: {quality_score}, Issues: {issues}")
                    last_issues = issues

                    # If this is not the last attempt, regenerate with feedback
                    if attempt < max_attempts:
                        logger.info(f"Regenerating content with quality feedback...")
                        # Add issues to prompt for next iteration
                        prompt += f"\n\nPREVIOUS ATTEMPT HAD THESE ISSUES - PLEASE FIX:\n"
                        for issue in issues:
                            prompt += f"- {issue}\n"
                    else:
                        # Last attempt failed, but return it anyway (don't block on quality)
                        logger.warning(f"Using content despite validation failure after {max_attempts} attempts")
                        return data

            except Exception as e:
                logger.error(f"LLM content generation failed on attempt {attempt}: {e}")
                if attempt == max_attempts:
                    # All attempts failed, fall through to fallback
                    break

        # Fallback if all attempts failed
        logger.error("All generation attempts failed - using fallback content")
        return {
            'headline': topic.title[:100],  # Truncate if needed
            'bullets': [
                topic.description[:150] if topic.description else "Details unavailable",
                f"Covered by {len(articles)} sources",
                "See sources for full context"
            ],
            'personal_impact': None,
            'so_what': None,
            'perspectives': None
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
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
                logger.debug(f"Could not parse seed_statements for topic {topic.id}: {e}")

        # Fallback CTA
        return "Share your view on this topic"

    def _call_llm(self, prompt: str) -> str:
        """
        Call LLM API (OpenAI or Anthropic).

        Args:
            prompt: User prompt

        Returns:
            str: LLM response text
            
        Raises:
            ValueError: If no LLM provider is available
        """
        if not self.llm_available:
            raise ValueError("No LLM API key configured")
        
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
    
    This function is designed to be robust and not crash the scheduler:
    - Returns None if no topics available (not an error)
    - Catches and logs all exceptions
    - Provides detailed logging for debugging

    Args:
        brief_date: Date to generate for (default: today)
        auto_publish: Set to 'ready' status if True

    Returns:
        DailyBrief instance, or None if generation fails or no topics available
    """
    from app.brief.topic_selector import select_topics_for_date, TopicSelector

    if brief_date is None:
        brief_date = date.today()

    logger.info(f"Starting daily brief generation for {brief_date}")

    # Select topics with detailed logging
    try:
        topics = select_topics_for_date(brief_date, limit=5)
    except Exception as e:
        logger.error(f"Topic selection failed for {brief_date}: {e}", exc_info=True)
        return None

    if not topics:
        # Log diagnostic info to help debug why no topics
        try:
            from app.models import TrendingTopic
            from datetime import datetime, timedelta
            
            cutoff_24h = datetime.utcnow() - timedelta(hours=24)
            cutoff_48h = datetime.utcnow() - timedelta(hours=48)
            cutoff_72h = datetime.utcnow() - timedelta(hours=72)
            
            published_24h = TrendingTopic.query.filter(
                TrendingTopic.status == 'published',
                TrendingTopic.published_at >= cutoff_24h
            ).count()
            
            published_48h = TrendingTopic.query.filter(
                TrendingTopic.status == 'published',
                TrendingTopic.published_at >= cutoff_48h
            ).count()
            
            published_72h = TrendingTopic.query.filter(
                TrendingTopic.status == 'published',
                TrendingTopic.published_at >= cutoff_72h
            ).count()
            
            total_published = TrendingTopic.query.filter_by(status='published').count()
            
            logger.warning(
                f"No topics available for brief on {brief_date}. "
                f"Diagnostic: {published_24h} topics in 24h, {published_48h} in 48h, "
                f"{published_72h} in 72h, {total_published} total published. "
                f"Check if trending pipeline is running and publishing topics."
            )
        except Exception as diag_e:
            logger.warning(f"No topics available for brief on {brief_date} (diagnostic failed: {diag_e})")
        
        return None

    logger.info(f"Selected {len(topics)} topics for brief generation")

    # Validate selection
    try:
        selector = TopicSelector(brief_date)
        validation = selector.validate_selection(topics)
        if not validation['valid']:
            logger.warning(f"Topic selection has issues: {validation['issues']}")
        logger.info(f"Selection summary: {validation['summary']}")
    except Exception as val_e:
        logger.warning(f"Topic validation failed (continuing anyway): {val_e}")

    # Generate brief
    try:
        generator = BriefGenerator()
        brief = generator.generate_brief(brief_date, topics, auto_publish)
        logger.info(f"Brief generated successfully: {brief.title} ({brief.item_count} items)")
        return brief
    except Exception as e:
        logger.error(f"Brief generation failed for {brief_date}: {e}", exc_info=True)
        return None
