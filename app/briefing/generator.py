"""
Briefing Generator

Generalized brief generator for multi-tenant briefings.
Works with IngestedItem instead of TrendingTopic.
Creates BriefRun instead of DailyBrief.
"""

import os
import logging
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from app import db
from app.models import (
    Briefing, BriefRun, BriefRunItem, IngestedItem, InputSource
)
from app.trending.scorer import extract_json, get_system_api_key

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
        
        if not self.llm_available:
            logger.warning("No LLM API key found. Brief will use fallback content generation.")
    
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
            # Select items if not provided
            if ingested_items is None:
                ingested_items = self._select_items_for_briefing(briefing)
            
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
            
            # Create BriefRun
            brief_run = BriefRun(
                briefing_id=briefing.id,
                scheduled_at=scheduled_at,
                status='generated_draft' if briefing.mode == 'approval_required' else 'approved',
                generated_at=datetime.utcnow()
            )
            
            db.session.add(brief_run)
            db.session.flush()  # Get brief_run.id
            
            # Generate content
            title = self._generate_brief_title(briefing, ingested_items)
            intro_text = self._generate_intro_text(briefing, ingested_items)
            
            # Use briefing's max_items setting (default 10, capped at 20)
            max_items = min(briefing.max_items or 10, 20)
            items_created = 0
            for position, item in enumerate(ingested_items[:max_items], start=1):
                try:
                    run_item = self._generate_brief_item(brief_run, item, position, briefing)
                    db.session.add(run_item)
                    items_created += 1
                except Exception as e:
                    logger.error(f"Failed to generate item for IngestedItem {item.id}: {e}")
                    continue
            
            if items_created == 0:
                logger.warning(f"No items generated for BriefRun {brief_run.id}")
                db.session.rollback()
                return None
            
            # Generate key takeaways synthesis (cross-item insights)
            key_takeaways = self._generate_key_takeaways(briefing, ingested_items[:max_items])
            
            # Generate markdown and HTML with improved structure
            brief_run.draft_markdown = self._generate_markdown(brief_run, title, intro_text, key_takeaways)
            brief_run.draft_html = self._generate_structured_html(brief_run, title, intro_text, key_takeaways, briefing)
            
            # If auto_send, also set approved content
            if briefing.mode == 'auto_send':
                brief_run.approved_markdown = brief_run.draft_markdown
                brief_run.approved_html = brief_run.draft_html
                brief_run.status = 'approved'
            
            db.session.commit()

            logger.info(f"Generated BriefRun {brief_run.id} for briefing {briefing.name} ({items_created} items)")

            # Send notification if approval is required
            if briefing.mode == 'approval_required':
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
    
    def _select_items_for_briefing(self, briefing: Briefing, limit: int = None) -> List[IngestedItem]:
        """
        Select items from briefing's sources using a two-phase approach:
        1. Global ranking: Score all items based on topic preferences, include keywords, and source priority
        2. Fair selection: Ensure source diversity while respecting global scores
        
        Args:
            briefing: Briefing configuration
            limit: Maximum number of items to select
        
        Returns:
            List of IngestedItem instances with diverse sources, prioritized by user preferences
        """
        from datetime import timedelta
        from collections import defaultdict
        import re
        
        # Get all sources for this briefing with their priorities
        source_priorities = {bs.source_id: getattr(bs, 'priority', 1) or 1 for bs in briefing.sources}
        source_ids = list(source_priorities.keys())
        if not source_ids:
            return []
        
        # Use briefing's max_items setting, or default to 10
        if limit is None:
            limit = min(briefing.max_items or 10, 20)
        
        # Get user's content filters
        filters = briefing.filters_json or {}
        include_keywords = [k.lower().strip() for k in filters.get('include_keywords', []) if k.strip()]
        exclude_keywords = [k.lower().strip() for k in filters.get('exclude_keywords', []) if k.strip()]
        
        # Get topic preferences (topic -> weight 1-3)
        topic_preferences = briefing.topic_preferences or {}
        
        # Get recent items from these sources (last 7 days)
        cutoff = datetime.utcnow() - timedelta(days=7)
        
        all_items = IngestedItem.query.filter(
            IngestedItem.source_id.in_(source_ids),
            IngestedItem.fetched_at >= cutoff
        ).order_by(
            IngestedItem.published_at.desc().nullslast(),
            IngestedItem.fetched_at.desc()
        ).limit(limit * 15).all()
        
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
                return False  # No match bonus when no include keywords
            return any(kw in text for kw in include_keywords)
        
        def calculate_score(item: IngestedItem, text: str) -> float:
            """
            Calculate global relevance score for an item.
            Score components:
            - Base: 1.0
            - Include keyword match: +5.0 (significant boost)
            - Topic preference match: +weight (1-3 per topic)
            - Source priority: +priority (1-3)
            """
            score = 1.0
            
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
            
            return score
        
        # Phase 1: Score and filter all items
        scored_items = []
        for item in all_items:
            text = get_text(item)
            
            # Apply exclude filter (hard filter)
            if should_exclude(text):
                continue
            
            score = calculate_score(item, text)
            scored_items.append((item, score))
        
        # Sort by score (highest first), then by recency
        scored_items.sort(key=lambda x: (x[1], x[0].published_at or datetime.min), reverse=True)
        
        # Phase 2: Fair selection with source diversity
        selected_items = []
        seen_headlines = set()
        source_counts = defaultdict(int)
        max_per_source = max(2, (limit // len(source_ids)) + 1) if source_ids else limit
        
        def normalize_headline(title: str) -> str:
            """Normalize headline for dedup comparison"""
            normalized = re.sub(r'[^\w\s]', '', title.lower())
            words = [w for w in normalized.split() if len(w) > 3][:5]
            return ' '.join(sorted(words))
        
        # First pass: select top-scored items with diversity constraints
        for item, score in scored_items:
            if len(selected_items) >= limit:
                break
            
            # Check for duplicate headlines
            normalized = normalize_headline(item.title)
            if normalized in seen_headlines:
                continue
            
            # Enforce source diversity (soft limit per source in first pass)
            if source_counts[item.source_id] >= max_per_source:
                continue
            
            seen_headlines.add(normalized)
            selected_items.append(item)
            source_counts[item.source_id] += 1
        
        # Second pass: if we need more items, relax source limits
        if len(selected_items) < limit:
            for item, score in scored_items:
                if len(selected_items) >= limit:
                    break
                
                normalized = normalize_headline(item.title)
                if normalized in seen_headlines:
                    continue
                
                seen_headlines.add(normalized)
                selected_items.append(item)
        
        logger.info(
            f"Selected {len(selected_items)} items from {len(set(i.source_id for i in selected_items))} sources "
            f"for briefing {briefing.id} (topic_prefs: {len(topic_preferences)}, "
            f"include_kw: {len(include_keywords)}, exclude_kw: {len(exclude_keywords)})"
        )
        
        return selected_items
    
    def _generate_brief_title(self, briefing: Briefing, items: List[IngestedItem]) -> str:
        """Generate brief title"""
        day_name = datetime.now().strftime('%A')
        return f"{briefing.name} - {day_name}"
    
    def _generate_intro_text(self, briefing: Briefing, items: List[IngestedItem]) -> str:
        """Generate intro text based on briefing tone"""
        count = len(items)
        
        if briefing.template and briefing.template.default_tone == 'calm_neutral':
            return f"Your {briefing.cadence} brief covers {count} stories from your selected sources. Focused on clarity and context."
        
        return f"Your {briefing.cadence} brief: {count} stories from your sources."
    
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
        # Generate content via LLM
        llm_content = self._generate_item_content(ingested_item, briefing)
        
        # Get source name for denormalized storage
        source_name = llm_content.get('source_name', '')
        if not source_name and ingested_item.source:
            source_name = ingested_item.source.name
        
        # Store category and context with the content for premium styling
        category = llm_content.get('category', 'UPDATE')
        context_label = llm_content.get('context_label', 'What This Means')
        context_insight = llm_content.get('context_insight', '')
        
        # Store metadata in markdown for later use in HTML generation
        enhanced_markdown = llm_content.get('markdown', ingested_item.content_text or '')
        if context_insight:
            enhanced_markdown = f"[{context_label}] {context_insight}\n\n{enhanced_markdown}"
        
        # Create item with category info embedded
        run_item = BriefRunItem(
            brief_run_id=brief_run.id,
            position=position,
            ingested_item_id=ingested_item.id,
            headline=f"[{category}] " + llm_content.get('headline', ingested_item.title[:200]),
            summary_bullets=llm_content.get('bullets', [ingested_item.content_text[:200] if ingested_item.content_text else '']),
            content_markdown=enhanced_markdown,
            content_html=llm_content.get('html', ''),
            source_name=source_name,
            source_url=ingested_item.url  # Link to original article
        )
        
        return run_item
    
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
        
        prompt = f"""Analyze this content and create an insightful brief summary:

SOURCE: {source_name}
TITLE: {ingested_item.title}
CONTENT: {ingested_item.content_text[:3000] if ingested_item.content_text else 'No content available'}

Create a summary that goes beyond just restating facts. Include:
1. A compelling headline (max 100 chars) that captures the key insight
2. A category label (1-2 words, uppercase) like: POLICY, REGULATION, TECHNOLOGY, MARKETS, INFRASTRUCTURE, RESEARCH, ANALYSIS, SECURITY, SUSTAINABILITY, INNOVATION
3. 2-3 bullet points with:
   - The key facts
   - Why this matters (implications/significance)
   - What to watch for next (if applicable)
4. A brief "context" insight (1-2 sentences) explaining broader implications - label it as one of: "What This Means", "Key Challenge", "Market Impact", "Policy Context", or "Why It Matters"
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
        
        try:
            if self.provider == 'openai':
                import openai
                client = openai.OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that creates clear, neutral summaries."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=500
                )
                content = response.choices[0].message.content
            elif self.provider == 'anthropic':
                import anthropic
                client = anthropic.Anthropic(api_key=self.api_key)
                response = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=500,
                    system="You are a helpful assistant that creates clear, neutral summaries.",
                    messages=[{"role": "user", "content": prompt}]
                )
                content_block = response.content[0]
                content = getattr(content_block, 'text', None) or str(content_block)
            else:
                content = None
            
            if content:
                result = extract_json(content)
                if result:
                    # Convert markdown to HTML (simple)
                    html = self._markdown_to_html_simple(result.get('markdown', ''))
                    result['html'] = html
                    result['source_name'] = source_name
                    # Ensure category and context fields have defaults
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
        
        try:
            if self.provider == 'openai':
                import openai
                client = openai.OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are an expert analyst who identifies patterns and synthesizes insights across multiple news stories."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=400
                )
                content = response.choices[0].message.content
            elif self.provider == 'anthropic':
                import anthropic
                client = anthropic.Anthropic(api_key=self.api_key)
                response = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=400,
                    system="You are an expert analyst who identifies patterns and synthesizes insights across multiple news stories.",
                    messages=[{"role": "user", "content": prompt}]
                )
                content_block = response.content[0]
                content = getattr(content_block, 'text', None) or str(content_block)
            else:
                return []
            
            if content:
                result = extract_json(content)
                if result and 'takeaways' in result:
                    return result['takeaways'][:5]
        except Exception as e:
            logger.error(f"Key takeaways generation failed: {e}")
        
        return []
    
    def _generate_markdown(self, brief_run: BriefRun, title: str, intro: str, key_takeaways: List[str] = None) -> str:
        """Generate markdown content for the brief run with key takeaways"""
        lines = [f"# {title}", "", intro, ""]
        
        # Add key takeaways section if available
        if key_takeaways:
            lines.append("## Key Takeaways")
            lines.append("")
            for takeaway in key_takeaways:
                lines.append(f"- {takeaway}")
            lines.append("")
        
        lines.append("## Today's Stories")
        lines.append("")
        
        for item in sorted(brief_run.items, key=lambda x: x.position or 0):
            lines.append(f"### {item.headline}")
            if item.summary_bullets:
                for bullet in item.summary_bullets:
                    lines.append(f"- {bullet}")
            if item.content_markdown:
                lines.append("")
                lines.append(item.content_markdown)
            lines.append("")
        
        return "\n".join(lines)
    
    def _generate_structured_html(
        self,
        brief_run: BriefRun,
        title: str,
        intro: str,
        key_takeaways: List[str],
        briefing: Briefing
    ) -> str:
        """Generate premium-styled HTML matching world-class newsletter standards"""
        accent_color = briefing.accent_color or '#1e40af'
        
        # Category color palette for visual variety
        category_colors = {
            'POLICY': '#1e40af', 'REGULATION': '#dc2626', 'TECHNOLOGY': '#7c3aed',
            'MARKETS': '#059669', 'INFRASTRUCTURE': '#d97706', 'RESEARCH': '#0891b2',
            'ANALYSIS': '#6366f1', 'SECURITY': '#be123c', 'SUSTAINABILITY': '#059669',
            'INNOVATION': '#7c3aed', 'UPDATE': accent_color
        }
        
        # Context box color palette
        context_box_colors = {
            'What This Means': ('#f0fdfa', '#115e59'),
            'Key Challenge': ('#fffbeb', '#92400e'),
            'Market Impact': ('#f0fdf4', '#166534'),
            'Policy Context': ('#eff6ff', '#1e40af'),
            'Why It Matters': ('#faf5ff', '#6b21a8'),
        }
        
        # Build key takeaways HTML with premium styling
        takeaways_html = ''
        if key_takeaways:
            takeaways_items = ''.join([f'<li style="margin-bottom: 10px; padding-left: 8px; color: #1f2937;">{t}</li>' for t in key_takeaways])
            takeaways_html = f'''
            <div style="background-color: #f8fafc; border-left: 4px solid {accent_color}; padding: 20px 24px; margin-bottom: 28px; border-radius: 0 8px 8px 0;">
                <h2 style="font-family: Georgia, 'Times New Roman', serif; color: {accent_color}; font-size: 18px; font-weight: 700; margin: 0 0 14px 0;">Key Takeaways</h2>
                <ul style="margin: 0; padding-left: 20px; line-height: 1.7; font-size: 15px;">
                    {takeaways_items}
                </ul>
            </div>
            '''
        
        # Build stories HTML with premium newsletter styling
        stories_html = ''
        for idx, item in enumerate(sorted(brief_run.items, key=lambda x: x.position or 0)):
            # Get source name
            source_name = item.source_name or ''
            if not source_name and item.ingested_item and item.ingested_item.source:
                source_name = item.ingested_item.source.name
            
            # Extract category from headline if embedded (format: "[CATEGORY] headline")
            headline = item.headline or ''
            category = 'UPDATE'
            if headline.startswith('[') and ']' in headline:
                bracket_end = headline.index(']')
                category = headline[1:bracket_end].upper()
                headline = headline[bracket_end + 2:].strip()  # Remove "[CATEGORY] " prefix
            
            category_color = category_colors.get(category, accent_color)
            
            # Category label with premium styling
            category_html = f'''
            <p style="margin: 0 0 8px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: {category_color};">{category}</p>
            '''
            
            # Headline with Georgia serif font
            headline_html = f'''
            <h3 style="margin: 0 0 12px 0; font-family: Georgia, 'Times New Roman', serif; font-size: 18px; font-weight: 700; color: #0f172a; line-height: 1.3;">{headline}</h3>
            '''
            
            # Bullets with enhanced styling
            bullets_html = ''
            if item.summary_bullets:
                bullets_items = ''.join([f'<li style="margin-bottom: 8px; color: #374151;">{b}</li>' for b in item.summary_bullets])
                bullets_html = f'<ul style="margin: 0 0 16px 0; padding-left: 20px; line-height: 1.65; font-size: 15px;">{bullets_items}</ul>'
            
            # Extract context from content_markdown if embedded (format: "[Label] insight\n\nrest")
            context_html = ''
            content_markdown = item.content_markdown or ''
            context_label = 'What This Means'
            context_insight = ''
            
            if content_markdown.startswith('[') and ']' in content_markdown:
                bracket_end = content_markdown.index(']')
                context_label = content_markdown[1:bracket_end]
                rest = content_markdown[bracket_end + 2:]
                if '\n\n' in rest:
                    context_insight, content_markdown = rest.split('\n\n', 1)
                else:
                    context_insight = rest
                    content_markdown = ''
            
            bg_color, text_color = context_box_colors.get(context_label, ('#f0fdfa', '#115e59'))
            
            if context_insight:
                # Create premium callout box with extracted context
                context_html = f'''
                <div style="background-color: {bg_color}; border-radius: 6px; padding: 14px 16px; margin: 16px 0 0 0;">
                    <p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; color: {text_color}; text-transform: uppercase;">{context_label}</p>
                    <p style="margin: 0; font-size: 14px; line-height: 1.6; color: #374151;">{context_insight[:300]}</p>
                </div>
                '''
            
            # Render remaining analysis/narrative body if available
            analysis_html = ''
            if content_markdown and content_markdown.strip():
                # Convert markdown to simple HTML paragraphs
                analysis_text = content_markdown.strip()[:500]
                analysis_html = f'''
                <p style="color: #4b5563; font-size: 15px; line-height: 1.65; margin: 16px 0 0 0; font-style: italic;">
                    {analysis_text}
                </p>
                '''
            elif item.content_html and item.content_html.strip():
                # Use pre-rendered HTML if available and no extracted markdown
                analysis_html = f'''
                <div style="color: #4b5563; font-size: 15px; line-height: 1.65; margin: 16px 0 0 0; font-style: italic;">
                    {item.content_html}
                </div>
                '''
            
            # Source attribution with clickable link
            source_html = ''
            source_url = item.source_url or ''
            if not source_url and item.ingested_item:
                source_url = item.ingested_item.url or ''
            
            if source_name:
                if source_url:
                    source_html = f'''
                <p style="margin: 12px 0 0 0; font-size: 12px; color: #6b7280;">
                    Source: <a href="{source_url}" style="color: {accent_color}; text-decoration: underline;" target="_blank">{source_name}</a>
                </p>
                '''
                else:
                    source_html = f'''
                <p style="margin: 12px 0 0 0; font-size: 12px; color: #6b7280;">
                    Source: <span style="color: #374151;">{source_name}</span>
                </p>
                '''
            
            stories_html += f'''
            <div style="border-bottom: 1px solid #e5e7eb; padding-bottom: 24px; margin-bottom: 24px;">
                {category_html}
                {headline_html}
                {bullets_html}
                {context_html}
                {analysis_html}
                {source_html}
            </div>
            '''
        
        # Full HTML structure with premium styling
        html = f'''
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
            <p style="color: #4b5563; font-size: 16px; line-height: 1.75; margin-bottom: 28px;">{intro}</p>
            {takeaways_html}
            <h2 style="font-family: Georgia, 'Times New Roman', serif; color: #0f172a; font-size: 22px; font-weight: 700; margin: 28px 0 20px 0; padding-bottom: 12px; border-bottom: 2px solid {accent_color};">Today's Stories</h2>
            {stories_html}
        </div>
        '''
        
        return html
    
    def _markdown_to_html(self, markdown: str) -> str:
        """Convert markdown to HTML (simple implementation)"""
        # Simple markdown to HTML (can be enhanced with markdown library)
        html = markdown.replace('\n# ', '\n<h1>').replace('\n## ', '\n<h2>')
        html = html.replace('\n- ', '\n<li>')
        # Wrap in basic structure
        return f"<div class='brief-content'>{html}</div>"
    
    def _markdown_to_html_simple(self, markdown: str) -> str:
        """Simple markdown to HTML converter"""
        html = markdown.replace('\n', '<br>')
        return f"<p>{html}</p>"


def generate_brief_run_for_briefing(
    briefing_id: int,
    scheduled_at: Optional[datetime] = None
) -> Optional[BriefRun]:
    """
    Convenience function to generate a BriefRun for a briefing.
    
    Args:
        briefing_id: Briefing ID
        scheduled_at: When to schedule (defaults to now)
    
    Returns:
        BriefRun instance or None
    """
    briefing = Briefing.query.get(briefing_id)
    if not briefing:
        logger.error(f"Briefing {briefing_id} not found")
        return None
    
    if briefing.status != 'active':
        logger.info(f"Briefing {briefing_id} is not active, skipping")
        return None
    
    if scheduled_at is None:
        scheduled_at = datetime.utcnow()
    
    generator = BriefingGenerator()
    return generator.generate_brief_run(briefing, scheduled_at)
