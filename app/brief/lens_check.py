"""
Lens Check: Cross-Perspective Headline Comparison

This module generates the "Same Story, Different Lens" section of the Daily Brief,
showing how outlets across the political spectrum frame the same news story differently.

METHODOLOGY (v1.0)
==================

1. STORY SELECTION
   - Find trending topics from last 24h with coverage across left/centre/right
   - Require minimum 2 sources per perspective (6 total minimum)
   - Score by coverage balance (prefer even distribution)
   - Select the story with highest balance score
   - If no story meets criteria, skip this section (better than weak example)

2. PERSPECTIVE CLASSIFICATION
   - Uses AllSides-based political_leaning scores from NewsSource
   - Left: leaning <= -0.5
   - Centre: -0.5 < leaning < 0.5
   - Right: leaning >= 0.5
   
3. HEADLINE SELECTION
   - Analyze ALL headlines from each perspective
   - Select 2 most representative per perspective (not outliers)
   - Representative = closest to median framing of that perspective
   
4. FRAMING ANALYSIS (LLM)
   - Prompt designed for neutrality - asks for observations, not judgments
   - Focuses on: word choice, emphasis, what's highlighted, what's omitted
   - Does NOT use terms like "bias" or "slant" (loaded language)
   - Structured output for consistency
   
5. CONTRAST GENERATION
   - Summarizes the key difference between perspectives
   - States observations factually
   - Encourages reader to form own conclusions

6. OMISSION DETECTION
   - Identifies what NO outlet covered
   - Based on LLM analysis of collective blind spots
   - Optional - only included if genuinely insightful

TRANSPARENCY
============
- All selection criteria are logged
- Source counts are shown in output
- Methodology version is stored with each analysis
- Code is open source for review

LIMITATIONS
===========
- Political leaning scores are from AllSides.com - methodology documented at allsides.com/media-bias
- LLM analysis may reflect training data biases - we use neutral prompts to minimize
- Representative headline selection is heuristic, not perfect
- Some stories may not have clear left/right framing - these are skipped
"""

import os
import logging
import time
import threading
from datetime import datetime, timedelta, date, timezone
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from collections import defaultdict
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed

from app import db
from app.models import TrendingTopic, NewsArticle, NewsSource, TrendingTopicArticle
from app.trending.scorer import extract_json, get_system_api_key

logger = logging.getLogger(__name__)

# Methodology version - increment when algorithm changes significantly
METHODOLOGY_VERSION = "1.0"

# Perspective thresholds based on political_leaning score (-2 to +2)
LEFT_THRESHOLD = -0.5
RIGHT_THRESHOLD = 0.5

# Minimum sources required per perspective
MIN_SOURCES_PER_PERSPECTIVE = 2

# Number of headlines to display per perspective
HEADLINES_TO_DISPLAY = 2


def retry_on_api_error(max_retries=3, backoff_factor=2):
    """
    Decorator to retry LLM API calls with exponential backoff.

    Retries on rate limits, timeouts, and transient server errors.
    Non-retryable errors (e.g., authentication, invalid requests) fail immediately.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        # Last attempt failed - raise the error
                        raise

                    # Check if it's a retryable error
                    error_str = str(e).lower()
                    retryable = any(term in error_str for term in [
                        'rate limit', 'timeout', 'connection', 'overloaded',
                        'internal server error', '429', '500', '502', '503', '504'
                    ])

                    if not retryable:
                        # Non-retryable error (auth, validation, etc.) - fail immediately
                        raise

                    wait_time = backoff_factor ** attempt
                    logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)

            return None
        return wrapper
    return decorator


def track_performance(func):
    """Decorator to log execution time for performance monitoring."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"{func.__name__} completed in {elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} failed after {elapsed:.2f}s: {e}")
            raise
    return wrapper


@dataclass
class HeadlineData:
    """Represents a single headline with metadata."""
    source_name: str
    source_leaning: float
    title: str
    url: str
    published_at: Optional[datetime]
    
    @property
    def perspective(self) -> str:
        """Classify into left/centre/right based on source leaning."""
        if self.source_leaning <= LEFT_THRESHOLD:
            return 'left'
        elif self.source_leaning >= RIGHT_THRESHOLD:
            return 'right'
        else:
            return 'centre'


@dataclass
class PerspectiveAnalysis:
    """Analysis of headlines from one perspective."""
    source_count: int
    headlines: List[HeadlineData]
    emphasis: Optional[str] = None
    language_patterns: Optional[List[str]] = None


class LensCheckGenerator:
    """
    Generates cross-perspective headline comparison for Daily Brief.
    
    Design Principles:
    - Objective selection criteria (no editorial discretion in story choice)
    - Neutral analysis language (observations, not judgments)
    - Transparent methodology (all criteria documented and logged)
    - Graceful degradation (skip if criteria not met, don't force weak examples)
    """
    
    def __init__(self, brief_date: Optional[date] = None):
        self.brief_date = brief_date or date.today()
        self.api_key, self.provider = get_system_api_key()
        self.llm_available = bool(self.api_key)

        # Token usage tracking (thread-safe)
        self.total_tokens = 0
        self.total_api_calls = 0
        self.generation_start_time = None
        self._token_lock = threading.Lock()  # Protect token counters in parallel execution

        if not self.llm_available:
            logger.warning("No LLM API key found. Lens check analysis will be limited.")

    @track_performance
    def generate(self) -> Optional[Dict[str, Any]]:
        """
        Generate the lens check analysis for today's brief.

        Returns:
            dict: Complete lens check data structure, or None if criteria not met
        """
        self.generation_start_time = time.time()
        logger.info(f"Generating lens check for {self.brief_date}")

        # Step 1: Find candidate stories with cross-spectrum coverage
        candidates = self._find_candidate_stories()
        
        if not candidates:
            logger.info("No stories meet lens check criteria - skipping section")
            return None
        
        # Step 2: Select the best candidate (highest balance score)
        selected_topic, selection_criteria = self._select_best_candidate(candidates)
        
        if not selected_topic:
            logger.info("No suitable story selected for lens check")
            return None
        
        logger.info(f"Selected topic for lens check: {selected_topic.title[:50]}...")
        
        # Step 3: Collect and group headlines by perspective
        headlines_by_perspective = self._collect_headlines(selected_topic)
        
        # Step 4: Validate we still have enough coverage
        if not self._validate_coverage(headlines_by_perspective):
            logger.warning("Insufficient coverage after headline collection - skipping")
            return None
        
        # Step 5: Generate neutral story summary
        story_summary = self._generate_story_summary(selected_topic, headlines_by_perspective)
        
        # Step 6: Analyze framing patterns per perspective
        perspective_analyses = self._analyze_perspectives(headlines_by_perspective)
        
        # Step 7: Generate contrast analysis
        contrast_analysis = self._generate_contrast_analysis(
            story_summary, perspective_analyses, headlines_by_perspective
        )
        
        # Step 8: Detect omissions (what no one covered)
        omissions = self._detect_omissions(
            story_summary, headlines_by_perspective
        )
        
        # Step 9: Select representative headlines for display
        display_headlines = self._select_display_headlines(
            headlines_by_perspective, perspective_analyses
        )
        
        # Calculate generation time
        generation_time = time.time() - self.generation_start_time if self.generation_start_time else 0

        # Assemble final structure
        # Always include all three perspectives (even if empty) for template safety
        lens_check = {
            'story_summary': story_summary,
            'topic_id': selected_topic.id,
            'topic_title': selected_topic.title,
            'selection_criteria': selection_criteria,
            'perspectives': {
                perspective: {
                    'source_count': len(headlines_by_perspective.get(perspective, [])),
                    'emphasis': perspective_analyses.get(perspective, {}).get('emphasis'),
                    'language_patterns': perspective_analyses.get(perspective, {}).get('language_patterns'),
                    'headlines': [
                        {
                            'source': h.source_name,
                            'title': h.title,
                            'url': h.url
                        }
                        for h in display_headlines.get(perspective, [])
                    ]
                }
                for perspective in ['left', 'centre', 'right']  # Always include all three
            },
            'contrast_analysis': contrast_analysis,
            'omissions': omissions,
            'methodology_version': METHODOLOGY_VERSION,
            'generated_at': datetime.utcnow().isoformat(),
            'metadata': {
                'total_tokens_used': self.total_tokens,
                'api_calls_made': self.total_api_calls,
                'generation_time_seconds': round(generation_time, 2)
            }
        }

        logger.info(f"Lens check generated successfully for topic {selected_topic.id}")
        logger.info(f"Token usage: {self.total_tokens} tokens across {self.total_api_calls} API calls")

        return lens_check
    
    def _find_candidate_stories(self) -> List[Tuple[TrendingTopic, Dict]]:
        """
        Find trending topics with sufficient cross-spectrum coverage.
        
        Selection Criteria:
        - Published in last 24-48 hours
        - At least MIN_SOURCES_PER_PERSPECTIVE sources in each perspective
        - Has articles with valid source political leanings
        
        Returns:
            List of (TrendingTopic, coverage_stats) tuples
        """
        cutoff_24h = datetime.utcnow() - timedelta(hours=24)
        cutoff_48h = datetime.utcnow() - timedelta(hours=48)
        
        # First try 24h, then 48h if needed
        for cutoff in [cutoff_24h, cutoff_48h]:
            topics = TrendingTopic.query.filter(
                TrendingTopic.status == 'published',
                TrendingTopic.published_at >= cutoff
            ).order_by(TrendingTopic.published_at.desc()).all()
            
            candidates = []
            
            for topic in topics:
                coverage = self._calculate_coverage_stats(topic)
                
                if coverage and self._meets_coverage_criteria(coverage):
                    candidates.append((topic, coverage))
            
            if candidates:
                hours = 24 if cutoff == cutoff_24h else 48
                logger.info(f"Found {len(candidates)} candidate stories in last {hours}h")
                return candidates
        
        logger.info("No candidate stories found with sufficient cross-spectrum coverage")
        return []
    
    def _calculate_coverage_stats(self, topic: TrendingTopic) -> Optional[Dict]:
        """
        Calculate coverage statistics for a topic.
        
        Returns:
            dict with left_count, centre_count, right_count, balance_score
        """
        try:
            article_links = topic.articles.all() if hasattr(topic, 'articles') else []
        except Exception as e:
            logger.warning(f"Error getting articles for topic {topic.id}: {e}")
            return None
        
        if not article_links:
            return None
        
        left_count = 0
        centre_count = 0
        right_count = 0
        
        for link in article_links:
            article = link.article
            if not article or not article.source:
                continue
            
            leaning = article.source.political_leaning
            if leaning is None:
                continue
            
            if leaning <= LEFT_THRESHOLD:
                left_count += 1
            elif leaning >= RIGHT_THRESHOLD:
                right_count += 1
            else:
                centre_count += 1
        
        total = left_count + centre_count + right_count
        
        if total == 0:
            return None
        
        # Balance score: how evenly distributed across perspectives
        # Perfect balance (1/3 each) = 1.0, extreme imbalance = 0.0
        ideal = total / 3
        deviation = (
            abs(left_count - ideal) +
            abs(centre_count - ideal) +
            abs(right_count - ideal)
        ) / (2 * total)  # Normalize to 0-1
        
        balance_score = 1.0 - deviation
        
        return {
            'left_count': left_count,
            'centre_count': centre_count,
            'right_count': right_count,
            'total_count': total,
            'balance_score': round(balance_score, 3)
        }
    
    def _meets_coverage_criteria(self, coverage: Dict) -> bool:
        """Check if coverage meets minimum requirements."""
        return (
            coverage['left_count'] >= MIN_SOURCES_PER_PERSPECTIVE and
            coverage['centre_count'] >= MIN_SOURCES_PER_PERSPECTIVE and
            coverage['right_count'] >= MIN_SOURCES_PER_PERSPECTIVE
        )
    
    def _select_best_candidate(
        self, 
        candidates: List[Tuple[TrendingTopic, Dict]]
    ) -> Tuple[Optional[TrendingTopic], Optional[Dict]]:
        """
        Select the best candidate story for lens check.
        
        Selection Priority:
        1. Highest balance score (most even coverage across perspectives)
        2. Higher total source count (tie-breaker)
        
        Returns:
            (TrendingTopic, selection_criteria) or (None, None)
        """
        if not candidates:
            return None, None
        
        # Sort by balance score (desc), then total count (desc)
        sorted_candidates = sorted(
            candidates,
            key=lambda x: (x[1]['balance_score'], x[1]['total_count']),
            reverse=True
        )
        
        best_topic, best_coverage = sorted_candidates[0]
        
        selection_criteria = {
            'total_sources': best_coverage['total_count'],
            'left_sources': best_coverage['left_count'],
            'centre_sources': best_coverage['centre_count'],
            'right_sources': best_coverage['right_count'],
            'coverage_balance_score': best_coverage['balance_score'],
            'candidates_considered': len(candidates),
            'selected_reason': 'Highest cross-spectrum coverage balance'
        }
        
        return best_topic, selection_criteria
    
    def _collect_headlines(self, topic: TrendingTopic) -> Dict[str, List[HeadlineData]]:
        """
        Collect all headlines for a topic, grouped by perspective.
        
        Returns:
            {'left': [HeadlineData, ...], 'centre': [...], 'right': [...]}
        """
        headlines = defaultdict(list)
        
        article_links = topic.articles.all() if hasattr(topic, 'articles') else []
        
        for link in article_links:
            article = link.article
            if not article or not article.source:
                continue
            
            leaning = article.source.political_leaning
            if leaning is None:
                continue
            
            headline_data = HeadlineData(
                source_name=article.source.name,
                source_leaning=leaning,
                title=article.title,
                url=article.url,
                published_at=article.published_at
            )
            
            headlines[headline_data.perspective].append(headline_data)
        
        return dict(headlines)
    
    def _validate_coverage(self, headlines_by_perspective: Dict[str, List[HeadlineData]]) -> bool:
        """Validate we have sufficient coverage in all perspectives."""
        for perspective in ['left', 'centre', 'right']:
            if len(headlines_by_perspective.get(perspective, [])) < MIN_SOURCES_PER_PERSPECTIVE:
                return False
        return True
    
    def _generate_story_summary(
        self, 
        topic: TrendingTopic,
        headlines_by_perspective: Dict[str, List[HeadlineData]]
    ) -> str:
        """
        Generate a neutral one-sentence summary of the story.
        
        Uses LLM to create factual summary without framing bias.
        """
        if not self.llm_available:
            return topic.title
        
        # Collect sample headlines for context
        sample_headlines = []
        for perspective in ['left', 'centre', 'right']:
            for h in headlines_by_perspective.get(perspective, [])[:2]:
                sample_headlines.append(f"[{h.source_name}] {h.title}")
        
        headlines_text = '\n'.join(sample_headlines)
        
        prompt = f"""You are a neutral news analyst. Based on these headlines about the same story from different outlets, write ONE sentence that factually describes what happened.

HEADLINES:
{headlines_text}

REQUIREMENTS:
- One sentence only (max 30 words)
- State facts only - no interpretation or framing
- Use neutral language - avoid loaded words
- Focus on the event itself, not reactions to it
- Do not attribute motives or intentions

Return ONLY the summary sentence, no quotes or explanation."""

        try:
            response = self._call_llm(prompt)
            summary = response.strip().strip('"').strip("'")
            return summary[:200]  # Safety limit
        except Exception as e:
            logger.warning(f"Story summary generation failed: {e}")
            return topic.title
    
    def _analyze_perspectives(
        self,
        headlines_by_perspective: Dict[str, List[HeadlineData]]
    ) -> Dict[str, Dict]:
        """
        Analyze framing patterns for each perspective (in parallel for 3x speedup).

        Returns:
            {
                'left': {'emphasis': '...', 'language_patterns': [...]},
                'centre': {...},
                'right': {...}
            }
        """
        if not self.llm_available:
            return {}

        def analyze_single_perspective(perspective: str) -> Tuple[str, Optional[Dict]]:
            """Analyze one perspective - suitable for parallel execution."""
            headlines = headlines_by_perspective.get(perspective, [])
            if not headlines:
                return perspective, None

            headlines_text = '\n'.join([
                f"- [{h.source_name}] {h.title}" for h in headlines
            ])

            prompt = f"""Analyze these {perspective.upper()} news headlines about the same story.

HEADLINES:
{headlines_text}

Identify:
1. EMPHASIS: What aspect of the story do these headlines focus on? (one phrase, max 8 words)
2. LANGUAGE_PATTERNS: What words or phrases appear repeatedly or characterize the framing? (list 2-4 words)

REQUIREMENTS:
- Be observational, not judgmental
- Do not use words like "bias", "slant", or "propaganda"
- Focus on what IS said, not what you think they should say
- Be specific and concrete

Return JSON:
{{"emphasis": "...", "language_patterns": ["word1", "word2", "word3"]}}"""

            try:
                response = self._call_llm(prompt)
                data = extract_json(response)

                # Validate JSON structure
                if not isinstance(data, dict):
                    raise ValueError("Response is not a valid dictionary")

                emphasis = data.get('emphasis', '')
                language_patterns = data.get('language_patterns', [])

                # Validate types
                if not isinstance(emphasis, str):
                    emphasis = str(emphasis) if emphasis else ''
                if not isinstance(language_patterns, list):
                    language_patterns = []

                result = {
                    'emphasis': emphasis,
                    'language_patterns': language_patterns
                }
                return perspective, result

            except Exception as e:
                logger.warning(f"Perspective analysis failed for {perspective}: {e}")
                return perspective, {'emphasis': None, 'language_patterns': None}

        # Execute analyses in parallel (up to 3 concurrent calls)
        analyses = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(analyze_single_perspective, p): p
                for p in ['left', 'centre', 'right']
            }

            for future in as_completed(futures):
                try:
                    perspective, result = future.result()
                    if result:
                        analyses[perspective] = result
                except Exception as e:
                    perspective = futures[future]
                    logger.error(f"Critical error analyzing {perspective}: {e}")
                    analyses[perspective] = {'emphasis': None, 'language_patterns': None}

        return analyses
    
    def _generate_contrast_analysis(
        self,
        story_summary: str,
        perspective_analyses: Dict[str, Dict],
        headlines_by_perspective: Dict[str, List[HeadlineData]]
    ) -> str:
        """
        Generate analysis of how perspectives differ.
        
        This is the "aha moment" - the key insight about framing differences.
        """
        if not self.llm_available:
            return "Compare the headlines above to see how different outlets frame this story."
        
        # Build context
        context_parts = [f"STORY: {story_summary}", ""]
        
        for perspective in ['left', 'centre', 'right']:
            headlines = headlines_by_perspective.get(perspective, [])
            analysis = perspective_analyses.get(perspective, {})
            
            headlines_text = '; '.join([h.title for h in headlines[:3]])
            emphasis = analysis.get('emphasis', 'unknown')
            
            context_parts.append(f"{perspective.upper()} ({len(headlines)} sources):")
            context_parts.append(f"  Headlines: {headlines_text}")
            context_parts.append(f"  Emphasis: {emphasis}")
            context_parts.append("")
        
        context = '\n'.join(context_parts)
        
        prompt = f"""You are analyzing how different news perspectives frame the same story.

{context}

Write 2-3 sentences that:
1. Describe the KEY CONTRAST between how these perspectives frame the story
2. Focus on observable differences in emphasis, word choice, or focus
3. Do NOT say one is "right" or "wrong" or "biased"
4. Help readers see the difference so they can form their own view

REQUIREMENTS:
- Be factual and observational
- Use phrases like "X focuses on..." or "Y emphasizes..." rather than "X is biased toward..."
- Maximum 50 words total
- Do not editorialize or suggest which framing is correct

Return ONLY the contrast analysis, no quotes or JSON."""

        try:
            response = self._call_llm(prompt)
            return response.strip()[:300]  # Safety limit
        except Exception as e:
            logger.warning(f"Contrast analysis generation failed: {e}")
            return "Different outlets emphasize different aspects of this story. Compare the headlines to see the contrast."
    
    def _detect_omissions(
        self,
        story_summary: str,
        headlines_by_perspective: Dict[str, List[HeadlineData]]
    ) -> Optional[str]:
        """
        Identify what no outlet mentioned (collective blind spot).
        
        Returns insight about omissions, or None if nothing notable.
        """
        if not self.llm_available:
            return None
        
        all_headlines = []
        for perspective, headlines in headlines_by_perspective.items():
            for h in headlines:
                all_headlines.append(f"[{h.source_name}] {h.title}")
        
        headlines_text = '\n'.join(all_headlines)
        
        prompt = f"""You are analyzing news coverage for potential blind spots.

STORY: {story_summary}

ALL HEADLINES:
{headlines_text}

Consider: Is there an important angle, stakeholder, or consequence that NONE of these headlines mention?

Examples of omissions:
- Affected groups not mentioned (e.g., workers, patients, residents)
- Long-term consequences
- Historical context
- Alternative perspectives

REQUIREMENTS:
- Only report a genuine, notable omission
- If coverage seems reasonably complete, return "none"
- Be specific about what's missing
- Maximum 25 words
- Do not speculate wildly - only note clear omissions

Return ONLY the omission (or "none"), no explanation or JSON."""

        try:
            response = self._call_llm(prompt)
            omission = response.strip()
            
            if omission.lower() in ['none', 'n/a', 'nothing notable', '']:
                return None
            
            return omission[:200]  # Safety limit
        except Exception as e:
            logger.warning(f"Omission detection failed: {e}")
            return None
    
    def _select_display_headlines(
        self,
        headlines_by_perspective: Dict[str, List[HeadlineData]],
        perspective_analyses: Dict[str, Dict]
    ) -> Dict[str, List[HeadlineData]]:
        """
        Select representative headlines for display.
        
        Selection Strategy:
        - Pick 2 headlines per perspective
        - Prefer headlines from higher-reputation sources
        - Prefer more recent headlines
        - Avoid duplicates from same source
        """
        display = {}
        
        for perspective in ['left', 'centre', 'right']:
            headlines = headlines_by_perspective.get(perspective, [])
            
            if not headlines:
                display[perspective] = []
                continue
            
            # Sort by recency (most recent first)
            # Use timezone-aware datetime.min for safety
            sorted_headlines = sorted(
                headlines,
                key=lambda h: h.published_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True
            )
            
            # Select up to HEADLINES_TO_DISPLAY, avoiding same source
            selected = []
            seen_sources = set()
            
            for h in sorted_headlines:
                if h.source_name in seen_sources:
                    continue
                selected.append(h)
                seen_sources.add(h.source_name)
                
                if len(selected) >= HEADLINES_TO_DISPLAY:
                    break
            
            # If we still need more, allow same source
            if len(selected) < HEADLINES_TO_DISPLAY:
                for h in sorted_headlines:
                    if h not in selected:
                        selected.append(h)
                        if len(selected) >= HEADLINES_TO_DISPLAY:
                            break
            
            display[perspective] = selected
        
        return display
    
    def _call_llm(self, prompt: str) -> str:
        """Call LLM API (OpenAI or Anthropic)."""
        if not self.llm_available:
            raise ValueError("No LLM API key configured")
        
        if self.provider == 'openai':
            return self._call_openai(prompt)
        elif self.provider == 'anthropic':
            return self._call_anthropic(prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")
    
    @retry_on_api_error(max_retries=3)
    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API with retry logic and token tracking."""
        import openai

        client = openai.OpenAI(api_key=self.api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a neutral media analyst. Your role is to observe and describe, not judge or editorialize. Respond concisely."
                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.3
        )

        # Track token usage (thread-safe)
        if hasattr(response, 'usage') and response.usage:
            tokens = response.usage.total_tokens
            with self._token_lock:
                self.total_tokens += tokens
                self.total_api_calls += 1
            logger.debug(f"OpenAI API call: {tokens} tokens "
                        f"(prompt: {response.usage.prompt_tokens}, "
                        f"completion: {response.usage.completion_tokens})")

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from OpenAI")

        return content
    
    @retry_on_api_error(max_retries=3)
    def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic API with retry logic and token tracking."""
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            temperature=0.3,
            system="You are a neutral media analyst. Your role is to observe and describe, not judge or editorialize. Respond concisely.",
            messages=[{"role": "user", "content": prompt}]
        )

        # Track token usage (thread-safe)
        if hasattr(message, 'usage') and message.usage:
            # Anthropic usage has input_tokens and output_tokens
            tokens = message.usage.input_tokens + message.usage.output_tokens
            with self._token_lock:
                self.total_tokens += tokens
                self.total_api_calls += 1
            logger.debug(f"Anthropic API call: {tokens} tokens "
                        f"(input: {message.usage.input_tokens}, "
                        f"output: {message.usage.output_tokens})")

        content_block = message.content[0]
        content = getattr(content_block, 'text', None) or str(content_block)

        if not content:
            raise ValueError("Empty response from Anthropic")

        return content


def generate_lens_check(brief_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """
    Convenience function to generate lens check for a date.
    
    Args:
        brief_date: Date to generate for (default: today)
    
    Returns:
        Lens check data structure, or None if criteria not met
    """
    generator = LensCheckGenerator(brief_date)
    return generator.generate()
