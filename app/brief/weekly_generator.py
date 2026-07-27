"""
Weekly Brief Generator

Builds one weekly edition from the past 7 days of daily briefs.

What makes it a weekly rather than a rerun — a daily reader has already seen
this week's stories, so the edition has to add something:

- **Re-ranked for the week**, not the day. Civic score 40%, days-appeared 30%,
  source count 15%, coverage balance 15%. A story that ran all week outranks a
  Tuesday one-off with a higher daily score.
- **Latest appearance wins.** One item per topic, taken from the story's *last*
  day in the briefs, so the weekend reader gets it as it stood on Friday.
- **A development line.** The one field not inherited from the daily item:
  1-2 LLM-written sentences on how the story moved across the week. Only for
  stories that ran on 2+ days — a one-day story has no development to describe,
  and inventing one would be worse than saying nothing.
- **Real sections.** Stories keep their own topic section (a daily *lead* is
  refiled from its topic category), capped per section so a busy week in one
  area cannot fill the whole edition.

Brief-level content: best lens check of the week, the week ahead, and world
events — see ``generate_weekly_brief``.
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

# How many stories the weekly edition carries.
WEEKLY_STORY_LIMIT = 7

# Sections a weekly *story* can be filed under. The rest of SECTIONS is either
# brief-level structure (market_pulse, week_ahead, world_events, lens_check) or
# reserved: 'lead' always goes to the week's top-ranked story.
WEEKLY_TOPICAL_SECTIONS = (
    'politics', 'economy', 'society', 'science', 'global_roundup', 'underreported',
)

# Per-section cap for the weekly. Stops one busy week in Westminster from
# filling all seven slots while the other four sections sit empty. Never
# shrinks the edition — items displaced by the cap are backfilled in rank order.
WEEKLY_SECTION_CAP = 2

# A story needs at least this many appearances across the week before a
# "how it developed" line is honest. One appearance has no development.
MIN_APPEARANCES_FOR_DEVELOPMENT = 2


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
        self._llm_delegate = None  # lazily built BriefGenerator, see _call_llm

    def generate_weekly_brief(
        self,
        week_end_date: date,
        auto_publish: bool = True,
        force: bool = False,
    ) -> Optional[DailyBrief]:
        """
        Generate weekly brief for the week ending on week_end_date.

        Args:
            week_end_date: The Sunday (or delivery date) of the week
            auto_publish: Set to 'ready' if True
            force: Regenerate when a ready/published edition already exists

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

            if existing and existing.status in ('ready', 'published') and not force:
                logger.info(f"Weekly brief for {week_end_date} already exists")
                return existing

            # Regenerating a live edition must leave it live. Both weekly web
            # routes filter status='published', and the auto-publish job only
            # looks at date=today — so an older edition demoted to 'ready' here
            # would go dark permanently, with nothing to promote it back.
            was_published = bool(existing) and existing.status == 'published'
            prior_published_at = existing.published_at if existing else None

            if existing:
                brief = existing
                BriefItem.query.filter_by(brief_id=existing.id).delete()
                brief.status = 'draft'
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
                was_published = False
                prior_published_at = None
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to create weekly brief record: {e}")
            return None

        # Generate title
        brief.title = f"The Week in Review: {week_start.strftime('%d %b')} – {week_end_date.strftime('%d %b %Y')}"

        # Story history per topic, keyed by trending_topic_id and ordered by the
        # date of the daily brief each appearance came from. Drives both the
        # ranker (developing stories score higher) and the per-item development
        # line, so it is built once here and threaded through.
        topic_history = self._build_topic_history(daily_briefs)

        # Rank and select top stories
        top_stories = self._rank_weekly_stories(all_items, topic_history)
        lineup = self._select_weekly_lineup(top_stories, topic_history)

        position = 1
        selected_items = []
        for source_item, section, depth in lineup:
            try:
                weekly_item = self._create_weekly_item(
                    brief, source_item, position, section, depth,
                    topic_history.get(source_item.trending_topic_id, []),
                )
                db.session.add(weekly_item)
                selected_items.append(weekly_item)
                position += 1
            except Exception as e:
                logger.warning(f"Failed to create weekly item: {e}")
                continue

        # Intro reflects what the edition actually contains, so it must run
        # after selection — not against the full week's item pool.
        brief.intro_text = self._generate_weekly_intro(
            daily_briefs, selected_items, topic_history
        )

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
            world_events_data = gen._generate_world_events(
                seen_market_ids=market_pulse_ids,
                brief_date=getattr(brief, 'date', None),
            )
            if world_events_data:
                brief.world_events = world_events_data
                logger.info(f"Generated World Events for weekly brief with {len(world_events_data)} markets")
        except Exception as e:
            logger.warning(f"Failed to generate World Events for weekly brief: {e}")

        # Finalize. A previously-published edition is republished with its
        # original published_at, so a --force refresh swaps the content without
        # ever removing the edition from /brief/weekly.
        if was_published:
            brief.status = 'published'
            brief.published_at = prior_published_at or utcnow_naive()
        else:
            brief.status = 'ready' if auto_publish else 'draft'
        brief.created_at = utcnow_naive()
        db.session.commit()

        logger.info(
            f"Weekly brief generated: {brief.title} "
            f"({position - 1} items, status={brief.status})"
        )
        return brief

    def _generate_weekly_intro(
        self,
        briefs: List[DailyBrief],
        selected_items: List[BriefItem],
        topic_history: Dict[int, List[Dict[str, Any]]],
    ) -> str:
        """Write the intro for the stories this edition actually carries.

        ``selected_items`` is the final lineup, not the week's whole item pool —
        an intro that claims to synthesise 68 stories while shipping 7 is simply
        wrong. Falls back to a deterministic sentence when no LLM is available.
        """
        days_covered = len(briefs)
        story_count = len(selected_items)
        developing = [
            item for item in selected_items
            if len(topic_history.get(item.trending_topic_id, [])) >= MIN_APPEARANCES_FOR_DEVELOPMENT
        ]

        fallback = self._fallback_weekly_intro(story_count, days_covered, len(developing))

        if not self.llm_available or not selected_items:
            return fallback

        headlines = "\n".join(
            f"- {item.headline}"
            + (
                f" (ran on {len(topic_history.get(item.trending_topic_id, []))} days)"
                if len(topic_history.get(item.trending_topic_id, [])) >= MIN_APPEARANCES_FOR_DEVELOPMENT
                else ""
            )
            for item in selected_items
        )
        prompt = (
            "You are writing the opening paragraph of a weekly news digest for a "
            "civic discussion platform. Readers may have read some of the daily "
            "briefs already, so the value here is the shape of the week, not a recap.\n\n"
            f"The edition covers {story_count} stories drawn from {days_covered} daily briefs:\n"
            f"{headlines}\n\n"
            "Write 2 sentences (max 45 words total) that tell the reader what kind of "
            "week it was and what connects or separates these stories. Rules:\n"
            "- Calm and neutral. No hype, no rhetorical questions, no 'buckle up'.\n"
            "- Introduce no facts that are not in the headlines above.\n"
            "- Do not list the stories back; characterise them.\n"
            "- Do not open with 'This week' or 'In this edition'.\n"
            "Return the paragraph as plain text with no preamble or quotation marks."
        )

        try:
            text = self._call_llm(
                prompt,
                system_prompt=(
                    "You are a calm, neutral news editor. Respond with plain text only."
                ),
                max_tokens=180,
            )
            text = (text or '').strip().strip('"').strip()
            if text:
                return text
            logger.warning("Weekly intro LLM returned empty text; using fallback")
        except Exception as e:
            logger.warning(f"Weekly intro generation failed, using fallback: {e}")

        return fallback

    @staticmethod
    def _fallback_weekly_intro(
        story_count: int, days_covered: int, developing_count: int
    ) -> str:
        """Deterministic intro used when no LLM is configured or the call fails."""
        day_label = "day" if days_covered == 1 else "days"
        story_label = "story" if story_count == 1 else "stories"
        base = (
            f"The {story_count} {story_label} that mattered most across "
            f"{days_covered} {day_label} of coverage, re-ranked for the week rather "
            f"than the day."
        )
        if developing_count:
            moved = "one of them" if developing_count == 1 else f"{developing_count} of them"
            base += f" We've noted how {moved} developed."
        return base

    def _build_topic_history(
        self, briefs: List[DailyBrief]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Map trending_topic_id → its appearances across the week, in date order.

        Each appearance records the brief date plus the headline and bullets as
        they ran that day, which is what the development line is written from.
        """
        history: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for brief in sorted(briefs, key=lambda b: b.date):
            items = brief.items.all() if hasattr(brief.items, 'all') else list(brief.items)
            for item in items:
                if not item.trending_topic_id:
                    continue
                history[item.trending_topic_id].append({
                    'date': brief.date,
                    'headline': item.headline,
                    'bullets': list(item.summary_bullets or []),
                    'item': item,
                })
        return dict(history)

    def _weekly_section_for(self, item: BriefItem) -> str:
        """The section a weekly story belongs in.

        Prefers the section the item already carried. Daily *lead* stories carry
        section='lead' with no topical section of their own, and they are exactly
        the stories most likely to rank into the weekly — so fall back to the
        underlying topic's category rather than dumping them all in one bucket.
        """
        section = (item.section or '').strip()
        if section in WEEKLY_TOPICAL_SECTIONS:
            return section

        topic = item.trending_topic
        return get_section_for_category(getattr(topic, 'primary_topic', None))

    def _select_weekly_lineup(
        self,
        ranked_items: List[BriefItem],
        topic_history: Dict[int, List[Dict[str, Any]]],
        limit: int = WEEKLY_STORY_LIMIT,
    ) -> List[tuple]:
        """Assign section and depth to the week's top stories.

        The top-ranked story leads at full depth. Every other story keeps its
        real topic section — filing them all under 'politics' put unrelated
        stories beneath a "Policy & Governance" heading. Per-section caps keep
        the edition varied; anything displaced is backfilled in rank order so a
        single-theme week still ships a full edition.

        Returns: [(source_item, section, depth)]
        """
        lineup = []
        deferred = []
        counts = defaultdict(int)

        for item in ranked_items:
            if len(lineup) >= limit:
                break

            if not lineup:
                lineup.append((item, 'lead', DEPTH_FULL))
                continue

            section = self._weekly_section_for(item)
            if counts[section] >= WEEKLY_SECTION_CAP:
                deferred.append((item, section))
                continue

            counts[section] += 1
            lineup.append((item, section, DEPTH_STANDARD))

        # Caps shape the edition, they never shrink it.
        for item, section in deferred:
            if len(lineup) >= limit:
                break
            lineup.append((item, section, DEPTH_STANDARD))

        return lineup

    def _rank_weekly_stories(
        self,
        items: List[BriefItem],
        topic_history: Dict[int, List[Dict[str, Any]]],
    ) -> List[BriefItem]:
        """
        Re-rank stories by weekly significance, one item per topic.

        Scoring criteria:
        - Civic score of underlying topic (40%)
        - Number of days the story appeared (30%) — developing stories rank higher
        - Source count (15%)
        - Coverage balance (15%)

        The representative item for a topic is its *latest* appearance. A story
        that ran Monday through Friday should reach the weekend reader as it
        stood on Friday; carrying Monday's write-up made the weekly both a rerun
        and an out-of-date one.
        """
        scored_items = []

        for topic_id, appearances in topic_history.items():
            if not appearances:
                continue

            item = appearances[-1]['item']  # latest appearance
            topic = item.trending_topic
            civic = topic.civic_score if topic and topic.civic_score else 0.5
            source_count = item.source_count or 1
            imbalance = item.coverage_imbalance or 0.5

            weekly_score = (
                civic * 0.40 +
                min(len(appearances) / 5, 1.0) * 0.30 +  # Cap at 5 days
                min(source_count / 10, 1.0) * 0.15 +
                (1 - imbalance) * 0.15
            )

            scored_items.append((item, weekly_score))

        # Tie-break on topic id so a given week always ranks identically —
        # regeneration must not reshuffle the edition.
        scored_items.sort(key=lambda x: (-x[1], x[0].trending_topic_id or 0))
        return [item for item, _ in scored_items]

    def _create_weekly_item(
        self,
        brief: DailyBrief,
        source_item: BriefItem,
        position: int,
        section: str,
        depth: str,
        appearances: List[Dict[str, Any]],
    ) -> BriefItem:
        """Create a weekly brief item from the story's latest daily appearance.

        Editorial content is carried over — it was already written and checked.
        ``weekly_development`` is the one field generated fresh, and it is the
        only reason a daily reader has to open the weekly.
        """
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
            weekly_development=self._generate_development_line(source_item, appearances),
        )

    def _generate_development_line(
        self,
        item: BriefItem,
        appearances: List[Dict[str, Any]],
    ) -> Optional[str]:
        """One or two sentences on how this story moved across the week.

        Returns None — and the email renders nothing — when the story ran on a
        single day or no LLM is configured. A fabricated development line on a
        one-day story would be worse than no line at all.
        """
        if len(appearances) < MIN_APPEARANCES_FOR_DEVELOPMENT:
            return None
        if not self.llm_available:
            return None

        timeline = []
        for appearance in appearances:
            day = appearance['date'].strftime('%A %d %b')
            bullets = '; '.join(b for b in appearance['bullets'][:3] if b)
            timeline.append(
                f"{day}: {appearance['headline']}" + (f" — {bullets}" if bullets else "")
            )

        prompt = (
            "Below is how one news story was reported across a single week, in "
            "date order, as it appeared in a daily news brief.\n\n"
            + "\n".join(timeline)
            + "\n\nWrite 1-2 sentences (max 40 words) describing how the story "
            "developed over the week for a reader catching up on Sunday. Rules:\n"
            "- Use only what is stated above. Introduce no new facts, numbers, "
            "names or predictions.\n"
            "- Focus on what changed between the first and last entry — a "
            "reversal, an escalation, a resolution, or that it held steady.\n"
            "- If nothing meaningfully changed, say so plainly.\n"
            "- Calm and neutral. No hype.\n"
            "Return plain text only, with no preamble or quotation marks."
        )

        try:
            text = self._call_llm(
                prompt,
                system_prompt=(
                    "You are a calm, neutral news editor summarising how a story "
                    "developed. Respond with plain text only."
                ),
                max_tokens=150,
            )
            text = (text or '').strip().strip('"').strip()
            return text or None
        except Exception as e:
            logger.warning(
                f"Development line generation failed for topic "
                f"{item.trending_topic_id}: {e}"
            )
            return None

    def _call_llm(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Delegate to BriefGenerator's LLM path.

        Reuses the daily pipeline's provider selection, client pooling and retry
        handling rather than duplicating it here. The generator is instantiated
        once and cached — its __init__ only constructs an API client.
        """
        if self._llm_delegate is None:
            from app.brief.generator import BriefGenerator
            self._llm_delegate = BriefGenerator()
        return self._llm_delegate._call_llm(
            prompt, system_prompt=system_prompt, max_tokens=max_tokens
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
    auto_publish: bool = True,
    force: bool = False,
) -> Optional[DailyBrief]:
    """
    Convenience function to generate a weekly brief.

    Args:
        week_end_date: Sunday of the week to summarize (default: last Sunday)
        auto_publish: Set to 'ready' if True
        force: Regenerate when a ready/published edition already exists

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
        return generator.generate_weekly_brief(week_end_date, auto_publish, force=force)
    except Exception as e:
        logger.error(f"Weekly brief generation failed: {e}", exc_info=True)
        return None
