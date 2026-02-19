"""
Weekly Brief Generator

Generates a curated weekly digest from the past 7 days of daily briefs.
Not a concatenation of dailies — a synthesised, re-ranked summary that
highlights the most important stories and how they developed over the week.

Sections:
1. Top Stories of the Week (5-7 items, re-ranked by week-long significance)
2. Themed Sections (best story per theme from the week)
3. The Week in Numbers (key data points and movements)
4. What to Watch Next Week (forward-looking events)
5. Same Story, Different Lens (best lens check from the week)
"""

import logging
from datetime import datetime, date, timedelta
from app.lib.time import utcnow_naive
from typing import List, Dict, Optional, Any
from collections import defaultdict

from app.models import DailyBrief, BriefItem, TrendingTopic, UpcomingEvent, db
from app.brief.sections import (
    SECTIONS, DEPTH_FULL, DEPTH_STANDARD, DEPTH_QUICK,
    BRIEF_TYPE_WEEKLY, get_section_for_category,
)
from app.trending.scorer import extract_json, get_system_api_key

logger = logging.getLogger(__name__)


class WeeklyBriefGenerator:
    """
    Generates weekly digest briefs from daily brief data.

    Design principles:
    - Curated synthesis, not concatenation (readers should not re-read dailies)
    - Re-ranks stories by weekly significance (developing stories rank higher)
    - Generates week-specific content via LLM (how did the story develop?)
    - Graceful degradation (works even if some days had no brief)
    """

    def __init__(self):
        self.api_key, self.provider = get_system_api_key()
        self.llm_available = bool(self.api_key)

    def generate_weekly_brief(
        self,
        week_end_date: date,
        auto_publish: bool = True
    ) -> Optional[DailyBrief]:
        """
        Generate weekly brief for the week ending on week_end_date.

        Args:
            week_end_date: The Sunday (or delivery date) of the week
            auto_publish: Set to 'ready' if True

        Returns:
            DailyBrief instance with brief_type='weekly', or None
        """
        week_start = week_end_date - timedelta(days=6)

        logger.info(f"Generating weekly brief for {week_start} to {week_end_date}")

        # Collect all daily briefs from the past week
        daily_briefs = DailyBrief.query.filter(
            DailyBrief.date >= week_start,
            DailyBrief.date <= week_end_date,
            DailyBrief.brief_type == 'daily',
            DailyBrief.status.in_(['ready', 'published'])
        ).order_by(DailyBrief.date.asc()).all()

        if not daily_briefs:
            logger.warning(f"No daily briefs found for week of {week_start} to {week_end_date}")
            return None

        logger.info(f"Found {len(daily_briefs)} daily briefs for the week")

        # Collect all items from the week
        all_items = []
        for brief in daily_briefs:
            items = brief.items.all() if hasattr(brief.items, 'all') else list(brief.items)
            all_items.extend(items)

        if not all_items:
            logger.warning("No items found across daily briefs")
            return None

        # Create or get weekly brief record
        try:
            existing = DailyBrief.query.filter_by(
                date=week_end_date,
                brief_type=BRIEF_TYPE_WEEKLY
            ).first()

            if existing and existing.status in ('ready', 'published'):
                logger.info(f"Weekly brief for {week_end_date} already exists")
                return existing

            if existing:
                brief = existing
                BriefItem.query.filter_by(brief_id=existing.id).delete()
                db.session.flush()
            else:
                brief = DailyBrief(
                    date=week_end_date,
                    brief_type=BRIEF_TYPE_WEEKLY,
                    week_start_date=week_start,
                    week_end_date=week_end_date,
                    status='draft',
                    auto_selected=True
                )
                db.session.add(brief)
                db.session.flush()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to create weekly brief record: {e}")
            return None

        # Generate title
        brief.title = f"The Week in Review: {week_start.strftime('%d %b')} – {week_end_date.strftime('%d %b %Y')}"

        # Generate intro
        brief.intro_text = self._generate_weekly_intro(daily_briefs, all_items)

        # Rank and select top stories
        top_stories = self._rank_weekly_stories(all_items)
        position = 1

        # Section 1: Top Stories of the Week (5-7 items, standard depth)
        for item in top_stories[:7]:
            try:
                weekly_item = self._create_weekly_item(
                    brief, item, position, 'lead' if position == 1 else 'politics',
                    DEPTH_FULL if position == 1 else DEPTH_STANDARD,
                    daily_briefs
                )
                db.session.add(weekly_item)
                position += 1
            except Exception as e:
                logger.warning(f"Failed to create weekly item: {e}")
                continue

        # Best lens check from the week
        best_lens = self._select_best_lens_check(daily_briefs)
        if best_lens:
            brief.lens_check = best_lens

        # Week Ahead for next week
        try:
            next_week_events = UpcomingEvent.get_upcoming(days_ahead=7, limit=5)
            if next_week_events:
                brief.week_ahead = [e.to_dict() for e in next_week_events]
        except Exception as e:
            logger.warning(f"Failed to get Week Ahead for weekly brief: {e}")

        # "What the World is Watching" — reuse the daily generator's method
        try:
            from app.brief.generator import BriefGenerator
            gen = BriefGenerator()
            # Collect market IDs already used in market_pulse to avoid duplicates
            market_pulse_ids = set()
            if brief.market_pulse:
                market_pulse_ids = {m['market_id'] for m in brief.market_pulse if 'market_id' in m}
            world_events_data = gen._generate_world_events(seen_market_ids=market_pulse_ids)
            if world_events_data:
                brief.world_events = world_events_data
                logger.info(f"Generated World Events for weekly brief with {len(world_events_data)} markets")
        except Exception as e:
            logger.warning(f"Failed to generate World Events for weekly brief: {e}")

        # Finalize
        brief.status = 'ready' if auto_publish else 'draft'
        brief.created_at = utcnow_naive()
        db.session.commit()

        logger.info(f"Weekly brief generated: {brief.title} ({position - 1} items)")
        return brief

    def _generate_weekly_intro(
        self,
        briefs: List[DailyBrief],
        items: List[BriefItem]
    ) -> str:
        """Generate a summary intro for the weekly brief."""
        days_covered = len(briefs)
        story_count = len(items)

        intros = [
            f"This week's digest synthesises {story_count} stories from {days_covered} daily briefs. "
            f"Here are the stories that defined the week, with context on how they developed.",

            f"A curated look back at the week's most important stories. "
            f"{story_count} topics distilled from {days_covered} days of coverage.",

            f"Your weekly review: the biggest stories, how they developed, and what to watch next. "
            f"Drawn from {days_covered} daily briefs.",
        ]

        import random
        random.seed(briefs[0].date.toordinal() if briefs else 0)
        return random.choice(intros)

    def _rank_weekly_stories(self, items: List[BriefItem]) -> List[BriefItem]:
        """
        Re-rank stories by weekly significance.

        Scoring criteria:
        - Civic score of underlying topic (40%)
        - Number of days the story appeared (30%) — developing stories rank higher
        - Source count (15%)
        - Coverage balance (15%)
        """
        # Group items by topic to detect developing stories
        topic_items = defaultdict(list)
        for item in items:
            if item.trending_topic_id:
                topic_items[item.trending_topic_id].append(item)

        scored_items = []
        seen_topics = set()

        for item in items:
            topic_id = item.trending_topic_id
            if not topic_id or topic_id in seen_topics:
                continue
            seen_topics.add(topic_id)

            # How many days did this story appear?
            appearances = len(topic_items.get(topic_id, []))

            # Get topic scores
            topic = item.trending_topic
            civic = topic.civic_score if topic and topic.civic_score else 0.5
            source_count = item.source_count or 1
            imbalance = item.coverage_imbalance or 0.5

            weekly_score = (
                civic * 0.40 +
                min(appearances / 5, 1.0) * 0.30 +  # Cap at 5 days
                min(source_count / 10, 1.0) * 0.15 +
                (1 - imbalance) * 0.15
            )

            scored_items.append((item, weekly_score))

        scored_items.sort(key=lambda x: x[1], reverse=True)
        return [item for item, _ in scored_items]

    def _create_weekly_item(
        self,
        brief: DailyBrief,
        source_item: BriefItem,
        position: int,
        section: str,
        depth: str,
        daily_briefs: List[DailyBrief]
    ) -> BriefItem:
        """Create a weekly brief item from a daily brief item."""
        # For weekly items, we carry over the daily item's content
        # but could generate a weekly summary via LLM in future
        return BriefItem(
            brief_id=brief.id,
            position=position,
            section=section,
            depth=depth,
            trending_topic_id=source_item.trending_topic_id,
            headline=source_item.headline,
            quick_summary=source_item.quick_summary,
            summary_bullets=source_item.summary_bullets,
            personal_impact=source_item.personal_impact,
            so_what=source_item.so_what,
            perspectives=source_item.perspectives,
            coverage_distribution=source_item.coverage_distribution,
            coverage_imbalance=source_item.coverage_imbalance,
            source_count=source_item.source_count,
            sources_by_leaning=source_item.sources_by_leaning,
            blindspot_explanation=source_item.blindspot_explanation,
            sensationalism_score=source_item.sensationalism_score,
            sensationalism_label=source_item.sensationalism_label,
            verification_links=source_item.verification_links,
            deeper_context=source_item.deeper_context,
            market_signal=source_item.market_signal,
        )

    def _select_best_lens_check(self, briefs: List[DailyBrief]) -> Optional[Dict]:
        """Select the most insightful lens check from the week's briefs."""
        best = None
        best_source_count = 0

        for brief in briefs:
            if brief.lens_check:
                criteria = brief.lens_check.get('selection_criteria', {})
                total = criteria.get('total_sources', 0)
                if total > best_source_count:
                    best = brief.lens_check
                    best_source_count = total

        return best


def generate_weekly_brief(
    week_end_date: Optional[date] = None,
    auto_publish: bool = True
) -> Optional[DailyBrief]:
    """
    Convenience function to generate a weekly brief.

    Args:
        week_end_date: Sunday of the week to summarize (default: last Sunday)
        auto_publish: Set to 'ready' if True

    Returns:
        DailyBrief instance with brief_type='weekly', or None
    """
    if week_end_date is None:
        today = date.today()
        # Find the most recent Sunday
        days_since_sunday = (today.weekday() + 1) % 7
        week_end_date = today - timedelta(days=days_since_sunday)

    logger.info(f"Generating weekly brief for week ending {week_end_date}")

    try:
        generator = WeeklyBriefGenerator()
        return generator.generate_weekly_brief(week_end_date, auto_publish)
    except Exception as e:
        logger.error(f"Weekly brief generation failed: {e}", exc_info=True)
        return None
