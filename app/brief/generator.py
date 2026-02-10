"""
Brief Generator

Generates daily briefs from selected topics using LLM.
Creates concise headlines, bullet summaries, and extracts verification links.

Supports two generation modes:
1. Legacy flat: generate_brief() — 3-5 items in a flat list (backward compatible)
2. Sectioned: generate_sectioned_brief() — items grouped by section at variable depth

The sectioned mode is the new default, invoked by generate_daily_brief().
"""

import os
import logging
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Any
from app.models import DailyBrief, BriefItem, TrendingTopic, NewsArticle, UpcomingEvent, db
from app.brief.coverage_analyzer import CoverageAnalyzer
from app.brief.sections import (
    SECTIONS, DEPTH_FULL, DEPTH_STANDARD, DEPTH_QUICK, DEPTH_CONFIG,
    get_section_for_category, get_topic_display_label,
)
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
            existing = DailyBrief.query.filter_by(date=brief_date, brief_type='daily').with_for_update().first()
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
            existing = DailyBrief.query.filter_by(date=brief_date, brief_type='daily').first()
            if existing:
                logger.info(f"Daily brief for {brief_date} was created by another process, returning existing")
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

        # Generate "Same Story, Different Lens" cross-perspective analysis
        # Shows how outlets across the political spectrum frame the same story differently
        try:
            from app.brief.lens_check import generate_lens_check
            lens_check_data = generate_lens_check(brief_date)
            if lens_check_data:
                brief.lens_check = lens_check_data
                logger.info(f"Generated lens check for topic: {lens_check_data.get('topic_title', 'unknown')[:50]}")
            else:
                logger.info("No story met lens check criteria - section will be omitted")
        except Exception as e:
            logger.warning(f"Failed to generate lens check: {e}")
            # Non-critical - continue without it

        # Set status
        brief.status = 'ready' if auto_publish else 'draft'
        brief.created_at = datetime.utcnow()

        db.session.commit()

        logger.info(f"Brief generated successfully: {brief.title} ({brief.item_count} items)")

        # Audio generation disabled - feature was deprecated as not worthwhile

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
        Generate an LLM-written editorial intro that previews what's in the brief.

        Falls back to a generic template if the LLM call fails.
        """
        count = len(topics)

        if not topics:
            return "Today's brief is being prepared. Check back shortly for the latest stories that matter."

        # Fallback intros (used if LLM unavailable or fails)
        fallback_intros = [
            f"Today's brief covers {count} stories that matter for sense-making. Not comprehensive news—just what's worth understanding today.",
            f"{count} stories from today's news, with context for sense-making. Coverage analysis and primary sources included.",
            f"Your evening brief: {count} stories worth understanding. We show which outlets covered each story and link to primary sources.",
            f"{count} topics from today, selected for civic importance and coverage across perspectives. This isn't all the news—it's what matters."
        ]

        if not self.llm_available:
            import random
            random.seed(datetime.now().day)
            return random.choice(fallback_intros)

        # Build headline list for the LLM
        headlines = []
        for topic in topics[:8]:  # Cap to avoid overly long prompts
            headlines.append(f"- {topic.title[:100]}")
        headline_text = "\n".join(headlines)

        prompt = f"""Write a brief editorial introduction (2-3 sentences, max 60 words) for today's news brief.

The brief covers {count} stories:
{headline_text}

Guidelines:
- British English, calm and authoritative tone
- Reference 1-2 specific themes or stories by name to give a preview
- End with a phrase that frames why these stories matter together
- Do NOT use clickbait, exclamation marks, or hype
- Do NOT start with "Today's brief covers..." — be more editorial
- Write in second person ("you") sparingly

Return ONLY the intro text, no JSON, no quotes, no label."""

        try:
            response = self._call_llm(prompt)
            intro = response.strip().strip('"').strip("'")
            # Basic validation: must be reasonable length and not empty
            if intro and 20 < len(intro) < 500:
                return intro
            else:
                logger.warning(f"LLM intro text too short/long ({len(intro)} chars), using fallback")
        except Exception as e:
            logger.warning(f"Failed to generate LLM intro text: {e}")

        # Fallback
        import random
        random.seed(datetime.now().day)
        return random.choice(fallback_intros)

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

        # Generate deeper context (for "Want more detail?" feature)
        deeper_context = self._generate_deeper_context(topic, articles, llm_content)

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
            deeper_context=deeper_context,
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

        # Enrich with market signal (optional, failures are silent)
        try:
            from app.polymarket.matcher import market_matcher
            market_signal = market_matcher.get_market_signal_for_topic(topic.id)
            if market_signal:
                item.market_signal = market_signal
        except Exception as e:
            logger.warning(f"Market signal enrichment failed for topic {topic.id}: {e}")
            # Continue without market signal - brief generation succeeds

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

        # Generate deeper context
        deeper_context = self._generate_deeper_context(topic, articles, llm_content)

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
            deeper_context=deeper_context,
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

        # Get current year for date validation
        current_year = datetime.now().year
        
        critique_prompt = f"""You are a senior editor reviewing news briefing content for quality issues.

TODAY'S DATE: {datetime.now().strftime('%d %B %Y')}
CURRENT YEAR: {current_year}

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
7. MISSING PERSONAL RELEVANCE: Personal impact only addresses local/obvious impacts without explaining global/macro relevance. For international stories, MUST include why it matters to people worldwide (energy prices, markets, geopolitics, supply chains, etc.)
8. DATE ERRORS: Any dates that seem wrong for current news (e.g., mentioning 2024 or 2025 when we're in {current_year}). Flag references to past years unless clearly referring to historical context.

Respond ONLY with valid JSON:
{{
  "passes": true or false (true if quality_score >= 7),
  "quality_score": 0-10 (10 = excellent, specific, concrete; 0 = vague, generic, poor),
  "issues": ["Specific issue 1", "Specific issue 2", ...]
}}

Be strict but fair. If content is specific, concrete, and well-written, give credit."""

        try:
            # Call opposite LLM for validation with explicit key
            if validation_provider == 'openai':
                response = self._call_openai(critique_prompt, api_key=validation_key)
            else:
                response = self._call_anthropic(critique_prompt, api_key=validation_key)

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
        # Get current date for context (prevents date hallucination)
        current_date = datetime.now()
        current_year = current_date.year
        date_context = current_date.strftime('%d %B %Y')
        
        # Prepare article summaries for context
        article_context = []
        source_perspectives = {'left': [], 'center': [], 'right': []}
        
        for i, article in enumerate(articles[:8], start=1):  # Max 8 articles for richer context
            summary = article.summary[:300] if article.summary else article.title
            source_name = article.source.name if article.source else 'Unknown'
            
            # Include article publication date if available
            pub_date = ""
            if article.published_at:
                pub_date = f" ({article.published_at.strftime('%d %b %Y')})"
            
            # Get political leaning from source (-2 to +2 scale)
            leaning_score = article.source.political_leaning if article.source and article.source.political_leaning is not None else 0
            
            article_context.append(f"{i}. [{source_name}]{pub_date} {article.title}\n   {summary}")
            
            # Collect perspectives by leaning score
            if leaning_score <= -1:  # Left or Lean Left
                source_perspectives['left'].append(f"{source_name}: {summary[:150]}")
            elif leaning_score >= 1:  # Right or Lean Right
                source_perspectives['right'].append(f"{source_name}: {summary[:150]}")
            else:  # Center
                source_perspectives['center'].append(f"{source_name}: {summary[:150]}")

        article_text = '\n'.join(article_context)

        prompt = f"""You are a senior news analyst creating a Tortoise Media-style briefing. Generate rich, analytical content from these articles about the same story.

TODAY'S DATE: {date_context}
CURRENT YEAR: {current_year}

CRITICAL DATE RULES:
- We are in {current_year}. Any reference to years MUST be accurate.
- Only use dates, statistics, and figures that appear in the source articles.
- NEVER invent or hallucinate dates, percentages, or numbers.
- If an article mentions a survey or statistic, use the date from that article.
- When in doubt, say "according to recent data" rather than inventing a year.

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

3. PERSONAL IMPACT: Two-part explanation of why this matters (2 sentences max, 50 words total).
   
   Our audience is GLOBAL (English-speaking worldwide), so always provide BOTH:
   
   a) MICRO/LOCAL: Direct impact on those in the affected region (if applicable)
   b) MACRO/GLOBAL: Why this matters to everyone else, globally
   
   For international stories, the global angle is MORE important than the local one.
   Think: energy prices, supply chains, geopolitical stability, economic ripples, 
   precedent-setting, refugee flows, trade impacts, market effects, security implications.
   
   Examples:
   ✓ GOOD (Ukraine story): "For Ukrainians: 1.5 million face weeks without heating. Globally: this escalation could push European gas prices up 10-15% and tests NATO's resolve heading into winter."
   ✓ GOOD (China-Taiwan): "For Taiwan: increased military presence disrupts shipping. For everyone: 60% of global semiconductors transit this strait, so expect tech supply chain jitters."
   ✓ GOOD (UK policy): "For UK residents: council tax bills may rise £200/year. Internationally: this signals how wealthy nations are funding climate transition costs."
   ✓ GOOD (US Fed decision): "If you hold dollar assets or have a mortgage, expect rate impacts within 3 months. Emerging markets will feel capital flow pressure."
   ✗ BAD: "Residents in affected areas may face disruptions." (obvious, no global context)
   ✗ BAD: "This could affect many people." (vague, no specifics)

4. SO WHAT (Why It Matters): One paragraph (2-3 sentences) explaining concrete, real-world impact.
   - Do NOT start with "So what?" - the section is already labeled "Why It Matters". Write the analysis directly.
   - BE SPECIFIC: Include numbers, dates, affected groups, or measurable outcomes
   - Show second-order effects: "If this continues, watch for..."
   - Make it personal: "You'll notice this when..." or "This affects [group] by..."
   - Add historical context when relevant: "Last time this happened (year), the result was..."

   Examples:
   ✓ GOOD: "17 million Americans in red states will lose Medicaid expansion by March if governors don't reverse course. Last time federal funding changed (2017), 8 states took 2+ years to respond, leaving 3 million temporarily uninsured."
   ✗ BAD: "This decision could impact healthcare access and affect millions of people across the country." (vague, no specifics)

   ✓ GOOD: "If you have student loans, this changes your repayment timeline by 6-18 months depending on your balance. The new rules take effect in August 2026, with applications opening in June."
   ✗ BAD: "This policy will have implications for people with student debt." (generic, no actionable info)

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
- Make the "Why it matters" analysis genuinely insightful and concrete, not generic

Return JSON:
{{
  "headline": "...",
  "bullets": ["bullet 1", "bullet 2", "bullet 3", "bullet 4"],
  "personal_impact": "One sentence personal relevance (max 25 words)",
  "so_what": "[Your specific, concrete analysis - do not start with 'So what?']",
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

    def _generate_deeper_context(
        self,
        topic: TrendingTopic,
        articles: List[NewsArticle],
        existing_content: Dict[str, Any]
    ) -> Optional[str]:
        """
        Generate deeper context for "Want more detail?" feature.
        
        Provides extended background, historical context, and deeper analysis
        that goes beyond the summary bullets.
        
        Returns:
            str: Extended context text, or None if generation fails
        """
        if not self.llm_available:
            return None
        
        try:
            # Get current date for context
            current_date = datetime.now()
            current_year = current_date.year
            date_context = current_date.strftime('%d %B %Y')
            
            # Prepare article summaries (use more articles for deeper context)
            article_context = []
            for i, article in enumerate(articles[:12], start=1):  # More articles for context
                summary = article.summary[:400] if article.summary else article.title
                source_name = article.source.name if article.source else 'Unknown'
                pub_date = f" ({article.published_at.strftime('%d %b %Y')})" if article.published_at else ""
                article_context.append(f"{i}. [{source_name}]{pub_date} {article.title}\n   {summary}")
            
            article_text = '\n'.join(article_context)
            
            prompt = f"""You are a senior news analyst providing deeper context for a news story.

TODAY'S DATE: {date_context}
CURRENT YEAR: {current_year}

TOPIC: {topic.title}

EXISTING SUMMARY:
Headline: {existing_content.get('headline', 'N/A')}
Key Points: {chr(10).join(f"- {b}" for b in existing_content.get('bullets', []))}
So What: {existing_content.get('so_what', 'N/A')}

ARTICLES:
{article_text}

Generate a deeper dive (3-4 paragraphs) that provides:

1. HISTORICAL CONTEXT: What led to this moment? What similar events happened before?
2. BROADER IMPLICATIONS: What does this mean for related issues, sectors, or regions?
3. KEY PLAYERS: Who are the main actors, organizations, or institutions involved?
4. WHAT TO WATCH: What developments should readers monitor in the coming days/weeks?

Guidelines:
- Use British English (analyse, centre, organisation)
- Be specific with numbers, dates, and names
- Provide genuine insight, not just restate the summary
- Connect this story to larger trends or patterns
- Keep tone calm and analytical
- Avoid speculation - stick to what's known from sources

Return ONLY the deeper context text (no JSON, no labels, just the prose)."""

            response = self._call_llm(prompt)
            
            # Clean up response (remove JSON markers if present)
            context = response.strip()
            if context.startswith('{') or context.startswith('"'):
                # Try to extract text from JSON
                try:
                    import json
                    data = json.loads(context)
                    if isinstance(data, dict):
                        context = data.get('deeper_context') or data.get('context') or data.get('text', context)
                    elif isinstance(data, str):
                        context = data
                except:
                    pass
            
            # Limit length (roughly 800-1200 words)
            if len(context) > 2000:
                # Truncate at sentence boundary
                truncated = context[:2000]
                last_period = truncated.rfind('.')
                if last_period > 1500:  # Only truncate if we have a reasonable sentence
                    context = truncated[:last_period + 1]
                else:
                    context = truncated + "..."
            
            return context if context else None
            
        except Exception as e:
            logger.warning(f"Failed to generate deeper context for topic {topic.id}: {e}")
            return None

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
        seen_urls = set()  # Track URLs to prevent duplicates
        seen_sources = set()  # Track source names to prevent same source appearing twice

        for article in articles[:6]:  # Check more articles but dedupe
            # Skip articles without URLs
            if not article.url:
                continue
            
            # Skip if we've already seen this URL
            if article.url in seen_urls:
                continue
            
            # Skip if we've already included this source (one article per source)
            # Allow multiple 'Unknown' sources only if we have fewer than 3 links
            source_name = article.source.name if article.source else None
            if source_name and source_name in seen_sources:
                continue
            
            # Only add up to 3 unique source articles
            if len(links) >= 3:
                break
            
            # Check if likely paywalled
            is_paywalled = any(domain in article.url for domain in [
                'ft.com', 'economist.com', 'wsj.com', 'nytimes.com',
                'telegraph.co.uk', 'thetimes.co.uk'
            ])

            links.append({
                'tier': 'reporting',
                'url': article.url,
                'type': 'news_article',
                'description': f"{source_name} coverage" if source_name else "News coverage",
                'is_paywalled': is_paywalled
            })
            
            seen_urls.add(article.url)
            if source_name:  # Only track named sources
                seen_sources.add(source_name)

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

    # =========================================================================
    # SECTIONED BRIEF GENERATION (New)
    # =========================================================================

    def generate_sectioned_brief(
        self,
        brief_date: date,
        topics_by_section: Dict[str, List[Tuple[TrendingTopic, str]]],
        auto_publish: bool = True
    ) -> DailyBrief:
        """
        Generate a sectioned daily brief with variable depth content.

        This is the new generation path. Topics are pre-selected by section
        with assigned depth levels from the TopicSelector.

        Args:
            brief_date: Date of the brief
            topics_by_section: Dict from TopicSelector.select_topics_by_section()
            auto_publish: If True, set status to 'ready'

        Returns:
            DailyBrief instance (saved to database)
        """
        if not topics_by_section:
            raise ValueError("Cannot generate brief with no topics")

        logger.info(f"Generating sectioned brief for {brief_date}")

        # Check/create brief record (same idempotency as legacy)
        try:
            existing = DailyBrief.query.filter_by(date=brief_date, brief_type='daily').with_for_update().first()
            if existing:
                if existing.status in ('ready', 'published'):
                    logger.info(f"Brief for {brief_date} already {existing.status}, skipping")
                    return existing
                logger.warning(f"Brief exists for {brief_date} with status '{existing.status}', updating...")
                brief = existing
                # Clear old items for regeneration
                BriefItem.query.filter_by(brief_id=existing.id).delete()
                db.session.flush()
            else:
                brief = DailyBrief(
                    date=brief_date,
                    brief_type='daily',
                    status='draft',
                    auto_selected=True
                )
                db.session.add(brief)
                db.session.flush()
        except Exception as e:
            db.session.rollback()
            existing = DailyBrief.query.filter_by(date=brief_date, brief_type='daily').first()
            if existing:
                return existing
            raise e

        # Collect all topics for title generation
        all_topics = []
        for section_items in topics_by_section.values():
            all_topics.extend([t for t, _ in section_items])

        brief.title = self._generate_brief_title(all_topics)
        brief.intro_text = self._generate_intro_text(all_topics)

        # Generate items section by section
        position = 1
        items_created = 0

        for section_key, topic_depth_list in topics_by_section.items():
            for topic, depth in topic_depth_list:
                try:
                    item = self._generate_sectioned_item(
                        brief, topic, position, section_key, depth
                    )
                    db.session.add(item)
                    position += 1
                    items_created += 1
                    logger.info(
                        f"Generated [{section_key}/{depth}] item {position-1}: {item.headline}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to generate {section_key} item for topic {topic.id}: {e}"
                    )
                    continue

        # Add underreported "Under the Radar" bonus item
        if items_created > 0:
            try:
                exclude_topics = all_topics
                underreported_item = self._generate_underreported_item(brief, position, exclude_topics)
                if underreported_item:
                    underreported_item.section = 'underreported'
                    underreported_item.depth = DEPTH_STANDARD
                    db.session.add(underreported_item)
                    position += 1
                    logger.info(f"Generated Under the Radar item: {underreported_item.headline}")
            except Exception as e:
                logger.warning(f"Failed to generate underreported item: {e}")

        # Generate "Same Story, Different Lens"
        try:
            from app.brief.lens_check import generate_lens_check
            lens_check_data = generate_lens_check(brief_date)
            if lens_check_data:
                brief.lens_check = lens_check_data
                logger.info(f"Generated lens check for topic: {lens_check_data.get('topic_title', 'unknown')[:50]}")
        except Exception as e:
            logger.warning(f"Failed to generate lens check: {e}")

        # Generate "The Week Ahead" section
        try:
            week_ahead_data = self._generate_week_ahead(brief_date)
            if week_ahead_data:
                brief.week_ahead = week_ahead_data
                logger.info(f"Generated Week Ahead with {len(week_ahead_data)} events")
        except Exception as e:
            logger.warning(f"Failed to generate Week Ahead: {e}")

        # Generate "Market Pulse" section
        try:
            market_pulse_data = self._generate_market_pulse(all_topics)
            if market_pulse_data:
                brief.market_pulse = market_pulse_data
                logger.info(f"Generated Market Pulse with {len(market_pulse_data)} markets")
        except Exception as e:
            logger.warning(f"Failed to generate Market Pulse: {e}")

        # Finalize
        brief.status = 'ready' if auto_publish else 'draft'
        brief.created_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"Sectioned brief generated: {brief.title} ({items_created} items)")
        return brief

    def _generate_sectioned_item(
        self,
        brief: DailyBrief,
        topic: TrendingTopic,
        position: int,
        section: str,
        depth: str
    ) -> BriefItem:
        """
        Generate a brief item at the specified depth level.

        - full: headline, 4 bullets, personal impact, so what, perspectives,
                deeper context, verification links, blindspot, coverage bar
        - standard: headline, 2 bullets, so what, coverage bar, verification links
        - quick: headline + one-sentence summary only

        Args:
            brief: Parent DailyBrief
            topic: TrendingTopic to generate from
            position: Overall position in brief
            section: Section key (lead, politics, economy, etc.)
            depth: Depth level (full, standard, quick)

        Returns:
            BriefItem instance (not yet saved)
        """
        depth_config = DEPTH_CONFIG.get(depth, DEPTH_CONFIG[DEPTH_FULL])

        # Get articles
        article_links = topic.articles.all() if hasattr(topic, 'articles') else []
        articles = [link.article for link in article_links if link.article]

        # Coverage analysis (needed at all depths for data)
        analyzer = CoverageAnalyzer(topic)
        coverage_data = analyzer.calculate_distribution()

        # Generate content based on depth
        if depth == DEPTH_QUICK:
            llm_content = self._generate_quick_content(topic, articles)
        elif depth == DEPTH_STANDARD:
            llm_content = self._generate_standard_content(topic, articles)
        else:
            llm_content = self._generate_item_content(topic, articles)

        # Deeper context (full depth only)
        deeper_context = None
        if depth_config.get('deeper_context') and depth == DEPTH_FULL:
            deeper_context = self._generate_deeper_context(topic, articles, llm_content)

        # Verification links (full and standard)
        verification_links = None
        if depth_config.get('verification_links'):
            verification_links = self._extract_verification_links(articles)

        # Sensationalism
        sensationalism_scores = [a.sensationalism_score for a in articles if a.sensationalism_score is not None]
        avg_sensationalism = sum(sensationalism_scores) / len(sensationalism_scores) if sensationalism_scores else None

        # Blindspot (full depth only)
        blindspot_explanation = None
        if depth_config.get('blindspot') and coverage_data['distribution']:
            left_pct = coverage_data['distribution'].get('left', 0)
            right_pct = coverage_data['distribution'].get('right', 0)
            if left_pct < 0.15 and right_pct > 0.30:
                blindspot_explanation = analyzer.analyze_coverage_gap('left')
            elif right_pct < 0.15 and left_pct > 0.30:
                blindspot_explanation = analyzer.analyze_coverage_gap('right')

        # CTA (full depth only)
        cta_text = self._generate_cta_text(topic) if depth_config.get('discussion_cta') else None

        item = BriefItem(
            brief_id=brief.id,
            position=position,
            section=section,
            depth=depth,
            trending_topic_id=topic.id,
            headline=llm_content.get('headline', topic.title[:100]),
            quick_summary=llm_content.get('quick_summary'),
            summary_bullets=llm_content.get('bullets'),
            personal_impact=llm_content.get('personal_impact'),
            so_what=llm_content.get('so_what'),
            perspectives=llm_content.get('perspectives'),
            deeper_context=deeper_context,
            coverage_distribution=coverage_data['distribution'] if depth_config.get('coverage_bar') else None,
            coverage_imbalance=coverage_data['imbalance_score'] if depth_config.get('coverage_bar') else None,
            source_count=coverage_data['source_count'],
            sources_by_leaning=coverage_data['sources_by_leaning'] if depth_config.get('coverage_bar') else None,
            blindspot_explanation=blindspot_explanation,
            sensationalism_score=avg_sensationalism,
            sensationalism_label=analyzer.get_sensationalism_label(avg_sensationalism),
            verification_links=verification_links,
            discussion_id=topic.discussion_id,
            cta_text=cta_text,
        )

        # Polymarket signal on individual items (full depth only)
        if depth == DEPTH_FULL:
            try:
                from app.polymarket.matcher import market_matcher
                market_signal = market_matcher.get_market_signal_for_topic(topic.id)
                if market_signal:
                    item.market_signal = market_signal
                    logger.info(f"Attached market signal to topic {topic.id}")
            except Exception as e:
                logger.warning(f"Market signal enrichment failed for topic {topic.id}: {e}")

        return item

    def _generate_quick_content(
        self,
        topic: TrendingTopic,
        articles: List[NewsArticle]
    ) -> Dict[str, Any]:
        """
        Generate minimal content for quick-depth items (global roundup).

        Returns headline + one-sentence summary. Minimal LLM cost.
        """
        if not self.llm_available:
            return {
                'headline': topic.title[:100],
                'quick_summary': topic.description[:200] if topic.description else None,
            }

        # Build minimal context
        article_context = []
        for article in articles[:3]:
            summary = article.summary[:200] if article.summary else article.title
            source_name = article.source.name if article.source else 'Unknown'
            article_context.append(f"[{source_name}] {article.title}: {summary}")

        article_text = '\n'.join(article_context) if article_context else topic.title

        prompt = f"""Write a concise news headline and one-sentence summary.

TOPIC: {topic.title}
ARTICLES:
{article_text}

Return JSON:
{{
  "headline": "Active, specific headline (6-10 words)",
  "quick_summary": "One sentence (max 25 words) with a concrete detail"
}}

Guidelines: British English, neutral tone, no clickbait, include at least one specific detail."""

        try:
            response = self._call_llm(prompt)
            data = extract_json(response)
            return {
                'headline': data.get('headline', topic.title[:100]),
                'quick_summary': data.get('quick_summary'),
            }
        except Exception as e:
            logger.warning(f"Quick content generation failed for topic {topic.id}: {e}")
            return {
                'headline': topic.title[:100],
                'quick_summary': topic.description[:200] if topic.description else None,
            }

    def _generate_standard_content(
        self,
        topic: TrendingTopic,
        articles: List[NewsArticle]
    ) -> Dict[str, Any]:
        """
        Generate standard-depth content (themed section items).

        Returns headline, 2 bullets, and so-what analysis. No perspectives
        or personal impact (saves LLM tokens).
        """
        if not self.llm_available:
            return {
                'headline': topic.title[:100],
                'bullets': [
                    topic.description[:150] if topic.description else "Details unavailable",
                    f"Covered by {len(articles)} sources",
                ],
                'so_what': None,
            }

        # Prepare context (fewer articles than full depth)
        current_date = datetime.now()
        article_context = []
        for article in articles[:5]:
            summary = article.summary[:250] if article.summary else article.title
            source_name = article.source.name if article.source else 'Unknown'
            article_context.append(f"[{source_name}] {article.title}\n   {summary}")

        article_text = '\n'.join(article_context)

        prompt = f"""Generate a news briefing item with headline, 2 key points, and analysis.

TODAY'S DATE: {current_date.strftime('%d %B %Y')}

ARTICLES:
{article_text}

Return JSON:
{{
  "headline": "Active, specific headline (6-10 words)",
  "bullets": ["Key fact with concrete detail", "Second key point with specific data"],
  "so_what": "2 sentences: why this matters, with specific impact"
}}

Guidelines:
- British English, neutral tone
- No clickbait, vague language, or em dashes
- Every claim needs a number, date, or named source
- So-what should be concrete and actionable"""

        try:
            response = self._call_llm(prompt)
            data = extract_json(response)

            if 'headline' not in data or 'bullets' not in data:
                raise ValueError("Missing headline or bullets")

            data['bullets'] = data['bullets'][:2]  # Cap at 2

            return {
                'headline': data.get('headline', topic.title[:100]),
                'bullets': data.get('bullets', []),
                'so_what': data.get('so_what'),
            }
        except Exception as e:
            logger.warning(f"Standard content generation failed for topic {topic.id}: {e}")
            return {
                'headline': topic.title[:100],
                'bullets': [
                    topic.description[:150] if topic.description else "Details unavailable",
                    f"Covered by {len(articles)} sources",
                ],
                'so_what': None,
            }

    def _generate_week_ahead(self, brief_date: date) -> Optional[List[Dict]]:
        """
        Generate "The Week Ahead" section from UpcomingEvent records.

        Pulls events from the database for the next 7 days and formats them
        for the brief. If no events exist, returns None (section omitted).

        Returns:
            List of event dicts, or None if no events
        """
        try:
            events = UpcomingEvent.get_upcoming(days_ahead=7, limit=5)

            if not events:
                logger.info("No upcoming events found for Week Ahead section")
                return None

            week_ahead = []
            for event in events:
                week_ahead.append({
                    'title': event.title,
                    'date': event.event_date.strftime('%A, %d %B'),
                    'date_iso': event.event_date.isoformat(),
                    'description': event.description,
                    'category': event.category,
                    'region': event.region,
                    'importance': event.importance,
                    'source_url': event.source_url,
                })

                # Mark as used
                event.status = 'used'

            return week_ahead

        except Exception as e:
            logger.warning(f"Week Ahead generation failed: {e}")
            return None

    def _generate_market_pulse(
        self,
        topics: List[TrendingTopic],
        max_markets: int = 3
    ) -> Optional[List[Dict]]:
        """
        Generate "Market Pulse" section with prediction market data.

        Strategy:
        1. Try to match markets to today's topics (lower threshold)
        2. Fall back to trending/interesting markets if no matches

        Returns:
            List of market signal dicts, or None
        """
        try:
            from app.polymarket.matcher import market_matcher
            from app.models import PolymarketMarket

            signals = []
            seen_market_ids = set()

            # Strategy 1: Match to today's topics (with lower threshold)
            for topic in topics[:8]:
                if len(signals) >= max_markets:
                    break

                market = market_matcher.get_best_match_for_topic(topic.id)
                if market and market.id not in seen_market_ids:
                    signal = market.to_signal_dict()
                    signal['matched_topic'] = topic.title[:80]
                    signals.append(signal)
                    seen_market_ids.add(market.id)
                    logger.info(f"Market Pulse: matched market '{market.question[:50]}' to topic '{topic.title[:40]}'")

            # Strategy 2: Fall back to trending markets (high volume, recent movement)
            if len(signals) < max_markets:
                trending_markets = PolymarketMarket.query.filter(
                    PolymarketMarket.is_active == True,
                    PolymarketMarket.volume_24h >= 5000,  # Meaningful volume
                    PolymarketMarket.id.notin_(seen_market_ids) if seen_market_ids else True
                ).order_by(
                    PolymarketMarket.volume_24h.desc()
                ).limit(max_markets - len(signals)).all()

                for market in trending_markets:
                    # Only include markets with interesting movement
                    if market.change_24h and abs(market.change_24h) >= 0.02:  # 2%+ movement
                        signal = market.to_signal_dict()
                        signal['matched_topic'] = None  # Not matched to a specific topic
                        signals.append(signal)
                        seen_market_ids.add(market.id)
                        logger.info(f"Market Pulse (trending): '{market.question[:50]}' (vol=${market.volume_24h:,.0f})")

            if not signals:
                logger.info("No market signals found for Market Pulse section")
                return None

            return signals

        except Exception as e:
            logger.warning(f"Market Pulse generation failed: {e}")
            return None

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

    def _call_openai(self, prompt: str, api_key: Optional[str] = None) -> str:
        """Call OpenAI API"""
        import openai

        # Use provided key or fall back to self.api_key, then environment
        key = api_key or self.api_key or os.environ.get('OPENAI_API_KEY')
        client = openai.OpenAI(api_key=key)

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

    def _call_anthropic(self, prompt: str, api_key: Optional[str] = None) -> str:
        """Call Anthropic API"""
        import anthropic

        # Use provided key or fall back to self.api_key, then environment
        key = api_key or self.api_key or os.environ.get('ANTHROPIC_API_KEY')
        client = anthropic.Anthropic(api_key=key)

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
    Generate today's daily brief using the sectioned format.

    Uses section-based topic selection (lead, politics, economy, society, science,
    global roundup) with variable depth content generation. Falls back to legacy
    flat mode if sectioned selection produces no results.

    This function is designed to be robust and not crash the scheduler:
    - Returns None if no topics available (not an error)
    - Catches and logs all exceptions
    - Provides detailed logging for debugging
    - Falls back to legacy mode gracefully

    Args:
        brief_date: Date to generate for (default: today)
        auto_publish: Set to 'ready' status if True

    Returns:
        DailyBrief instance, or None if generation fails or no topics available
    """
    from app.brief.topic_selector import (
        select_topics_for_date, select_sectioned_topics_for_date, TopicSelector
    )

    if brief_date is None:
        brief_date = date.today()

    logger.info(f"Starting daily brief generation for {brief_date}")

    # Try sectioned selection first (new mode)
    try:
        topics_by_section = select_sectioned_topics_for_date(brief_date)
    except Exception as e:
        logger.error(f"Sectioned topic selection failed for {brief_date}: {e}", exc_info=True)
        topics_by_section = {}

    if topics_by_section:
        total_topics = sum(len(items) for items in topics_by_section.values())
        sections = list(topics_by_section.keys())
        logger.info(f"Sectioned selection: {total_topics} topics across {sections}")

        # Generate sectioned brief
        try:
            generator = BriefGenerator()
            brief = generator.generate_sectioned_brief(brief_date, topics_by_section, auto_publish)
            logger.info(f"Sectioned brief generated: {brief.title} ({brief.item_count} items)")
            return brief
        except Exception as e:
            logger.error(f"Sectioned brief generation failed: {e}", exc_info=True)
            logger.info("Falling back to legacy flat brief generation...")

    # Fallback to legacy flat mode
    logger.info("Using legacy flat topic selection")
    try:
        topics = select_topics_for_date(brief_date, limit=5)
    except Exception as e:
        logger.error(f"Legacy topic selection failed for {brief_date}: {e}", exc_info=True)
        return None

    if not topics:
        # Log diagnostic info
        _log_topic_diagnostic(brief_date)
        return None

    logger.info(f"Selected {len(topics)} topics for legacy brief generation")

    # Validate selection
    try:
        selector = TopicSelector(brief_date)
        validation = selector.validate_selection(topics)
        if not validation['valid']:
            logger.warning(f"Topic selection has issues: {validation['issues']}")
        logger.info(f"Selection summary: {validation['summary']}")
    except Exception as val_e:
        logger.warning(f"Topic validation failed (continuing anyway): {val_e}")

    # Generate legacy brief
    try:
        generator = BriefGenerator()
        brief = generator.generate_brief(brief_date, topics, auto_publish)
        logger.info(f"Legacy brief generated: {brief.title} ({brief.item_count} items)")
        return brief
    except Exception as e:
        logger.error(f"Brief generation failed for {brief_date}: {e}", exc_info=True)
        return None


def _log_topic_diagnostic(brief_date: date):
    """Log diagnostic info when no topics are found."""
    try:
        from app.models import TrendingTopic

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
