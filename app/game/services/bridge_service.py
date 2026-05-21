"""Society Speaks bridge — match Play scenarios to Daily Questions / Discussions.

Plan §1.3: max one bridge per completed session; priority topic match → journey → profile.
V1 implements topic match only (Daily Question first, then Discussion).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional, Set

from flask import url_for

from app.game.engine.scenario import load_scenario
from app.game.services.daily_service import utc_game_date
from app.models.daily_question import DailyQuestion
from app.models.discussions import Discussion

# Scenario topic_tags → Society Speaks Discussion.topic values.
_TAG_TO_DISCUSSION_TOPICS: Dict[str, tuple[str, ...]] = {
    'fiscal': ('Economy',),
    'taxation': ('Economy', 'Politics'),
    'public_services': ('Society', 'Healthcare'),
    'debt': ('Economy',),
    'healthcare': ('Healthcare',),
    'housing': ('Society', 'Economy'),
    'technology': ('Technology',),
    'labour': ('Economy', 'Society'),
    'automation': ('Technology', 'Economy'),
    'energy': ('Economy', 'Environment'),
    'cost_of_living': ('Economy',),
    'climate': ('Environment',),
    'economy': ('Economy',),
    'regulation': ('Politics', 'Economy'),
    'water': ('Environment', 'Infrastructure'),
    'infrastructure': ('Infrastructure',),
    'migration': ('Society', 'Geopolitics'),
    'border': ('Geopolitics', 'Politics'),
    'demographics': ('Society',),
    'security': ('Politics', 'Society'),
    'privacy': ('Technology', 'Society'),
    'pensions': ('Society', 'Healthcare'),
    'intergenerational': ('Society',),
    'democracy': ('Politics',),
    'populism': ('Politics',),
    'trust': ('Society', 'Politics'),
    'governance': ('Politics',),
    'corruption': ('Politics',),
    'institutions': ('Politics', 'Society'),
    'education': ('Education',),
    'innovation': ('Technology', 'Education'),
    'finance': ('Economy',),
    'sovereignty': ('Geopolitics', 'Politics'),
    'austerity': ('Economy', 'Politics'),
}


def find_ss_bridge(scenario_slug: str) -> Optional[Dict[str, Any]]:
    """Return at most one bridge target for a completed scenario, or None."""
    scenario = load_scenario(scenario_slug)
    tags = _scenario_tags(scenario)
    if not tags:
        return None

    bridge = _match_daily_question(tags)
    if bridge:
        return bridge
    return _match_discussion(tags)


def _scenario_tags(scenario: Dict[str, Any]) -> Set[str]:
    raw = scenario.get('topic_tags') or []
    tags: Set[str] = set()
    for item in raw:
        normalized = str(item).strip().lower().replace('-', '_')
        if normalized:
            tags.add(normalized)
    return tags


def _tag_matches_category(tag: str, category: str) -> bool:
    cat = (category or '').lower()
    if not cat:
        return False
    if tag in cat or tag.replace('_', ' ') in cat:
        return True
    for topic in _TAG_TO_DISCUSSION_TOPICS.get(tag, ()):
        if topic.lower() in cat:
            return True
    return False


def _match_daily_question(tags: Set[str]) -> Optional[Dict[str, Any]]:
    today = utc_game_date()
    cutoff = today - timedelta(days=14)
    candidates = (
        DailyQuestion.query.filter(
            DailyQuestion.status == 'published',
            DailyQuestion.question_date >= cutoff,
            DailyQuestion.question_date <= today,
        )
        .order_by(DailyQuestion.question_date.desc())
        .all()
    )

    best: tuple[int, DailyQuestion] | None = None
    for question in candidates:
        score = sum(1 for tag in tags if _tag_matches_category(tag, question.topic_category or ''))
        if question.source_discussion and question.source_discussion.topic:
            for tag in tags:
                if question.source_discussion.topic in _TAG_TO_DISCUSSION_TOPICS.get(tag, ()):
                    score += 1
        if score <= 0:
            continue
        if best is None or score > best[0] or (
            score == best[0] and question.question_date > best[1].question_date
        ):
            best = (score, question)

    if not best:
        return None

    question = best[1]
    return {
        'bridge_type': 'daily_question',
        'title': question.question_text,
        'subtitle': question.topic_category or 'Daily Question',
        'url': url_for('daily.by_date', date_str=question.question_date.isoformat()),
        'target_id': question.id,
        'match_score': best[0],
    }


def _discussion_base_query():
    return Discussion.query.filter(
        Discussion.is_closed.is_(False),
        Discussion.has_native_statements.is_(True),
        Discussion.partner_env != 'test',
    )


def _match_discussion(tags: Set[str]) -> Optional[Dict[str, Any]]:
    mapped_topics: Set[str] = set()
    for tag in tags:
        mapped_topics.update(_TAG_TO_DISCUSSION_TOPICS.get(tag, ()))

    candidates = _discussion_base_query().order_by(
        Discussion.participant_count.desc(),
        Discussion.created_at.desc(),
    ).limit(200).all()

    best: tuple[int, Discussion] | None = None
    for discussion in candidates:
        score = 0
        if discussion.topic and discussion.topic in mapped_topics:
            score += 3
        haystack = ' '.join(
            filter(
                None,
                [
                    discussion.title or '',
                    discussion.description or '',
                    discussion.keywords or '',
                ],
            )
        ).lower()
        for tag in tags:
            term = tag.replace('_', ' ')
            if term in haystack or tag in haystack:
                score += 2
        if score <= 0:
            continue
        tiebreak = (discussion.participant_count or 0, discussion.created_at)
        if best is None or score > best[0] or (score == best[0] and tiebreak > (
            best[1].participant_count or 0,
            best[1].created_at,
        )):
            best = (score, discussion)

    if not best:
        return None

    discussion = best[1]
    return {
        'bridge_type': 'discussion',
        'title': discussion.title,
        'subtitle': discussion.topic or 'Discussion',
        'url': url_for(
            'discussions.view_discussion',
            discussion_id=discussion.id,
            slug=discussion.slug,
        ),
        'target_id': discussion.id,
        'match_score': best[0],
    }
