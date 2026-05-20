"""
Briefing Generator

Generalized brief generator for multi-tenant briefings.
Works with IngestedItem instead of TrendingTopic.
Creates BriefRun instead of DailyBrief.

Editorial output is produced as **structured data** on ``BriefRunItem``
columns (``cluster_also_covered``, ``context_label``, ``context_insight``)
and rendered via the ``emails/paid_brief.html`` Jinja template. The
generator no longer concatenates HTML strings; the template is the single
source of truth for visual design across email and the web reader.
"""

import logging
from datetime import datetime, date, timedelta
from app.lib.time import utcnow_naive
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.exc import IntegrityError
from flask import render_template
from flask_babel import lazy_gettext as _l
from app import db
from app.models import (
    Briefing, BriefRun, BriefRunItem, IngestedItem, InputSource
)
from app.trending.scorer import extract_json, get_system_api_key
from app.briefing.story_clustering import (
    StoryCluster,
    attach_cluster_metadata,
    cluster_scored_items,
)
from app.briefing.template_config import get_sections_for_briefing
from app.lib.editorial import (
    CoverageBlock,
    QualityVerdict,
    UnderreportedPick,
    assess_brief_quality,
    coverage_block_for_items,
    find_underreported_story,
)

logger = logging.getLogger(__name__)

class BriefingGenerator:
    """
    Generates brief runs from IngestedItem content.
    
    Similar to BriefGenerator but:
    - Works with IngestedItem (not TrendingTopic)
    - Creates BriefRun (not DailyBrief)
    - Supports custom source selection
    - Uses briefing configuration (tone, filters)
    """
    
    def __init__(self):
        self.api_key, self.provider = get_system_api_key()
        self.llm_available = bool(self.api_key)
        self._current_user_id = None
        # Locale and natural-language instruction the LLM should follow when
        # writing content for the current run. Set per-run by
        # ``generate_brief_run``; defaults keep the fallback content path
        # working when nothing else has been set.
        self._current_locale: Optional[str] = 'en'
        self._llm_language: str = 'British English (analyse, centre, organisation)'

        if not self.llm_available:
            logger.warning("No LLM API key found. Brief will use fallback content generation.")

    def _track_token_spend(self, tokens_used: int, cost_usd: float, model: str):
        """Record token spend for the current user if available."""
        if self._current_user_id:
            try:
                from app.billing.abuse_guardrails import record_token_spend
                record_token_spend(self._current_user_id, tokens_used, cost_usd, model)
            except Exception as e:
                logger.debug(f"Could not record token spend: {e}")

    def _track_quality_hold(
        self, briefing: Briefing, brief_run: BriefRun, quality: QualityVerdict,
    ) -> None:
        """Emit a PostHog event whenever the quality gate holds a brief.

        Visibility into how often this fires (per template, per user) is the
        signal we need to decide whether to invest in better source coverage,
        widen the warmup budget, or tune the thresholds in
        ``app.lib.editorial.quality``. Best-effort — never raises into the
        generator.
        """
        try:
            from app.lib.posthog_utils import safe_posthog_capture
            try:
                import posthog as _posthog
            except ImportError:
                _posthog = None
            distinct_id = (
                str(self._current_user_id) if self._current_user_id else f'briefing-{briefing.id}'
            )
            safe_posthog_capture(
                posthog_client=_posthog,
                distinct_id=distinct_id,
                event='paid_brief_held_for_quality',
                properties={
                    'briefing_id': briefing.id,
                    'brief_run_id': brief_run.id,
                    'template_slug': briefing.template.slug if briefing.template else None,
                    'hold_reason': quality.hold_reason,
                    'item_count': quality.item_count,
                    'distinct_sources': quality.distinct_sources,
                    'dominance': round(quality.dominance, 3),
                    'configured_sources': len(briefing.sources or []),
                },
            )
        except Exception as exc:
            logger.debug(f"Could not emit quality-hold event: {exc}")

    def _call_llm(self, prompt: str, system_prompt: str = "You are a helpful assistant.", max_tokens: int = 500, temperature: float = 0.7, max_retries: int = 3) -> Optional[str]:
        """Call LLM API with retry logic for transient errors."""
        import time

        if not self.llm_available:
            return None

        if self.provider == 'openai':
            return self._call_llm_openai(prompt, system_prompt, max_tokens, temperature, max_retries)
        elif self.provider == 'anthropic':
            return self._call_llm_anthropic(prompt, system_prompt, max_tokens, temperature, max_retries)
        else:
            return None

    def _call_llm_openai(self, prompt: str, system_prompt: str, max_tokens: int, temperature: float, max_retries: int) -> Optional[str]:
        import time
        import openai

        client = openai.OpenAI(api_key=self.api_key)

        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                content = response.choices[0].message.content
                if not content:
                    logger.warning("Empty response from OpenAI")
                    return None
                if hasattr(response, 'usage') and response.usage:
                    total_tokens = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)
                    cost = total_tokens * 0.00000015
                    self._track_token_spend(total_tokens, cost, 'gpt-4o-mini')
                return content

            except openai.APIStatusError as e:
                if e.status_code in (500, 502, 503, 529) and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"OpenAI API error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                logger.error(f"OpenAI API error after {attempt + 1} attempts: {e}")
                return None

            except openai.APIConnectionError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"OpenAI connection error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                logger.error(f"OpenAI connection error after {attempt + 1} attempts: {e}")
                return None

            except Exception as e:
                logger.error(f"OpenAI API error: {e}")
                return None

        return None

    def _call_llm_anthropic(self, prompt: str, system_prompt: str, max_tokens: int, temperature: float, max_retries: int) -> Optional[str]:
        import time
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        for attempt in range(max_retries):
            try:
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt}]
                )
                content_block = response.content[0]
                content = getattr(content_block, 'text', None) or str(content_block)
                if not content:
                    logger.warning("Empty response from Anthropic")
                    return None
                if hasattr(response, 'usage') and response.usage:
                    total_tokens = (getattr(response.usage, 'input_tokens', 0) or 0) + (getattr(response.usage, 'output_tokens', 0) or 0)
                    cost = total_tokens * 0.00000025
                    self._track_token_spend(total_tokens, cost, 'claude-haiku-4-5')
                return content

            except anthropic.APIStatusError as e:
                if e.status_code in (500, 502, 503, 529) and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Anthropic API error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                logger.error(f"Anthropic API error after {attempt + 1} attempts: {e}")
                return None

            except anthropic.APIConnectionError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Anthropic connection error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                logger.error(f"Anthropic connection error after {attempt + 1} attempts: {e}")
                return None

            except Exception as e:
                logger.error(f"Anthropic API error: {e}")
                return None

        return None
    
    def generate_brief_run(
        self,
        briefing: Briefing,
        scheduled_at: datetime,
        ingested_items: Optional[List[IngestedItem]] = None
    ) -> Optional[BriefRun]:
        """
        Generate a BriefRun for a briefing.
        
        Args:
            briefing: Briefing configuration
            scheduled_at: When this run should execute
            ingested_items: Optional pre-selected items (if None, selects from sources)
        
        Returns:
            BriefRun instance (saved to database) or None if no content
        """
        try:
            if briefing.owner_type == 'user':
                self._current_user_id = briefing.owner_id
            elif briefing.owner_type == 'org':
                from app.models import OrganizationMember
                admin_member = OrganizationMember.query.filter_by(
                    organization_id=briefing.owner_id, role='admin'
                ).first()
                if admin_member:
                    self._current_user_id = admin_member.user_id

            # Cache the briefing's preferred LLM-output language for the rest
            # of this generation run. Every prompt (intro, item summary,
            # takeaways, deeper context) reads from this so a French- or
            # Korean-speaking owner gets content in their language, not just
            # translated UI chrome around English prose.
            from app.briefing.briefing_locale import (
                llm_language_instruction, resolve_briefing_locale,
            )
            self._current_locale = resolve_briefing_locale(briefing)
            self._llm_language = llm_language_instruction(self._current_locale)

            selection_pool: List[IngestedItem] = []
            cluster_source_counts: Dict[int, int] = {}
            if ingested_items is None:
                ingested_items, selection_pool, cluster_source_counts = (
                    self._select_items_for_briefing(briefing)
                )

            if not ingested_items:
                logger.warning(f"No items available for briefing {briefing.id}")
                return None
            
            # Check if run already exists for this scheduled time
            existing = BriefRun.query.filter_by(
                briefing_id=briefing.id,
                scheduled_at=scheduled_at
            ).first()
            
            if existing:
                logger.info(f"BriefRun already exists for briefing {briefing.id} at {scheduled_at}")
                return existing
            
            # Create BriefRun with race condition handling
            brief_run = BriefRun(
                briefing_id=briefing.id,
                scheduled_at=scheduled_at,
                status='generated_draft' if briefing.mode == 'approval_required' else 'approved',
                generated_at=utcnow_naive()
            )
            
            try:
                db.session.add(brief_run)
                db.session.flush()  # Get brief_run.id
            except IntegrityError as e:
                # Race condition: another worker created the record between our check and insert
                db.session.rollback()
                logger.info(f"Race condition detected for briefing {briefing.id} at {scheduled_at}, fetching existing record")
                existing = BriefRun.query.filter_by(
                    briefing_id=briefing.id,
                    scheduled_at=scheduled_at
                ).first()
                if existing:
                    return existing
                # If still not found, re-raise the error
                raise
            
            # Generate content — title is briefing-level; intro/takeaways
            # must reflect items that actually rendered (see created_items).
            
            # Use briefing's max_items setting (default 10, capped at 20)
            max_items = min(briefing.max_items or 10, 20)
            # Track items that actually generated cleanly. A mid-loop failure
            # means the failed item isn't in BriefRunItem — using ``ingested_items[:N]``
            # would mis-align downstream coverage / quality / takeaway inputs
            # with what the reader actually sees.
            created_items: List[IngestedItem] = []
            for item in ingested_items[:max_items]:
                position = len(created_items) + 1
                try:
                    run_item = self._generate_brief_item(brief_run, item, position, briefing)
                    db.session.add(run_item)
                    created_items.append(item)
                except Exception as e:
                    logger.error(f"Failed to generate item for IngestedItem {item.id}: {e}")
                    continue

            if not created_items:
                logger.warning(f"No items generated for BriefRun {brief_run.id}")
                db.session.rollback()
                return None

            items_created = len(created_items)

            from flask_babel import force_locale

            with force_locale(self._current_locale):
                title = self._generate_brief_title(briefing, created_items)
                intro_text = self._generate_intro_text(briefing, created_items)
                key_takeaways = self._generate_key_takeaways(briefing, created_items)
                coverage_block = coverage_block_for_items(created_items)
                underreported = find_underreported_story(
                    candidates=selection_pool or ingested_items,
                    selected_ids=[i.id for i in created_items],
                    cluster_source_counts=cluster_source_counts,
                )
                brief_run.draft_markdown = self._render_markdown(
                    title, intro_text, key_takeaways, brief_run,
                )
                brief_run.draft_html = self._render_html(
                    brief_run=brief_run,
                    briefing=briefing,
                    intro_text=intro_text,
                    key_takeaways=key_takeaways,
                    coverage_block=coverage_block,
                    underreported=underreported,
                )
                quality = assess_brief_quality(created_items)
                if briefing.mode == 'auto_send':
                    if quality.should_hold:
                        brief_run.status = 'awaiting_approval'
                        brief_run.failure_reason = quality.hold_reason
                        logger.warning(
                            "BriefRun %s held for review (briefing=%s): %s "
                            "[items=%s sources=%s dominance=%.2f]",
                            brief_run.id, briefing.id, quality.hold_reason,
                            quality.item_count, quality.distinct_sources,
                            quality.dominance,
                        )
                        self._track_quality_hold(briefing, brief_run, quality)
                    else:
                        brief_run.approved_markdown = brief_run.draft_markdown
                        brief_run.approved_html = brief_run.draft_html
                        brief_run.status = 'approved'

            db.session.commit()

            logger.info(
                "Generated BriefRun %s for briefing %s (%s items, %s sources, status=%s)",
                brief_run.id, briefing.name, items_created,
                quality.distinct_sources, brief_run.status,
            )

            # Notify the owner whenever a brief is sitting in the approval
            # queue — that includes runs the quality gate held back from
            # auto_send. They need to know it's there to act on it.
            if brief_run.status in ('awaiting_approval', 'generated_draft'):
                try:
                    from app.briefing.notifications import notify_draft_ready
                    notify_draft_ready(brief_run.id)
                except Exception as e:
                    logger.error(f"Failed to send draft notification: {e}")

            return brief_run
            
        except Exception as e:
            logger.error(f"Error generating BriefRun for briefing {briefing.id}: {e}", exc_info=True)
            db.session.rollback()
            return None
    
    def _select_items_for_briefing(
        self, briefing: Briefing, limit: int = None,
    ) -> Tuple[List[IngestedItem], List[IngestedItem], Dict[int, int]]:
        """
        Select items from briefing's sources using an advanced multi-factor scoring approach:
        1. Global ranking with recency decay, topic preferences, keywords, source priority, and credibility
        2. Fair selection with source diversity and discovery quota
        3. Empty results fallback with graceful degradation

        Returns:
            Tuple of ``(selected_items, candidate_pool, cluster_source_counts)``:
              - selected_items: items chosen for the brief (length ≤ limit)
              - candidate_pool: every item considered (after exclude filter)
                so the underreported finder can pick from rejects
              - cluster_source_counts: ``{item.id -> source_count}`` so the
                underreported finder can skip well-covered stories
        """
        from datetime import timedelta
        from collections import defaultdict
        import re
        import math
        
        # Get all sources for this briefing with their priorities
        source_priorities = {bs.source_id: getattr(bs, 'priority', 1) or 1 for bs in briefing.sources}
        source_ids = list(source_priorities.keys())
        if not source_ids:
            return [], [], {}
        
        # Use briefing's max_items setting, or default to 10
        if limit is None:
            limit = min(briefing.max_items or 10, 20)
        
        # Get user's content filters
        filters = briefing.filters_json or {}
        include_keywords = [k.lower().strip() for k in filters.get('include_keywords', []) if k.strip()]
        exclude_keywords = [k.lower().strip() for k in filters.get('exclude_keywords', []) if k.strip()]
        
        # Get topic preferences (topic -> weight 1-3)
        topic_preferences = briefing.topic_preferences or {}
        
        # Discovery quota: reserve slots for diverse content outside preferences (prevent filter bubbles)
        discovery_quota = max(1, limit // 5)  # 20% of items for discovery
        preference_quota = limit - discovery_quota
        
        # Get recent items from these sources (last 7 days)
        # Use ItemFeedService for proper channel filtering
        from app.briefing.item_feed_service import ItemFeedService
        
        now = utcnow_naive()
        
        # ItemFeedService handles channel filtering and returns allowed items
        all_items = ItemFeedService.get_items_for_channel(
            channel=ItemFeedService.CHANNEL_USER_BRIEFINGS,
            source_ids=source_ids,
            days_back=7,
            limit=limit * 20
        )
        
        # Build source credibility map using verified status and political leaning data
        # Batch load all sources to avoid N+1 queries
        sources_map = {s.id: s for s in InputSource.query.filter(InputSource.id.in_(source_ids)).all()}
        source_credibility = {}
        for source_id in source_ids:
            source = sources_map.get(source_id)
            if source:
                # Base credibility of 1.0
                credibility = 1.0
                # Admin-verified sources get a significant boost
                if getattr(source, 'is_verified', False):
                    credibility = 1.3
                elif hasattr(source, 'political_leaning') and source.political_leaning is not None:
                    # Sources with political leaning data are researched
                    credibility = 1.2
                # Healthy sources get a small boost
                if source.status == 'ready' and source.fetch_error_count == 0:
                    credibility += 0.1
                source_credibility[source_id] = credibility
            else:
                source_credibility[source_id] = 1.0
        
        def get_text(item: IngestedItem) -> str:
            """Get searchable text from item"""
            return f"{item.title} {item.content_text or ''}".lower()
        
        def should_exclude(text: str) -> bool:
            """Check if item should be excluded based on filters"""
            if not exclude_keywords:
                return False
            return any(kw in text for kw in exclude_keywords)
        
        def matches_include(text: str) -> bool:
            """Check if item matches include keywords"""
            if not include_keywords:
                return False
            return any(kw in text for kw in include_keywords)
        
        def matches_any_topic(text: str) -> bool:
            """Check if item matches any topic preference"""
            if not topic_preferences:
                return False
            return any(topic.lower() in text for topic in topic_preferences)
        
        def calculate_recency_score(item: IngestedItem) -> float:
            """
            Calculate recency decay score (exponential decay with 48-hour half-life).
            Newer articles get higher scores.
            - Published today: ~3.0
            - Published 2 days ago: ~1.5 (half)
            - Published 4 days ago: ~0.75 (quarter)
            - Published 7 days ago: ~0.26
            """
            pub_time = item.published_at or item.fetched_at or now
            hours_old = max(0, (now - pub_time).total_seconds() / 3600)
            # Exponential decay with exact 48-hour half-life: decay = 0.5^(hours/48) = exp(-ln(2) * hours/48)
            decay = math.exp(-math.log(2) * hours_old / 48)
            return 3.0 * decay
        
        def calculate_score(item: IngestedItem, text: str) -> float:
            """
            Calculate global relevance score for an item.
            Score components:
            - Recency: 0-3 (exponential decay)
            - Include keyword match: +5.0 (significant boost)
            - Topic preference match: +weight (1-3 per topic)
            - Source priority: +priority (1-3)
            - Source credibility: multiplier (0.8-1.3)
            """
            score = 0.0
            
            # Recency score (favor fresh content)
            score += calculate_recency_score(item)
            
            # Boost for matching include keywords
            if matches_include(text):
                score += 5.0
            
            # Boost for matching topic preferences
            for topic, weight in topic_preferences.items():
                if topic.lower() in text:
                    score += float(weight)
            
            # Boost for source priority
            source_priority = source_priorities.get(item.source_id, 1)
            score += float(source_priority)
            
            # Apply source credibility multiplier
            credibility = source_credibility.get(item.source_id, 1.0)
            score *= credibility
            
            return score
        
        def normalize_headline(title: str) -> str:
            """Normalize headline for dedup comparison"""
            normalized = re.sub(r'[^\w\s]', '', title.lower())
            words = [w for w in normalized.split() if len(w) > 3][:5]
            return ' '.join(sorted(words))
        
        # Phase 1: Score and categorize all items
        preference_items = []  # Items matching user preferences
        discovery_items = []   # Items for discovery (don't match preferences but not excluded)
        all_unfiltered = []    # Fallback pool (everything except excluded)
        
        for item in all_items:
            text = get_text(item)
            
            # Apply exclude filter (hard filter)
            if should_exclude(text):
                continue
            
            score = calculate_score(item, text)
            all_unfiltered.append((item, score))
            
            # Categorize: preference match vs discovery
            if matches_include(text) or matches_any_topic(text):
                preference_items.append((item, score))
            else:
                discovery_items.append((item, score))
        
        # Sort each pool by score
        preference_items.sort(key=lambda x: x[1], reverse=True)
        discovery_items.sort(key=lambda x: x[1], reverse=True)
        all_unfiltered.sort(key=lambda x: x[1], reverse=True)
        
        # Phase 2: Cluster similar stories, then select with source diversity
        clusters = cluster_scored_items(all_unfiltered)
        preference_clusters = [
            c for c in clusters
            if matches_include(get_text(c.primary)) or matches_any_topic(get_text(c.primary))
        ]
        preference_set = set(id(c) for c in preference_clusters)
        discovery_clusters = [c for c in clusters if id(c) not in preference_set]

        selected_items: List[IngestedItem] = []
        seen_headlines: set = set()
        source_counts: dict = defaultdict(int)
        max_per_source = max(2, (limit // len(source_ids)) + 1) if source_ids else limit
        min_distinct_sources = min(
            max(3, limit // 3),
            len(source_ids),
        ) if source_ids else 1

        def _cluster_headline(cluster: StoryCluster) -> str:
            return normalize_headline(cluster.primary.title or '')

        def _pick_cluster(cluster: StoryCluster, relax_source_limit: bool = False) -> bool:
            if len(selected_items) >= limit:
                return False
            normalized = _cluster_headline(cluster)
            if normalized in seen_headlines:
                return False
            primary = cluster.primary
            if not relax_source_limit and source_counts[primary.source_id] >= max_per_source:
                return False
            seen_headlines.add(normalized)
            primary._selection_score = cluster.score  # type: ignore[attr-defined]
            attach_cluster_metadata(cluster)
            selected_items.append(primary)
            source_counts[primary.source_id] += 1
            return True

        def select_clusters_from_pool(
            pool: List[StoryCluster],
            max_items: int,
            *,
            relax_source_limit: bool = False,
            diversity_first: bool = False,
        ) -> int:
            added = 0
            if diversity_first and len(set(source_counts.keys())) < min_distinct_sources:
                represented = set(source_counts.keys())
                for cluster in pool:
                    if added >= max_items or len(selected_items) >= limit:
                        break
                    sid = cluster.primary.source_id
                    if sid in represented:
                        continue
                    if _pick_cluster(cluster, relax_source_limit=relax_source_limit):
                        represented.add(sid)
                        added += 1
            for cluster in pool:
                if added >= max_items or len(selected_items) >= limit:
                    break
                if _pick_cluster(cluster, relax_source_limit=relax_source_limit):
                    added += 1
            return added

        preference_selected = select_clusters_from_pool(
            preference_clusters,
            preference_quota,
            diversity_first=True,
        )
        discovery_selected = select_clusters_from_pool(
            discovery_clusters,
            discovery_quota,
            diversity_first=len(set(source_counts.keys())) < min_distinct_sources,
        )

        if len(selected_items) < limit:
            remaining = limit - len(selected_items)
            select_clusters_from_pool(
                clusters,
                remaining,
                relax_source_limit=False,
                diversity_first=len(set(source_counts.keys())) < min_distinct_sources,
            )
        
        # Empty results fallback: if filters are too aggressive, provide feedback
        filters_applied = bool(include_keywords or exclude_keywords or topic_preferences)
        if len(selected_items) == 0 and filters_applied and all_items:
            logger.warning(
                f"Briefing {briefing.id}: Filters too restrictive, falling back to unfiltered selection"
            )
            # Fallback: ignore all filters and just score by recency + source priority
            fallback_items = []
            for item in all_items:
                score = calculate_recency_score(item) + source_priorities.get(item.source_id, 1)
                fallback_items.append((item, score))
            fallback_clusters = cluster_scored_items(fallback_items)
            fallback_source_counts = defaultdict(int)
            for cluster in fallback_clusters:
                if len(selected_items) >= limit:
                    break
                normalized = normalize_headline(cluster.primary.title or '')
                if normalized in seen_headlines:
                    continue
                if fallback_source_counts[cluster.primary.source_id] >= max_per_source:
                    continue
                seen_headlines.add(normalized)
                cluster.primary._selection_score = cluster.score  # type: ignore[attr-defined]
                attach_cluster_metadata(cluster)
                selected_items.append(cluster.primary)
                fallback_source_counts[cluster.primary.source_id] += 1
            
            # Mark that fallback was used (can be shown to user)
            briefing._selection_fallback_used = True
        
        logger.info(
            f"Selected {len(selected_items)} items ({preference_selected} pref, {discovery_selected} discovery) "
            f"from {len(set(i.source_id for i in selected_items))} sources "
            f"({len(clusters)} story clusters) for briefing {briefing.id}"
        )

        # Map each candidate item -> how many sources covered its cluster, so
        # the underreported finder can avoid surfacing well-covered stories.
        cluster_source_counts: Dict[int, int] = {}
        for cluster in clusters:
            count = len(cluster.source_names)
            for member in cluster.all_items:
                if member.id is not None:
                    cluster_source_counts[member.id] = count

        candidate_pool = [pair[0] for pair in all_unfiltered]

        return selected_items, candidate_pool, cluster_source_counts
    
    def _generate_brief_title(self, briefing: Briefing, items: List[IngestedItem]) -> str:
        """Generate brief title with a locale-aware day name."""
        from datetime import date as date_cls
        from flask_babel import format_date

        day_name = format_date(date_cls.today(), format='EEEE')
        return f"{briefing.name} - {day_name}"
    
    def _generate_intro_text(self, briefing: Briefing, items: List[IngestedItem]) -> str:
        """Generate an editorial intro previewing today's stories.

        Runs inside the briefing-owner's locale (set by ``generate_brief_run``
        via ``force_locale``) so ``gettext`` resolves to the right language
        for both the deterministic fallbacks and any user-visible chrome.
        """
        from flask_babel import gettext as _

        count = len(items)
        if count == 0:
            return _("Your brief is being prepared. Check back shortly.")

        distinct_sources = len({i.source_id for i in items})
        fallback = _(
            "Today's brief: %(count)d stories from %(sources)d of your sources, "
            "clustered for clarity — not a raw feed dump.",
            count=count, sources=distinct_sources,
        )

        if not self.llm_available:
            if briefing.template and briefing.template.default_tone == 'calm_neutral':
                return _(
                    "Your %(cadence)s brief covers %(count)d stories from "
                    "%(sources)d sources. Focused on clarity and context.",
                    cadence=briefing.cadence, count=count, sources=distinct_sources,
                )
            return fallback

        headlines = []
        for item in items[:12]:
            source = item.source.name if item.source else 'Unknown'
            also = getattr(item, '_cluster_also_covered', None) or []
            if also:
                extra = ', '.join(n for n, _ in also[:3])
                headlines.append(f"- [{source} + {extra}] {item.title}")
            else:
                headlines.append(f"- [{source}] {item.title}")

        tone = briefing.tone or 'calm_neutral'
        tone_instructions = self._get_tone_instructions(tone)
        custom_prompt = briefing.custom_prompt or ''

        prompt = f"""Write a 2-sentence editorial intro for a personalised news brief named "{briefing.name}".

STORIES SELECTED TODAY:
{chr(10).join(headlines)}

Requirements:
- Preview the themes connecting these stories (not a generic "here are N stories")
- Calm, authoritative tone — no hype or clickbait
- WRITE IN: {self._llm_language}
- Do NOT list every headline; synthesise the day's through-line
- Max 45 words

WRITING STYLE: {tone_instructions}
{f'EDITORIAL FOCUS: {custom_prompt}' if custom_prompt else ''}

Return ONLY the intro prose, no labels."""

        content = self._call_llm(
            prompt,
            system_prompt="You are an editor writing the opening of a premium newsletter.",
            max_tokens=120,
            temperature=0.6,
        )
        if content and content.strip():
            return content.strip()
        return fallback
    
    def _generate_brief_item(
        self,
        brief_run: BriefRun,
        ingested_item: IngestedItem,
        position: int,
        briefing: Briefing
    ) -> BriefRunItem:
        """
        Generate a BriefRunItem from an IngestedItem.
        
        Args:
            brief_run: Parent BriefRun
            ingested_item: IngestedItem to generate from
            position: Display position
            briefing: Briefing configuration (for tone/filters)
        
        Returns:
            BriefRunItem instance
        """
        llm_content = self._generate_item_content(ingested_item, briefing)
        deeper_context = self._generate_deeper_context(ingested_item, briefing, llm_content)

        source_name = llm_content.get('source_name', '')
        if not source_name and ingested_item.source:
            source_name = ingested_item.source.name

        category = (llm_content.get('category') or 'UPDATE').upper()
        context_label = llm_content.get('context_label') or None
        context_insight = (llm_content.get('context_insight') or '').strip() or None

        # Cluster metadata lives on a real column now (cluster_also_covered)
        # instead of being marker-encoded into content_markdown.
        also_covered_raw = getattr(ingested_item, '_cluster_also_covered', None) or []
        cluster_also_covered = [
            {'name': name, 'url': url}
            for name, url in also_covered_raw
            if name
        ] or None

        # topic_category stores the raw category, and we *also* prefix the
        # headline with [CATEGORY] because the Jinja template and the markdown
        # output both rely on it as a stable, parseable label.
        headline = llm_content.get('headline', (ingested_item.title or '')[:200])

        return BriefRunItem(
            brief_run_id=brief_run.id,
            position=position,
            ingested_item_id=ingested_item.id,
            headline=f"[{category}] {headline}",
            summary_bullets=llm_content.get(
                'bullets',
                [ingested_item.content_text[:200] if ingested_item.content_text else ''],
            ),
            content_markdown=llm_content.get('markdown', ingested_item.content_text or ''),
            content_html=llm_content.get('html', ''),
            source_name=source_name,
            source_url=ingested_item.url,
            topic_category=category,
            selection_score=getattr(ingested_item, '_selection_score', None),
            deeper_context=deeper_context,
            cluster_also_covered=cluster_also_covered,
            context_label=context_label,
            context_insight=context_insight,
        )
    
    def _get_tone_instructions(self, tone: str) -> str:
        """Get writing style instructions based on tone setting."""
        tone_map = {
            'calm_neutral': 'Write in a calm, balanced, and objective tone. Avoid sensationalism. Present facts clearly without emotional language.',
            'formal': 'Write in a formal, professional tone suitable for business executives. Use precise language and maintain gravitas.',
            'conversational': 'Write in a friendly, approachable tone as if explaining to a colleague. Keep it engaging but informative.'
        }
        return tone_map.get(tone, tone_map['calm_neutral'])
    
    def _generate_item_content(
        self,
        ingested_item: IngestedItem,
        briefing: Briefing
    ) -> Dict[str, Any]:
        """
        Generate LLM content for an item with insights and actionable takeaways.
        
        Returns:
            Dict with: headline, bullets, markdown, html, source_name
        """
        # Get source name for attribution
        source_name = ingested_item.source.name if ingested_item.source else 'Unknown Source'
        also_covered = getattr(ingested_item, '_cluster_also_covered', None) or []
        also_line = ''
        if also_covered:
            names = [n for n, _ in also_covered if n]
            if names:
                also_line = f"\nALSO COVERED BY: {', '.join(names[:5])}"
        
        if not self.llm_available:
            # Fallback content
            return {
                'headline': ingested_item.title[:200],
                'bullets': [
                    ingested_item.content_text[:200] if ingested_item.content_text else ingested_item.title
                ],
                'markdown': ingested_item.content_text or ingested_item.title,
                'html': f"<p>{ingested_item.content_text or ingested_item.title}</p>",
                'source_name': source_name
            }
        
        # Build enhanced prompt using briefing settings
        tone = briefing.tone or 'calm_neutral'
        tone_instructions = self._get_tone_instructions(tone)
        custom_prompt = briefing.custom_prompt or ''
        
        prompt = f"""Analyze this content and create an insightful brief summary.

WRITE THE OUTPUT IN: {self._llm_language}
(The category label and JSON keys stay in English — they are internal identifiers, not display copy.)

SOURCE: {source_name}{also_line}
TITLE: {ingested_item.title}
CONTENT: {ingested_item.content_text[:3000] if ingested_item.content_text else 'No content available'}

Create a summary that goes beyond just restating facts. Include:
1. A compelling headline (max 100 chars) that captures the key insight
2. A category label in ENGLISH (1-2 words, uppercase) like: POLICY, REGULATION, TECHNOLOGY, MARKETS, INFRASTRUCTURE, RESEARCH, ANALYSIS, SECURITY, SUSTAINABILITY, INNOVATION
3. 2-3 bullet points with:
   - The key facts
   - Why this matters (implications/significance)
   - What to watch for next (if applicable)
4. A brief "context" insight (1-2 sentences). The ``context_insight`` text is in the OUTPUT language. The ``context_label`` MUST stay in English and be one of exactly: "What This Means", "Key Challenge", "Market Impact", "Policy Context", "Why It Matters" — these are lookup keys, not display copy.
5. A brief analysis paragraph (2-3 sentences) explaining the broader context

WRITING STYLE: {tone_instructions}
{f'ADDITIONAL INSTRUCTIONS: {custom_prompt}' if custom_prompt else ''}

Respond in JSON format:
{{
  "headline": "string",
  "category": "string",
  "bullets": ["string", "string", "string"],
  "context_label": "string",
  "context_insight": "string",
  "markdown": "string"
}}"""
        
        content = self._call_llm(
            prompt,
            system_prompt="You are a helpful assistant that creates clear, neutral summaries.",
            max_tokens=500,
            temperature=0.7
        )
        
        if content:
            try:
                result = extract_json(content)
                if result:
                    html = self._markdown_to_html_simple(result.get('markdown', ''))
                    result['html'] = html
                    result['source_name'] = source_name
                    result['category'] = result.get('category', 'UPDATE').upper()
                    result['context_label'] = result.get('context_label', 'What This Means')
                    result['context_insight'] = result.get('context_insight', '')
                    return result
            except Exception as e:
                logger.error(f"LLM generation failed: {e}")
        
        # Fallback with premium structure
        return {
            'headline': ingested_item.title[:200],
            'category': 'UPDATE',
            'bullets': [ingested_item.content_text[:200] if ingested_item.content_text else ingested_item.title],
            'context_label': 'What This Means',
            'context_insight': '',
            'markdown': ingested_item.content_text or ingested_item.title,
            'html': f"<p>{ingested_item.content_text or ingested_item.title}</p>",
            'source_name': source_name
        }
    
    def _generate_key_takeaways(
        self,
        briefing: Briefing,
        ingested_items: List[IngestedItem]
    ) -> List[str]:
        """
        Generate cross-item synthesis - key takeaways from all stories.
        
        Returns:
            List of 3-5 key takeaway strings
        """
        if not self.llm_available or len(ingested_items) < 2:
            return []
        
        # Build summary of all items
        items_summary = []
        for item in ingested_items[:10]:
            source = item.source.name if item.source else 'Unknown'
            items_summary.append(f"- [{source}] {item.title}")
        
        tone = briefing.tone or 'calm_neutral'
        tone_instructions = self._get_tone_instructions(tone)
        custom_prompt = briefing.custom_prompt or ''
        
        prompt = f"""Based on these news stories, identify 3-5 KEY TAKEAWAYS - the overarching themes, patterns, or insights that emerge when looking at these stories together.

WRITE THE TAKEAWAYS IN: {self._llm_language}

STORIES:
{chr(10).join(items_summary)}

Create takeaways that:
- Synthesize across multiple stories (not just summarize one)
- Highlight emerging trends or patterns
- Provide actionable insights for readers
- Connect dots that might not be obvious

WRITING STYLE: {tone_instructions}
{f'ADDITIONAL INSTRUCTIONS: {custom_prompt}' if custom_prompt else ''}

Respond in JSON format:
{{
  "takeaways": ["insight 1", "insight 2", "insight 3"]
}}"""
        
        content = self._call_llm(
            prompt,
            system_prompt="You are an expert analyst who identifies patterns and synthesizes insights across multiple news stories.",
            max_tokens=400,
            temperature=0.7
        )
        
        if content:
            try:
                result = extract_json(content)
                if result and 'takeaways' in result:
                    return result['takeaways'][:5]
            except Exception as e:
                logger.error(f"Key takeaways generation failed: {e}")
        
        return []
    
    def _render_markdown(
        self,
        title: str,
        intro: str,
        key_takeaways: List[str],
        brief_run: BriefRun,
    ) -> str:
        """Render plain-text/markdown rendition of the brief — used as the
        editorial source for the email preheader and any text-only consumers."""
        lines = [f"# {title}", "", intro, ""]

        if key_takeaways:
            lines.append("## Key Takeaways")
            lines.append("")
            for takeaway in key_takeaways:
                lines.append(f"- {takeaway}")
            lines.append("")

        lines.append("## Today's Stories")
        lines.append("")

        for item in sorted(brief_run.items, key=lambda x: x.position or 0):
            # ``_category`` discarded; ``_`` is reserved for gettext at module scope.
            _category, headline = self._parse_item_category_headline(item)
            lines.append(f"### {headline}")
            if item.summary_bullets:
                for bullet in item.summary_bullets:
                    lines.append(f"- {bullet}")
            if item.context_insight:
                lines.append("")
                lines.append(
                    f"_{item.context_label or 'What This Means'}:_ {item.context_insight}"
                )
            if item.content_markdown:
                lines.append("")
                lines.append(item.content_markdown)
            if item.cluster_also_covered:
                names = ', '.join(
                    c.get('name', '') for c in item.cluster_also_covered if c.get('name')
                )
                if names:
                    lines.append("")
                    lines.append(f"_Also covered by: {names}_")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _parse_item_category_headline(item: BriefRunItem) -> tuple[str, str]:
        headline = item.headline or ''
        category = (item.topic_category or 'UPDATE').upper()
        if headline.startswith('[') and ']' in headline:
            bracket_end = headline.index(']')
            category = headline[1:bracket_end].upper()
            headline = headline[bracket_end + 2:].strip()
        return category, headline

    # Editorial palette used by the Jinja template. Keep these together with
    # the generator so a designer changing colours has one obvious place to
    # look — the template just renders against `category_colors[item.category]`.
    CATEGORY_COLORS = {
        'POLICY': '#1e40af', 'REGULATION': '#dc2626', 'TECHNOLOGY': '#7c3aed',
        'MARKETS': '#059669', 'INFRASTRUCTURE': '#d97706', 'RESEARCH': '#0891b2',
        'ANALYSIS': '#6366f1', 'SECURITY': '#be123c', 'SUSTAINABILITY': '#059669',
        'INNOVATION': '#7c3aed', 'UPDATE': None,  # filled in with accent_color at render time
    }
    CONTEXT_BOX_COLORS = {
        'What This Means': ('#f0fdfa', '#115e59'),
        'Key Challenge':   ('#fffbeb', '#92400e'),
        'Market Impact':   ('#f0fdf4', '#166534'),
        'Policy Context':  ('#eff6ff', '#1e40af'),
        'Why It Matters':  ('#faf5ff', '#6b21a8'),
    }

    def _build_section_buckets(
        self, brief_run: BriefRun, briefing: Briefing,
    ) -> List[Tuple[str, List[BriefRunItem]]]:
        """Bucket items into editorial sections per the template config.

        Returns ordered ``[(section_name, [items])]``. When the template
        defines no sections (or items don't match any), returns a single
        ``("Today's Stories", items)`` bucket so the renderer stays simple.
        """
        items = sorted(brief_run.items, key=lambda x: x.position or 0)
        sections = get_sections_for_briefing(briefing)
        if not sections:
            return [(_l("Today's Stories"), items)] if items else []

        buckets: Dict[str, List[BriefRunItem]] = {name: [] for name, _labels in sections}
        other: List[BriefRunItem] = []
        for item in items:
            # ``_headline`` discarded; we only need the category for bucketing.
            category, _headline = self._parse_item_category_headline(item)
            placed = False
            for section_name, labels in sections:
                if category in labels:
                    buckets[section_name].append(item)
                    placed = True
                    break
            if not placed:
                other.append(item)

        result: List[Tuple[str, List[BriefRunItem]]] = []
        for section_name, _labels in sections:
            if buckets[section_name]:
                result.append((section_name, buckets[section_name]))
        if other:
            result.append((_l("More Stories"), other))
        return result

    def _build_source_roster(
        self, brief_run: BriefRun, briefing: Briefing,
    ) -> Dict[str, Any]:
        """Aggregate the source list shown in the email footer.

        Counts each distinct source name across selected items and their
        clusters; ``configured`` is the count the user set up. Templates
        only render this when ``used`` is non-empty.
        """
        used_names: List[str] = []
        seen: set = set()

        def _add(name: Optional[str]) -> None:
            if not name:
                return
            key = name.lower()
            if key in seen:
                return
            seen.add(key)
            used_names.append(name)

        for item in brief_run.items:
            name = item.source_name or ''
            if not name and item.ingested_item and item.ingested_item.source:
                name = item.ingested_item.source.name
            _add(name)
            for sibling in (item.cluster_also_covered or []):
                _add(sibling.get('name'))

        return {
            'used': used_names,
            'configured': len(briefing.sources or []),
        }

    def _render_html(
        self,
        *,
        brief_run: BriefRun,
        briefing: Briefing,
        intro_text: str,
        key_takeaways: List[str],
        coverage_block: Optional[CoverageBlock],
        underreported: Optional[UnderreportedPick],
    ) -> str:
        """Render the brief body via the canonical Jinja partial.

        The body is stored in ``brief_run.draft_html``. The email shell
        (``emails/brief_run.html``) embeds it; the web reader renders
        the same partial. One source of truth for visual design.
        """
        from flask_babel import force_locale
        from app.briefing.briefing_locale import resolve_briefing_locale

        locale_str = resolve_briefing_locale(briefing)
        with force_locale(locale_str):
            return render_template(
                'briefing/_paid_brief_body.html',
                brief_run=brief_run,
                briefing=briefing,
                accent_color=briefing.accent_color or '#1e40af',
                intro_text=intro_text or '',
                key_takeaways=key_takeaways or [],
                coverage_block=coverage_block,
                underreported=underreported,
                section_buckets=self._build_section_buckets(brief_run, briefing),
                source_roster=self._build_source_roster(brief_run, briefing),
                category_colors=self.CATEGORY_COLORS,
                context_box_colors=self.CONTEXT_BOX_COLORS,
                parse_item_headline=self._parse_item_category_headline,
            )

    def _generate_deeper_context(
        self,
        ingested_item: IngestedItem,
        briefing: Briefing,
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
            
            source_name = ingested_item.source.name if ingested_item.source else 'Unknown Source'
            content_text = ingested_item.content_text[:4000] if ingested_item.content_text else ingested_item.title
            
            tone = briefing.tone or 'calm_neutral'
            tone_instructions = self._get_tone_instructions(tone)
            
            prompt = f"""You are a senior news analyst providing deeper context for a news story.

TODAY'S DATE: {date_context}
CURRENT YEAR: {current_year}

SOURCE: {source_name}
TITLE: {ingested_item.title}

EXISTING SUMMARY:
Headline: {existing_content.get('headline', 'N/A')}
Key Points: {chr(10).join(f"- {b}" for b in existing_content.get('bullets', []))}

FULL CONTENT:
{content_text}

Generate a deeper dive (3-4 paragraphs) that provides:

1. HISTORICAL CONTEXT: What led to this moment? What similar events happened before?
2. BROADER IMPLICATIONS: What does this mean for related issues, sectors, or regions?
3. KEY PLAYERS: Who are the main actors, organizations, or institutions involved?
4. WHAT TO WATCH: What developments should readers monitor in the coming days/weeks?

WRITING STYLE: {tone_instructions}

Guidelines:
- Write in: {self._llm_language}
- Be specific with numbers, dates, and names
- Provide genuine insight, not just restate the summary
- Connect this story to larger trends or patterns
- Keep tone calm and analytical
- Avoid speculation - stick to what's known from sources

Return ONLY the deeper context text (no JSON, no labels, just the prose)."""

            content = self._call_llm(
                prompt,
                system_prompt="You are a news analyst providing deeper context.",
                max_tokens=800,
                temperature=0.7
            )
            
            if not content:
                return None
            
            context = content.strip()
            
            # Limit length (roughly 800-1200 words)
            if context and len(context) > 2000:
                truncated = context[:2000]
                last_period = truncated.rfind('.')
                if last_period > 1500:
                    context = truncated[:last_period + 1]
                else:
                    context = truncated + "..."
            
            return context if context else None
            
        except Exception as e:
            logger.warning(f"Failed to generate deeper context for item {ingested_item.id}: {e}")
            return None
    
    def _markdown_to_html_simple(self, markdown: str) -> str:
        """Simple markdown to HTML converter"""
        html = markdown.replace('\n', '<br>')
        return f"<p>{html}</p>"

def generate_brief_run_for_briefing(
    briefing_id: int,
    scheduled_at: Optional[datetime] = None,
    *,
    skip_warmup: bool = False,
) -> Optional[BriefRun]:
    """
    Convenience function to generate a BriefRun for a briefing.
    
    Args:
        briefing_id: Briefing ID
        scheduled_at: When to schedule (defaults to now)
        skip_warmup: Set when caller already ran source warm-up (first-brief path).
    
    Returns:
        BriefRun instance or None
    """
    from flask import current_app
    from app.briefing.source_warmup import warm_up_briefing_sources

    briefing = db.session.get(Briefing, briefing_id)
    if not briefing:
        logger.error(f"Briefing {briefing_id} not found")
        return None
    
    if briefing.status != 'active':
        logger.info(f"Briefing {briefing_id} is not active, skipping")
        return None

    if not skip_warmup:
        budget = float(current_app.config.get('BRIEFING_SOURCE_WARMUP_SECONDS', 60))
        warm_up_briefing_sources(briefing, budget_seconds=budget)
    
    if scheduled_at is None:
        scheduled_at = utcnow_naive()
    
    generator = BriefingGenerator()
    return generator.generate_brief_run(briefing, scheduled_at)
