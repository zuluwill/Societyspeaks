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
            
            # Generate items (limit to 5 for readability)
            items_created = 0
            for position, item in enumerate(ingested_items[:5], start=1):
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
            
            # Generate markdown and HTML
            brief_run.draft_markdown = self._generate_markdown(brief_run, title, intro_text)
            brief_run.draft_html = self._markdown_to_html(brief_run.draft_markdown)
            
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
    
    def _select_items_for_briefing(self, briefing: Briefing, limit: int = 5) -> List[IngestedItem]:
        """
        Select items from briefing's sources.
        
        Args:
            briefing: Briefing configuration
            limit: Maximum number of items to select
        
        Returns:
            List of IngestedItem instances
        """
        # Get all sources for this briefing
        source_ids = [bs.source_id for bs in briefing.sources]
        if not source_ids:
            return []
        
        # Get recent items from these sources (last 7 days)
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=7)
        
        items = IngestedItem.query.filter(
            IngestedItem.source_id.in_(source_ids),
            IngestedItem.fetched_at >= cutoff
        ).order_by(
            IngestedItem.published_at.desc().nullslast(),
            IngestedItem.fetched_at.desc()
        ).limit(limit * 3).all()  # Get more than needed, then filter
        
        # Apply briefing filters if any
        if briefing.template and briefing.template.default_filters:
            filters = briefing.template.default_filters
            keywords = filters.get('topics', [])
            
            if keywords:
                # Filter items by keywords in title or content
                filtered_items = []
                for item in items:
                    text = f"{item.title} {item.content_text or ''}".lower()
                    if any(keyword.lower() in text for keyword in keywords):
                        filtered_items.append(item)
                items = filtered_items[:limit]
            else:
                items = items[:limit]
        else:
            items = items[:limit]
        
        return items
    
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
        
        # Create item
        run_item = BriefRunItem(
            brief_run_id=brief_run.id,
            position=position,
            ingested_item_id=ingested_item.id,
            headline=llm_content.get('headline', ingested_item.title[:200]),
            summary_bullets=llm_content.get('bullets', [ingested_item.content_text[:200] if ingested_item.content_text else '']),
            content_markdown=llm_content.get('markdown', ingested_item.content_text or ''),
            content_html=llm_content.get('html', '')
        )
        
        return run_item
    
    def _generate_item_content(
        self,
        ingested_item: IngestedItem,
        briefing: Briefing
    ) -> Dict[str, Any]:
        """
        Generate LLM content for an item.
        
        Returns:
            Dict with: headline, bullets, markdown, html
        """
        if not self.llm_available:
            # Fallback content
            return {
                'headline': ingested_item.title[:200],
                'bullets': [
                    ingested_item.content_text[:200] if ingested_item.content_text else ingested_item.title
                ],
                'markdown': ingested_item.content_text or ingested_item.title,
                'html': f"<p>{ingested_item.content_text or ingested_item.title}</p>"
            }
        
        # Build prompt
        tone = briefing.template.default_tone if briefing.template else 'calm_neutral'
        
        prompt = f"""Generate a brief summary for this content:

Title: {ingested_item.title}
Content: {ingested_item.content_text[:2000] if ingested_item.content_text else 'No content available'}

Generate:
1. A concise headline (max 100 chars)
2. 2-3 bullet points summarizing key points
3. A brief markdown paragraph (2-3 sentences)

Tone: {tone}
Format: JSON with keys: headline, bullets (array), markdown
"""
        
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
                    return result
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
        
        # Fallback
        return {
            'headline': ingested_item.title[:200],
            'bullets': [ingested_item.content_text[:200] if ingested_item.content_text else ingested_item.title],
            'markdown': ingested_item.content_text or ingested_item.title,
            'html': f"<p>{ingested_item.content_text or ingested_item.title}</p>"
        }
    
    def _generate_markdown(self, brief_run: BriefRun, title: str, intro: str) -> str:
        """Generate markdown content for the brief run"""
        lines = [f"# {title}", "", intro, ""]
        
        for item in brief_run.items.order_by(BriefRunItem.position):
            lines.append(f"## {item.headline}")
            if item.summary_bullets:
                for bullet in item.summary_bullets:
                    lines.append(f"- {bullet}")
            if item.content_markdown:
                lines.append("")
                lines.append(item.content_markdown)
            lines.append("")
        
        return "\n".join(lines)
    
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
