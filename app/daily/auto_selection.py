"""
Automatic Daily Question Selection Service

Selects the next daily question from curated content sources:
1. Brief-promoted topics (yesterday's brief → tomorrow's question)
2. Existing discussion topics (fallback)
3. Published trending topics with high civic scores (fallback)
4. Statements from active discussions (fallback)

Uses ENGAGEMENT-WEIGHTED SELECTION to maximize participation:
- Civic relevance score
- Timeliness (recency of topic)
- Statement clarity (shorter = higher engagement)
- Historical performance (learn from past questions)
- Position diversity (alternate pro/con/neutral)
- Brief coverage imbalance / underreported (press-vs-public signal)

Avoids repeating content within a configurable time window.
"""

from datetime import date, datetime, timedelta
from app.lib.time import utcnow_naive
from app.lib.claim_craft import is_votable_claim
from app.lib.contestation import (
    contestation_score,
    coverage_engagement,
    is_national_scope,
    perspective_divergence,
)
from flask import current_app
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from app import db
from app.models import (
    DailyQuestion,
    DailyQuestionSelection,
    Discussion,
    Programme,
    TrendingTopic,
    Statement,
    DailyQuestionResponse,
    DailyBrief,
    BriefItem,
)
import random
import math


AVOID_REPEAT_DAYS = 30
MIN_CIVIC_SCORE = 0.5
MAX_QUESTION_LENGTH = 500
MAX_CONTEXT_LENGTH = 400
MAX_WHY_LENGTH = 300
BRIEF_SOURCE_TYPE = 'brief'

# Source count at which a story counts as broadly covered ("people have heard
# of this"). Chosen from the July 2026 corpus: the 100+ vote question drew 7
# sources; every zero-vote question drew 1–3.
BROAD_COVERAGE_SOURCE_COUNT = 8

# Contestation floor for a brief-sourced stance question. Candidates below this
# are civic pleasantries or national-policy propositions. If *every* candidate
# is below it we still publish the best of them and log loudly, because a weak
# question beats a missing one — but the warning is the signal that the brief
# had no arguable story that day.
MIN_BRIEF_CONTESTATION = 0.40

# Engagement scoring weights
WEIGHT_CIVIC = 0.25        # Civic importance
WEIGHT_TIMELINESS = 0.25   # How recent/relevant
WEIGHT_CLARITY = 0.20      # Statement clarity (shorter = better)
WEIGHT_CONTROVERSY = 0.15  # Potential for divided opinions (engagement driver)
WEIGHT_HISTORICAL = 0.15   # Learn from past performance

# Categories that are always eligible for the daily question.
# The daily question is about humanity's big civic/political/economic/social
# questions — not entertainment, celebrity, or pure lifestyle.
DAILY_QUESTION_CATEGORIES = {
    'Politics',
    'Geopolitics',
    'Economy',
    'Society',
    'Healthcare',
    'Environment',
    'Education',
    'Technology',
    'Infrastructure',
    'Business',
    # Culture is included but requires a higher civic threshold (see MIN_CIVIC_SCORE_FOR_CULTURE).
    # A Culture question must have clear civic relevance — e.g. "Should governments
    # fund public broadcasting?" — not "What is your favourite film?"
    'Culture',
}

# Culture discussions need a stronger civic signal before they qualify.
# This filters out lifestyle/entertainment Culture topics while keeping
# genuinely civic cultural debates.
MIN_CIVIC_SCORE_FOR_CULTURE = 0.6

# Priority topics - these get boosted for daily questions (major news/civic topics)
PRIORITY_TOPICS = {
    'Politics': 1.4,       # Major boost - core civic engagement
    'Geopolitics': 1.4,    # Major boost - world events
    'Economy': 1.3,        # Strong boost - affects everyone
    'Society': 1.2,        # Moderate boost - social issues
    'Healthcare': 1.1,     # Important - public health policy
    'Environment': 1.1,    # Important - climate/sustainability policy
    'Education': 1.1,      # Important - affects everyone long-term
    'Technology': 1.1,     # Slight boost - tech policy matters
    'Infrastructure': 1.0, # Neutral
    'Business': 1.0,       # Neutral
    'Culture': 0.8,        # Lower priority - must pass higher civic threshold
}

def _trim_text(text, max_length):
    """Trim text to a max length with a word-boundary ellipsis."""
    if not text:
        return None
    clean = " ".join(str(text).split())
    if len(clean) <= max_length:
        return clean
    cutoff = clean[: max_length - 1].rstrip()
    last_space = cutoff.rfind(" ")
    if last_space > int(max_length * 0.6):
        cutoff = cutoff[:last_space]
    return f"{cutoff}..."


def _extract_seed_content(seed_item):
    """Normalize seed statement payloads into plain text."""
    if isinstance(seed_item, dict):
        return (seed_item.get('content') or '').strip()
    return str(seed_item or '').strip()


def _best_votable_seed(topic, *, limit: int = 8, perspectives=None):
    """
    Most contested seed that is also a clear Agree/Disagree claim.

    Skips open questions and throat-clearing hedges so brief-sourced daily
    questions cannot quote unusable AI filler in the E1 stance CTA, then ranks
    the survivors on whether anyone would actually take the other side.

    Returns ``(seed, text, contestation_score)`` or ``None``.
    """
    seeds = list(topic.seed_statements or [])[:limit]
    scored = []
    for seed in seeds:
        text = _extract_seed_content(seed)
        if not is_votable_claim(text):
            continue
        scored.append(
            (seed, text, calculate_contestation_potential(text, perspectives=perspectives))
        )
    if not scored:
        return None
    scored.sort(key=lambda row: row[2], reverse=True)
    return scored[0]


def _build_discussion_context(statement, discussion):
    """Build concise pre-vote context for discussion-sourced questions."""
    statement_text = getattr(statement, 'content', '') or ''
    desc = (discussion.description or '').strip() if discussion else ''
    title = (discussion.title or '').strip() if discussion else ''

    if desc:
        return _trim_text(desc, MAX_CONTEXT_LENGTH)

    # Fallback to discussion title with a short lead-in for clarity.
    if title and title.lower() not in statement_text.lower():
        return _trim_text(f"From the discussion: {title}", MAX_CONTEXT_LENGTH)

    return _trim_text(title, MAX_CONTEXT_LENGTH)


def _build_statement_context(statement):
    """Build context for standalone statement fallback questions."""
    discussion = getattr(statement, 'discussion', None)
    if not discussion:
        return None
    return _build_discussion_context(statement, discussion)


def _build_trending_context(topic):
    """Build concise context for trending-topic sourced questions."""
    description = (topic.description or '').strip() if topic else ''
    title = (topic.title or '').strip() if topic else ''

    if description:
        return _trim_text(description, MAX_CONTEXT_LENGTH)

    if title:
        return _trim_text(f"Topic context: {title}", MAX_CONTEXT_LENGTH)
    return None


def _normalize_statement_text(text):
    """Collapse whitespace for matching daily question text to seed statements."""
    return " ".join(str(text or "").split()).lower()


def resolve_brief_primary_statement_id(question_text, discussion_id):
    """
    Match a brief-sourced daily question to its primary seed statement in the
    linked discussion so daily votes sync into statement_vote.

    Returns statement.id or None when no discussion / no matching seed exists.
    """
    from app.models import Statement

    if not question_text or not discussion_id:
        return None

    target = _normalize_statement_text(question_text)
    if not target:
        return None

    seeds = (
        Statement.query.filter_by(
            discussion_id=discussion_id,
            is_seed=True,
            is_deleted=False,
        )
        .order_by(Statement.id.asc())
        .all()
    )
    for stmt in seeds:
        if _normalize_statement_text(stmt.content) == target:
            return stmt.id
    return None


def _build_why_this_question(source_type, topic_category=None, source=None):
    """Build a short relevance explanation for why a question was selected."""
    topic = (topic_category or '').strip()
    if source_type == BRIEF_SOURCE_TYPE:
        base = (
            "This question comes from a story featured in the Daily Brief — where press "
            "attention was uneven or a story sat under the radar."
        )
    elif source_type == 'discussion':
        base = "This statement comes from an active discussion and helps compare public views on a concrete claim."
    elif source_type == 'trending':
        base = "This statement is tied to a current news topic with high civic relevance and multiple viewpoints."
    else:
        base = "This statement was selected for clear framing and strong potential to surface meaningful disagreement."

    if topic:
        base = f"{base} Category: {topic}."

    # Optional source freshness cue where possible
    if source and hasattr(source, 'created_at') and source.created_at:
        age_days = (utcnow_naive() - source.created_at).days
        if age_days <= 2:
            base += " It reflects a recent development."

    return _trim_text(base, MAX_WHY_LENGTH)


class BriefQuestionWiringError(RuntimeError):
    """Raised when brief-eligible items exist but no labeled brief question was wired."""


def _dominant_coverage_frame(distribution):
    """Return left|center|right|balanced from a coverage distribution dict."""
    if not distribution:
        return 'unknown'
    left = float(distribution.get('left') or 0)
    center = float(distribution.get('center') or distribution.get('centre') or 0)
    right = float(distribution.get('right') or 0)
    total = left + center + right
    if total <= 0:
        return 'unknown'
    shares = {'left': left / total, 'center': center / total, 'right': right / total}
    dominant, share = max(shares.items(), key=lambda item: item[1])
    if share < 0.45:
        return 'balanced'
    return dominant


def build_coverage_frame_snapshot(brief_item, brief_date):
    """Immutable press-posture snapshot stored on the daily question."""
    dist = brief_item.coverage_distribution or {}
    return {
        'brief_date': brief_date.isoformat(),
        'brief_item_id': brief_item.id,
        'trending_topic_id': brief_item.trending_topic_id,
        'section': brief_item.section,
        'coverage_distribution': dist,
        'coverage_imbalance': brief_item.coverage_imbalance,
        'is_underreported': bool(brief_item.is_underreported),
        'dominant_frame': _dominant_coverage_frame(dist),
        'source_count': brief_item.source_count,
    }


def calculate_brief_item_contestability_score(brief_item):
    """
    Rank brief items by how likely the story is to produce a genuine split.

    Higher = left, centre and right are all engaging with the story, and enough
    outlets covered it that readers have heard of it.

    Sign note (July 2026 correction): ``coverage_imbalance`` is documented as
    ``0=balanced, 1=single perspective``. The original implementation rewarded
    *high* imbalance, so it systematically picked stories only one bloc had
    bothered to cover — i.e. stories nobody was arguing about. Every zero-vote
    question in the 20–28 Jul corpus came from an item at imbalance 1.0 with
    1–3 sources; the two 100+ vote questions sat at 0.57/7 sources and (its
    nearest non-spike rival) 0.25/4 sources.

    ``is_underreported`` is deliberately absent. Surfacing neglected stories is
    a Daily Brief virtue and stays in the Brief; as a *question* signal it is
    poison, and it is already collinear with low source counts and high
    imbalance, so excluding it avoids double-counting the same evidence.
    """
    imbalance = float(brief_item.coverage_imbalance or 0)
    balance = max(0.0, 1.0 - imbalance)

    score = balance * 0.45

    # All three leanings materially engaged is the shape of a live argument.
    engaged = coverage_engagement(brief_item.coverage_distribution)
    score += (engaged / 3.0) * 0.20

    # Breadth of coverage proxies "readers have already heard about this".
    source_count = int(brief_item.source_count or 0)
    score += min(source_count / BROAD_COVERAGE_SOURCE_COUNT, 1.0) * 0.20

    if (brief_item.section or '') == 'lead':
        score += 0.12

    divergence = perspective_divergence(brief_item.perspectives)
    if divergence is not None:
        score += divergence * 0.15

    return round(score, 4)


def _brief_topic_recently_used(topic_id, days_to_avoid=AVOID_REPEAT_DAYS):
    cutoff = utcnow_naive() - timedelta(days=days_to_avoid)
    return DailyQuestionSelection.query.filter(
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_trending_topic_id == topic_id,
    ).first() is not None


def get_eligible_brief_items(brief_date, days_to_avoid=AVOID_REPEAT_DAYS):
    """
    Brief-promoted items with coverage metadata and voteable seed statements.

    Coverage imbalance / underreported flags exist only on BriefItem (denormalized
    at brief generation), not on the raw trending pool.
    """
    brief = DailyBrief.query.filter_by(
        date=brief_date,
        brief_type='daily',
    ).filter(
        DailyBrief.status.in_(('ready', 'published'))
    ).first()
    if not brief:
        return []

    items = (
        BriefItem.query.filter_by(brief_id=brief.id)
        .filter(BriefItem.trending_topic_id.isnot(None))
        .order_by(BriefItem.position.asc())
        .all()
    )

    eligible = []
    for item in items:
        topic = db.session.get(TrendingTopic, item.trending_topic_id)
        if not topic or not topic.seed_statements:
            continue
        if _brief_topic_recently_used(topic.id, days_to_avoid):
            continue
        eligible.append((item, topic))

    return eligible


def select_from_brief_items(brief_date, question_date):
    """
    Pick tomorrow's question from today's brief items (clock constraint).

    Returns source_info dict with source_type='brief' or None if no eligible item.
    """
    candidates = get_eligible_brief_items(brief_date)
    if not candidates:
        return None

    scored = []
    skipped_non_votable = 0
    for brief_item, topic in candidates:
        best = _best_votable_seed(topic, perspectives=brief_item.perspectives)
        if not best:
            skipped_non_votable += 1
            continue
        best_seed, seed_text, contestation = best
        contestability = calculate_brief_item_contestability_score(brief_item)
        clarity = calculate_clarity_score(seed_text)
        total = contestability + (contestation * 0.60) + (clarity * 0.15)
        scored.append({
            'brief_item': brief_item,
            'topic': topic,
            'seed': best_seed,
            'seed_text': seed_text,
            'score': total,
            'contestability': contestability,
            'contestation': contestation,
        })

    if skipped_non_votable:
        current_app.logger.info(
            "Skipped %s brief item(s) with no votable seed for question_date=%s",
            skipped_non_votable,
            question_date,
        )

    if not scored:
        current_app.logger.warning(
            "No votable brief-sourced seed for question_date=%s from brief %s — "
            "falling back to other sources",
            question_date,
            brief_date,
        )
        return None

    # Prefer candidates that clear the contestation floor. If none do, the brief
    # carried no arguable story today: still publish the best available (a weak
    # question beats a missing one) but make the editorial gap visible in logs.
    arguable = [row for row in scored if row['contestation'] >= MIN_BRIEF_CONTESTATION]
    if arguable:
        scored = arguable
    else:
        current_app.logger.warning(
            "No brief item cleared the contestation floor (%.2f) for question_date=%s "
            "from brief %s — best candidate scored %.2f. Publishing it anyway; the "
            "brief had no story with an identifiable opposing side.",
            MIN_BRIEF_CONTESTATION,
            question_date,
            brief_date,
            max(row['contestation'] for row in scored),
        )

    scored.sort(key=lambda row: row['score'], reverse=True)
    top = scored[:5]
    selected = weighted_random_choice(top, [row['score'] for row in top])
    if not selected:
        return None

    brief_item = selected['brief_item']
    topic = selected['topic']
    coverage_frame = build_coverage_frame_snapshot(brief_item, brief_date)
    # Never fall back to topic.title — brief topic titles are often open questions.
    question_text = _ensure_question_text(selected['seed_text'], None)
    if not question_text or not is_votable_claim(question_text):
        current_app.logger.warning(
            "Brief item %s seed failed final votable-claim check for %s",
            brief_item.id,
            question_date,
        )
        return None

    current_app.logger.info(
        "Selected brief-sourced daily question for %s from brief %s item %s "
        "(imbalance=%.2f, leanings_engaged=%s, sources=%s, contestability=%.2f, "
        "contestation=%.2f, national_scope=%s)",
        question_date,
        brief_date,
        brief_item.id,
        float(brief_item.coverage_imbalance or 0),
        coverage_engagement(brief_item.coverage_distribution),
        int(brief_item.source_count or 0),
        selected['contestability'],
        selected['contestation'],
        is_national_scope(question_text),
    )

    source_discussion_id = topic.discussion_id
    source_statement_id = resolve_brief_primary_statement_id(
        question_text, source_discussion_id
    )
    primary_statement = None
    if source_statement_id:
        from app.models import Statement

        primary_statement = db.session.get(Statement, source_statement_id)

    return {
        'source_type': BRIEF_SOURCE_TYPE,
        'source': topic,
        'brief_item': brief_item,
        'coverage_frame': coverage_frame,
        'statement': primary_statement,
        'question_text': question_text,
        'context': _build_trending_context(topic),
        'why_this_question': _build_why_this_question(
            source_type=BRIEF_SOURCE_TYPE,
            topic_category=topic.primary_topic,
            source=topic,
        ),
        'topic_category': topic.primary_topic,
        'discussion_slug': (
            topic.created_discussion.slug
            if getattr(topic, 'created_discussion', None)
            else None
        ),
        'engagement_score': selected['score'],
        'contestability_score': selected['contestability'],
        'source_trending_topic_id': topic.id,
        'source_brief_item_id': brief_item.id,
        'source_discussion_id': source_discussion_id,
        'source_statement_id': source_statement_id,
    }


def verify_brief_sourced_question_wiring(brief_date=None, question_date=None):
    """
    Ops guard: fail if eligible brief items exist but the target question is not
    brief-sourced with source_trending_topic_id labeled.

    Guards the "path exists but never fired" failure mode from the dormant trending path.
    """
    brief_date = brief_date or date.today()
    question_date = question_date or (brief_date + timedelta(days=1))

    eligible = get_eligible_brief_items(brief_date)
    if not eligible:
        return {
            'ok': True,
            'skipped': True,
            'reason': 'no_eligible_brief_items',
            'brief_date': brief_date.isoformat(),
            'question_date': question_date.isoformat(),
        }

    question = DailyQuestion.query.filter_by(question_date=question_date).first()
    if (
        question
        and question.source_type == BRIEF_SOURCE_TYPE
        and question.source_trending_topic_id
        and question.source_brief_item_id
        and question.coverage_frame_json
    ):
        return {
            'ok': True,
            'question_id': question.id,
            'brief_date': brief_date.isoformat(),
            'question_date': question_date.isoformat(),
        }

    raise BriefQuestionWiringError(
        f"Brief wiring dormant: {len(eligible)} eligible brief item(s) on "
        f"{brief_date} but question for {question_date} is not brief-sourced "
        f"(source_type={getattr(question, 'source_type', None)!r}, "
        f"topic_id={getattr(question, 'source_trending_topic_id', None)!r})."
    )


def schedule_question_from_brief(brief_date=None, question_date=None):
    """
    After brief generation: set tomorrow's question from today's brief items.

    Replaces an existing scheduled (unpublished) question; never overwrites published.
    """
    brief_date = brief_date or date.today()
    question_date = question_date or (brief_date + timedelta(days=1))

    existing = DailyQuestion.query.filter_by(question_date=question_date).first()
    if existing and existing.status == 'published':
        current_app.logger.info(
            "Question for %s already published; skipping brief re-wire",
            question_date,
        )
        return existing

    source_info = select_from_brief_items(brief_date, question_date)
    if not source_info:
        current_app.logger.warning(
            "No brief-sourced question available for %s from brief %s",
            question_date,
            brief_date,
        )
        return None

    question = upsert_daily_question_from_source(question_date, source_info)
    verify_brief_sourced_question_wiring(brief_date=brief_date, question_date=question_date)
    return question


def wire_tomorrow_question_from_brief(brief_date=None, source='unknown'):
    """
    Idempotent scheduler entry point: wire D+1's question from date D's brief and
    run the dormancy guard. Safe to call from every path that leaves a ready brief.
    """
    brief_date = brief_date or date.today()
    question_date = brief_date + timedelta(days=1)

    try:
        question = schedule_question_from_brief(
            brief_date=brief_date,
            question_date=question_date,
        )
        if question:
            return {
                'ok': True,
                'question': question,
                'brief_date': brief_date,
                'question_date': question_date,
                'source': source,
            }

        eligible = get_eligible_brief_items(brief_date)
        if not eligible:
            return {
                'ok': True,
                'skipped': True,
                'reason': 'no_eligible_brief_items',
                'brief_date': brief_date,
                'question_date': question_date,
                'source': source,
            }

        verify_brief_sourced_question_wiring(
            brief_date=brief_date,
            question_date=question_date,
        )
        return {
            'ok': True,
            'skipped': True,
            'reason': 'no_brief_source_selected',
            'brief_date': brief_date,
            'question_date': question_date,
            'source': source,
        }
    except BriefQuestionWiringError as err:
        alert = (
            f"CRITICAL: Brief→daily-question wiring dormant ({source}): {err}"
        )
        current_app.logger.error(alert)
        return {
            'ok': False,
            'alert': alert,
            'brief_date': brief_date,
            'question_date': question_date,
            'source': source,
        }


def _ensure_question_text(question_text, fallback_text):
    """Guarantee non-empty question text for DB constraints."""
    normalized = _trim_text(question_text, MAX_QUESTION_LENGTH)
    if normalized:
        return normalized
    return _trim_text(fallback_text, MAX_QUESTION_LENGTH)


def get_topic_priority_boost(topic):
    """Get priority multiplier for a topic category."""
    if not topic:
        return 1.0
    return PRIORITY_TOPICS.get(topic, 1.0)


def calculate_timeliness_score(created_at):
    """
    Score based on recency. Newer content is more engaging.
    Returns 0-1 score with exponential decay over 14 days.
    """
    if not created_at:
        return 0.5  # Default for missing dates

    days_old = (utcnow_naive() - created_at).days
    # Exponential decay: score = e^(-days/7)
    # 0 days = 1.0, 7 days = 0.37, 14 days = 0.14
    return math.exp(-days_old / 7)


def calculate_clarity_score(text):
    """
    Score based on statement clarity. Shorter, clearer statements engage better.
    Optimal length: 50-100 characters. Penalize very short or very long.
    """
    if not text:
        return 0.5

    length = len(text)

    # Optimal range: 50-100 chars
    if 50 <= length <= 100:
        return 1.0
    elif length < 50:
        # Too short might lack context
        return 0.7 + (length / 50) * 0.3
    elif length <= 150:
        # Slightly long is okay
        return 1.0 - ((length - 100) / 100) * 0.3
    else:
        # Long statements lose engagement
        return max(0.3, 0.7 - ((length - 150) / 200) * 0.4)


def calculate_contestation_potential(statement_text, perspectives=None):
    """
    Estimate whether a claim has a real opposing camp. 0.0–1.0.

    Replaces the previous modal-verb heuristic, which counted ``should`` /
    ``must`` / ``require`` / ``mandatory`` as evidence of controversy. Because
    civic pleasantries are phrased prescriptively ("Emergency response plans
    **must** be transparent and involve community input"), that scorer ranked
    the least arguable claims highest — the text-level twin of the coverage
    sign error in :func:`calculate_brief_item_contestability_score`.

    See :mod:`app.lib.contestation` for the signals: trade-off connectives,
    policy verbs with an identifiable loser, consensus-vocabulary density,
    jurisdiction scope, and left/right framing divergence.
    """
    return contestation_score(statement_text, perspectives=perspectives)


def get_historical_performance(topic_category=None, days_lookback=30):
    """
    Learn from historical daily question performance.
    Returns average response rate for similar topics.
    """
    cutoff = utcnow_naive() - timedelta(days=days_lookback)

    # Get response counts per question with proper grouping
    # Explicitly specify join condition to avoid ambiguity (DailyQuestionResponse has 2 FKs to DailyQuestion)
    results = db.session.query(
        DailyQuestion.topic_category,
        func.count(DailyQuestionResponse.id).label('response_count')
    ).outerjoin(
        DailyQuestionResponse,
        DailyQuestionResponse.daily_question_id == DailyQuestion.id
    ).filter(
        DailyQuestion.question_date >= cutoff.date(),
        DailyQuestion.status == 'published'
    ).group_by(DailyQuestion.id, DailyQuestion.topic_category).all()

    if not results:
        return 0.5  # No history, neutral score

    # Calculate average by category
    category_totals = {}
    category_counts = {}
    overall_total = 0
    overall_count = 0

    for cat, count in results:
        overall_total += count
        overall_count += 1
        if cat:
            category_totals[cat] = category_totals.get(cat, 0) + count
            category_counts[cat] = category_counts.get(cat, 0) + 1

    overall_avg = overall_total / overall_count if overall_count > 0 else 0

    if topic_category and topic_category in category_totals:
        cat_avg = category_totals[topic_category] / category_counts[topic_category]
        # Score relative to overall average
        if overall_avg > 0:
            return min(1.0, cat_avg / (overall_avg * 2))

    return 0.5  # Neutral for unknown categories


def calculate_statement_engagement_score(statement, discussion=None):
    """
    Calculate comprehensive engagement score for a statement.
    Returns 0-1 score where higher = more likely to engage users.
    """
    scores = {}

    # 1. Civic relevance (from discussion topic if available)
    if discussion and hasattr(discussion, 'civic_score') and discussion.civic_score:
        scores['civic'] = discussion.civic_score
    else:
        scores['civic'] = 0.6  # Default moderate civic value

    # 2. Timeliness
    created_at = statement.created_at if hasattr(statement, 'created_at') else None
    scores['timeliness'] = calculate_timeliness_score(created_at)

    # 3. Clarity
    text = statement.content if hasattr(statement, 'content') else str(statement)
    scores['clarity'] = calculate_clarity_score(text)

    # 4. Contestation potential — does anyone take the other side?
    scores['controversy'] = calculate_contestation_potential(text)

    # 5. Historical performance
    topic = discussion.topic if discussion and hasattr(discussion, 'topic') else None
    scores['historical'] = get_historical_performance(topic)

    # Weighted combination
    total_score = (
        scores['civic'] * WEIGHT_CIVIC +
        scores['timeliness'] * WEIGHT_TIMELINESS +
        scores['clarity'] * WEIGHT_CLARITY +
        scores['controversy'] * WEIGHT_CONTROVERSY +
        scores['historical'] * WEIGHT_HISTORICAL
    )
    
    # Apply topic priority boost (Politics, Geopolitics get priority over Culture, etc.)
    topic_boost = get_topic_priority_boost(topic)
    total_score *= topic_boost
    scores['topic_boost'] = topic_boost

    return total_score, scores


def calculate_topic_engagement_score(topic):
    """
    Calculate engagement score for a trending topic.
    """
    scores = {}

    # 1. Civic score (direct from topic)
    scores['civic'] = topic.civic_score or 0.5

    # 2. Timeliness
    scores['timeliness'] = calculate_timeliness_score(topic.created_at)

    # 3. Quality score as proxy for clarity
    scores['clarity'] = topic.quality_score or 0.5

    # 4. Contestation potential from seed statements
    if topic.seed_statements:
        controversy_scores = [
            calculate_contestation_potential(_extract_seed_content(s))
            for s in topic.seed_statements[:3]
        ]
        scores['controversy'] = sum(controversy_scores) / len(controversy_scores)
    else:
        scores['controversy'] = 0.5

    # 5. Historical performance
    scores['historical'] = get_historical_performance(topic.primary_topic)

    # Weighted combination
    total_score = (
        scores['civic'] * WEIGHT_CIVIC +
        scores['timeliness'] * WEIGHT_TIMELINESS +
        scores['clarity'] * WEIGHT_CLARITY +
        scores['controversy'] * WEIGHT_CONTROVERSY +
        scores['historical'] * WEIGHT_HISTORICAL
    )
    
    # Apply topic priority boost (Politics, Geopolitics get priority over Culture, etc.)
    topic_boost = get_topic_priority_boost(topic.primary_topic if hasattr(topic, 'primary_topic') else None)
    total_score *= topic_boost
    scores['topic_boost'] = topic_boost

    return total_score, scores


def weighted_random_choice(items, scores):
    """
    Select item using weighted random selection based on engagement scores.
    Higher scores = higher probability of selection, but not deterministic.
    """
    if not items or not scores:
        return None

    if len(items) != len(scores):
        return random.choice(items)

    # Make a copy to avoid mutating the original list
    weights = list(scores)

    # Ensure all weights are positive
    min_weight = min(weights)
    if min_weight <= 0:
        weights = [w - min_weight + 0.1 for w in weights]

    # Use weights for random selection
    return random.choices(items, weights=weights, k=1)[0]


def is_duplicate_date_error(error):
    """Check if an IntegrityError is due to duplicate question_date.
    
    Handles different database backends (PostgreSQL, SQLite, MySQL).
    """
    error_str = str(error).lower()
    orig = getattr(error, 'orig', None)
    
    if orig:
        orig_args = getattr(orig, 'args', ())
        if orig_args:
            orig_str = str(orig_args).lower()
            if 'question_date' in orig_str or 'uq_daily_question_date' in orig_str:
                return True
        pgcode = getattr(orig, 'pgcode', None)
        if pgcode == '23505':
            if 'uq_daily_question_date' in error_str or 'question_date' in error_str:
                return True
    
    return ('uq_daily_question_date' in error_str or 
            ('duplicate' in error_str and 'question_date' in error_str))


def get_eligible_discussions(days_to_avoid=AVOID_REPEAT_DAYS):
    """Get civic discussions that haven't been used recently.

    Only returns discussions whose topic falls within DAILY_QUESTION_CATEGORIES.
    Sport and any uncategorised/entertainment topics are excluded so the daily
    question stays focused on civic, political, economic, and societal issues.
    """
    cutoff = utcnow_naive() - timedelta(days=days_to_avoid)

    recently_used_ids = db.session.query(DailyQuestionSelection.source_discussion_id).filter(
        DailyQuestionSelection.source_type == 'discussion',
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_discussion_id.isnot(None)
    ).scalar_subquery()

    allowed_categories = list(DAILY_QUESTION_CATEGORIES)

    discussions = Discussion.query.filter(
        Discussion.id.notin_(recently_used_ids),
        Discussion.partner_env != 'test',
        Discussion.topic.in_(allowed_categories)
    ).order_by(Discussion.created_at.desc()).limit(50).all()

    return discussions


def get_guided_journey_priority_discussions(days_to_avoid=AVOID_REPEAT_DAYS):
    """
    Active flagship programme discussions, in curated theme order, eligible for daily question.

    Returned first (deduped) in select_next_question_source so the daily question often
    aligns with the guided journey without excluding the rest of the pool.
    """
    from app.programmes.journey import guided_journey_slug_set, ordered_journey_discussions

    slugs = sorted(guided_journey_slug_set())
    if not slugs:
        return []

    cutoff = utcnow_naive() - timedelta(days=days_to_avoid)
    recent_rows = db.session.query(DailyQuestionSelection.source_discussion_id).filter(
        DailyQuestionSelection.source_type == "discussion",
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_discussion_id.isnot(None),
    ).all()
    recent_ids = {row[0] for row in recent_rows if row[0] is not None}

    allowed_categories = list(DAILY_QUESTION_CATEGORIES)
    out = []
    programmes = (
        Programme.query.filter(Programme.slug.in_(slugs), Programme.status == "active").order_by(Programme.id.asc()).all()
    )
    for programme in programmes:
        for discussion in ordered_journey_discussions(programme):
            if discussion.id in recent_ids:
                continue
            if discussion.partner_env == "test":
                continue
            if discussion.topic not in allowed_categories:
                continue
            out.append(discussion)
    return out


def get_eligible_trending_topics(days_to_avoid=AVOID_REPEAT_DAYS, min_civic_score=MIN_CIVIC_SCORE):
    """Get published trending topics that haven't been used recently.

    Applies two-tier civic filtering:
    - All allowed categories require civic_score >= min_civic_score (default 0.5).
    - Culture topics additionally require civic_score >= MIN_CIVIC_SCORE_FOR_CULTURE (0.6)
      so that lifestyle/entertainment Culture stories are excluded while genuinely civic
      cultural debates (arts funding, media regulation, etc.) remain eligible.
    - Topics not in DAILY_QUESTION_CATEGORIES are excluded entirely (e.g. Sport).
    """
    from sqlalchemy import and_, or_

    cutoff = utcnow_naive() - timedelta(days=days_to_avoid)

    recently_used_ids = db.session.query(DailyQuestionSelection.source_trending_topic_id).filter(
        DailyQuestionSelection.source_type == 'trending',
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_trending_topic_id.isnot(None)
    ).scalar_subquery()

    non_culture_categories = [c for c in DAILY_QUESTION_CATEGORIES if c != 'Culture']

    civic_category_filter = or_(
        # All non-Culture civic categories: standard threshold
        and_(
            TrendingTopic.primary_topic.in_(non_culture_categories),
            TrendingTopic.civic_score >= min_civic_score
        ),
        # Culture: higher threshold to ensure genuine civic angle
        and_(
            TrendingTopic.primary_topic == 'Culture',
            TrendingTopic.civic_score >= MIN_CIVIC_SCORE_FOR_CULTURE
        )
    )

    topics = TrendingTopic.query.filter(
        TrendingTopic.status == 'published',
        TrendingTopic.id.notin_(recently_used_ids),
        civic_category_filter
    ).order_by(TrendingTopic.civic_score.desc()).limit(30).all()

    return topics


def get_eligible_statements(days_to_avoid=AVOID_REPEAT_DAYS):
    """Get seed statements from discussions that haven't been used recently"""
    cutoff = utcnow_naive() - timedelta(days=days_to_avoid)
    
    recently_used_ids = db.session.query(DailyQuestionSelection.source_statement_id).filter(
        DailyQuestionSelection.source_type == 'statement',
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_statement_id.isnot(None)
    ).scalar_subquery()
    
    allowed_categories = list(DAILY_QUESTION_CATEGORIES)

    statements = Statement.query.join(Discussion).filter(
        Statement.id.notin_(recently_used_ids),
        Statement.is_seed == True,
        Discussion.topic.in_(allowed_categories)
    ).order_by(Statement.created_at.desc()).limit(50).all()

    return statements


def select_next_question_source(question_date=None):
    """
    Select the next question source using ENGAGEMENT-WEIGHTED selection.

    Priority order:
    1. Yesterday's brief items (when question_date is set — clock constraint)
    2. Seed statements from curated discussions (fallback)
    3. High-quality trending topics (fallback)
    4. Direct statements as fallback

    Selection is weighted by engagement potential:
    - Civic relevance
    - Timeliness (recent topics)
    - Statement clarity
    - Controversy potential (divisive = engaging)
    - Historical performance of similar topics
    - Brief coverage imbalance / underreported (when brief path applies)

    Key insight: Daily questions should be actual voteable statements,
    not just discussion titles. Users need specific claims to agree/disagree with.
    """
    if question_date is not None:
        brief_date = question_date - timedelta(days=1)
        brief_source = select_from_brief_items(brief_date, question_date)
        if brief_source:
            return brief_source

    # Try discussions first - collect all eligible statements with scores
    guided_first = get_guided_journey_priority_discussions()
    general = get_eligible_discussions()
    seen_ids = set()
    discussions = []
    for d in guided_first + general:
        if d.id in seen_ids:
            continue
        seen_ids.add(d.id)
        discussions.append(d)

    all_discussion_statements = []

    for discussion in discussions[:25]:  # Guided programmes expand the candidate pool slightly
        seed_statements = Statement.query.filter_by(
            discussion_id=discussion.id,
            is_seed=True
        ).all()
        for stmt in seed_statements:
            score, breakdown = calculate_statement_engagement_score(stmt, discussion)
            all_discussion_statements.append({
                'statement': stmt,
                'discussion': discussion,
                'score': score,
                'breakdown': breakdown
            })

    if all_discussion_statements:
        # Sort by score and take top candidates
        all_discussion_statements.sort(key=lambda x: x['score'], reverse=True)
        top_candidates = all_discussion_statements[:10]

        # Weighted random selection from top candidates
        scores = [c['score'] for c in top_candidates]
        selected = weighted_random_choice(top_candidates, scores)

        if selected:
            topic_boost = selected['breakdown'].get('topic_boost', 1.0)
            current_app.logger.info(
                f"Selected statement with engagement score {selected['score']:.2f} "
                f"(civic={selected['breakdown']['civic']:.2f}, "
                f"timeliness={selected['breakdown']['timeliness']:.2f}, "
                f"clarity={selected['breakdown']['clarity']:.2f}, "
                f"controversy={selected['breakdown']['controversy']:.2f}, "
                f"topic_boost={topic_boost:.2f})"
            )
            return {
                'source_type': 'discussion',
                'source': selected['discussion'],
                'statement': selected['statement'],
                'question_text': _ensure_question_text(
                    selected['statement'].content,
                    selected['discussion'].title
                ),
                'context': _build_discussion_context(selected['statement'], selected['discussion']),
                'why_this_question': _build_why_this_question(
                    source_type='discussion',
                    topic_category=selected['discussion'].topic,
                    source=selected['discussion']
                ),
                'topic_category': selected['discussion'].topic,
                'discussion_slug': selected['discussion'].slug,
                'engagement_score': selected['score']
            }

    # Try trending topics with engagement scoring
    topics = get_eligible_trending_topics()
    if topics:
        topics_with_statements = [topic for topic in topics if topic.seed_statements]
        if topics_with_statements:
            # Score each topic
            scored_topics = []
            for topic in topics_with_statements:
                score, breakdown = calculate_topic_engagement_score(topic)
                scored_topics.append({
                    'topic': topic,
                    'score': score,
                    'breakdown': breakdown
                })

            # Sort and take top candidates
            scored_topics.sort(key=lambda x: x['score'], reverse=True)
            top_topics = scored_topics[:8]

            # Weighted random first pick, then walk remaining top topics if that
            # topic only has non-votable hedge seeds.
            scores = [t['score'] for t in top_topics]
            selected = weighted_random_choice(top_topics, scores)
            ordered = []
            if selected:
                ordered.append(selected)
            ordered.extend(t for t in top_topics if t is not selected)

            for candidate in ordered:
                topic = candidate['topic']
                best = _best_votable_seed(topic)
                if not best:
                    continue
                _seed, best_statement_text, _controversy = best
                question_text = _ensure_question_text(best_statement_text, None)
                if not question_text or not is_votable_claim(question_text):
                    continue
                current_app.logger.info(
                    "Selected trending topic with engagement score %.2f",
                    candidate['score'],
                )
                return {
                    'source_type': 'trending',
                    'source': topic,
                    'statement': None,
                    'question_text': question_text,
                    'context': _build_trending_context(topic),
                    'why_this_question': _build_why_this_question(
                        source_type='trending',
                        topic_category=topic.primary_topic,
                        source=topic,
                    ),
                    'topic_category': topic.primary_topic,
                    'discussion_slug': None,
                    'engagement_score': candidate['score'],
                }

    # Fallback to standalone statements with scoring
    statements = get_eligible_statements()
    if statements:
        scored_statements = []
        for stmt in statements[:20]:
            score, breakdown = calculate_statement_engagement_score(stmt, stmt.discussion)
            scored_statements.append({
                'statement': stmt,
                'score': score,
                'breakdown': breakdown
            })

        scored_statements.sort(key=lambda x: x['score'], reverse=True)
        top_statements = scored_statements[:10]

        scores = [s['score'] for s in top_statements]
        selected = weighted_random_choice(top_statements, scores)

        if selected:
            stmt = selected['statement']
            return {
                'source_type': 'statement',
                'source': stmt,
                'statement': stmt,
                'question_text': _ensure_question_text(
                    stmt.content,
                    stmt.discussion.title if stmt.discussion else "Should this statement be supported?"
                ),
                'context': _build_statement_context(stmt),
                'why_this_question': _build_why_this_question(
                    source_type='statement',
                    topic_category=stmt.discussion.topic if stmt.discussion else None,
                    source=stmt
                ),
                'topic_category': stmt.discussion.topic if stmt.discussion else None,
                'discussion_slug': stmt.discussion.slug if stmt.discussion else None,
                'engagement_score': selected['score']
            }

    return None


class DuplicateDateError(Exception):
    """Raised when a question already exists for the specified date"""
    pass


def _apply_source_info_to_question(question, source_info):
    """Update an existing scheduled question from a new source selection."""
    source = source_info['source']
    source_type = source_info['source_type']
    statement = source_info.get('statement')

    question.question_text = source_info['question_text']
    question.context = source_info.get('context')
    question.why_this_question = source_info.get('why_this_question')
    question.topic_category = source_info.get('topic_category')
    question.source_type = source_type
    question.source_discussion_id = None
    question.source_statement_id = None
    question.source_trending_topic_id = None
    question.source_brief_item_id = None
    question.coverage_frame_json = source_info.get('coverage_frame')
    question.contestability_score = source_info.get('contestability_score')

    if source_type == 'discussion':
        question.source_discussion_id = source.id
        if statement:
            question.source_statement_id = statement.id
    elif source_type == BRIEF_SOURCE_TYPE:
        question.source_trending_topic_id = source_info.get('source_trending_topic_id') or source.id
        question.source_brief_item_id = source_info.get('source_brief_item_id')
        if source_info.get('brief_item'):
            question.source_brief_item_id = source_info['brief_item'].id
        if source_info.get('source_discussion_id'):
            question.source_discussion_id = source_info['source_discussion_id']
        elif getattr(source, 'discussion_id', None):
            question.source_discussion_id = source.discussion_id
        question.source_statement_id = source_info.get('source_statement_id')
        if not question.source_statement_id and question.source_discussion_id:
            question.source_statement_id = resolve_brief_primary_statement_id(
                question.question_text, question.source_discussion_id
            )
    elif source_type == 'trending':
        question.source_trending_topic_id = source.id
    elif source_type == 'statement':
        question.source_statement_id = source.id
        if hasattr(source, 'discussion') and source.discussion:
            question.source_discussion_id = source.discussion.id


def upsert_daily_question_from_source(question_date, source_info, created_by_id=None):
    """
    Create or replace a scheduled daily question from source_info.

    Never overwrites a published question.
    """
    existing = DailyQuestion.query.filter_by(question_date=question_date).first()
    if existing and existing.status == 'published':
        return existing

    if existing:
        _apply_source_info_to_question(existing, source_info)
        selection = DailyQuestionSelection.query.filter_by(
            daily_question_id=existing.id
        ).first()
        if not selection:
            selection = DailyQuestionSelection(
                question_date=question_date,
                daily_question_id=existing.id,
            )
            db.session.add(selection)
        _update_selection_from_source_info(selection, source_info, question_date)
        db.session.commit()
        current_app.logger.info(
            "Updated scheduled daily question for %s from %s",
            question_date,
            source_info['source_type'],
        )
        return existing

    return create_daily_question_from_source(question_date, source_info, created_by_id=created_by_id)


def _update_selection_from_source_info(selection, source_info, question_date):
    source = source_info['source']
    source_type = source_info['source_type']
    statement = source_info.get('statement')

    selection.source_type = source_type
    selection.question_date = question_date
    selection.source_discussion_id = None
    selection.source_statement_id = None
    selection.source_trending_topic_id = None
    selection.source_brief_item_id = None
    selection.selected_at = utcnow_naive()

    if source_type == 'discussion':
        selection.source_discussion_id = source.id
        if statement:
            selection.source_statement_id = statement.id
    elif source_type == BRIEF_SOURCE_TYPE:
        selection.source_trending_topic_id = source_info.get('source_trending_topic_id') or source.id
        selection.source_brief_item_id = source_info.get('source_brief_item_id')
        if source_info.get('source_discussion_id'):
            selection.source_discussion_id = source_info['source_discussion_id']
        elif getattr(source, 'discussion_id', None):
            selection.source_discussion_id = source.discussion_id
        selection.source_statement_id = source_info.get('source_statement_id')
        if not selection.source_statement_id and selection.source_discussion_id:
            selection.source_statement_id = resolve_brief_primary_statement_id(
                source_info.get('question_text'), selection.source_discussion_id
            )
    elif source_type == 'trending':
        selection.source_trending_topic_id = source.id
    elif source_type == 'statement':
        selection.source_statement_id = source.id
        if hasattr(source, 'discussion') and source.discussion:
            selection.source_discussion_id = source.discussion.id


def create_daily_question_from_source(question_date, source_info, created_by_id=None):
    """Create a DailyQuestion from the selected source.
    
    Raises:
        DuplicateDateError: If a question already exists for this date (concurrent scheduling)
        IntegrityError: For other database integrity issues
    """
    source = source_info['source']
    source_type = source_info['source_type']
    statement = source_info.get('statement')
    
    source_discussion_id = None
    source_statement_id = None
    source_trending_topic_id = None
    source_brief_item_id = None
    coverage_frame_json = source_info.get('coverage_frame')
    contestability_score = source_info.get('contestability_score')
    
    if source_type == 'discussion':
        source_discussion_id = source.id
        if statement:
            source_statement_id = statement.id
    elif source_type == BRIEF_SOURCE_TYPE:
        source_trending_topic_id = source_info.get('source_trending_topic_id') or source.id
        source_brief_item_id = source_info.get('source_brief_item_id')
        if source_info.get('brief_item'):
            source_brief_item_id = source_info['brief_item'].id
        if source_info.get('source_discussion_id'):
            source_discussion_id = source_info['source_discussion_id']
        elif getattr(source, 'discussion_id', None):
            source_discussion_id = source.discussion_id
        source_statement_id = source_info.get('source_statement_id')
        if not source_statement_id and source_discussion_id:
            source_statement_id = resolve_brief_primary_statement_id(
                source_info.get('question_text'), source_discussion_id
            )
    elif source_type == 'trending':
        source_trending_topic_id = source.id
    elif source_type == 'statement':
        source_statement_id = source.id
        if hasattr(source, 'discussion') and source.discussion:
            source_discussion_id = source.discussion.id
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            next_number = DailyQuestion.get_next_question_number()
            
            question = DailyQuestion(
                question_date=question_date,
                question_number=next_number,
                question_text=source_info['question_text'],
                context=source_info.get('context'),
                why_this_question=source_info.get('why_this_question'),
                topic_category=source_info.get('topic_category'),
                source_type=source_type,
                source_discussion_id=source_discussion_id,
                source_trending_topic_id=source_trending_topic_id,
                source_brief_item_id=source_brief_item_id,
                coverage_frame_json=coverage_frame_json,
                contestability_score=contestability_score,
                source_statement_id=source_statement_id,
                status='scheduled',
                created_by_id=created_by_id
            )
            
            db.session.add(question)
            db.session.flush()
            
            selection = DailyQuestionSelection(
                source_type=source_type,
                source_discussion_id=source_discussion_id,
                source_trending_topic_id=source_trending_topic_id,
                source_brief_item_id=source_brief_item_id,
                source_statement_id=source_statement_id,
                question_date=question_date,
                daily_question_id=question.id
            )
            db.session.add(selection)
            
            db.session.commit()
            
            current_app.logger.info(f"Auto-created daily question #{next_number} for {question_date} from {source_type}")
            return question
            
        except IntegrityError as e:
            db.session.rollback()
            
            if is_duplicate_date_error(e):
                current_app.logger.info(f"Question for {question_date} already exists (concurrent scheduling)")
                raise DuplicateDateError(f"Question already exists for {question_date}")
            
            error_str = str(e).lower()
            if 'question_number' in error_str and attempt < max_retries - 1:
                current_app.logger.warning(f"Question number conflict, retrying (attempt {attempt + 1})")
                continue
            
            raise


def auto_schedule_upcoming_questions(days_ahead=7):
    """Auto-schedule questions for the next N days if not already scheduled"""
    today = date.today()
    scheduled_count = 0
    
    for i in range(days_ahead):
        target_date = today + timedelta(days=i)
        
        existing = DailyQuestion.query.filter_by(question_date=target_date).first()
        if existing:
            continue
        
        source_info = select_next_question_source(question_date=target_date)
        if source_info:
            try:
                create_daily_question_from_source(target_date, source_info)
                scheduled_count += 1
            except DuplicateDateError:
                pass
            except Exception as e:
                current_app.logger.error(f"Error auto-scheduling question for {target_date}: {e}")
                db.session.rollback()
        else:
            current_app.logger.warning(f"No eligible content found for auto-scheduling {target_date}")
    
    return scheduled_count


def auto_publish_todays_question():
    """Auto-publish today's scheduled question if not already published"""
    today = date.today()
    
    question = DailyQuestion.query.filter_by(question_date=today).first()
    
    if not question:
        source_info = select_next_question_source(question_date=today)
        if source_info:
            try:
                question = create_daily_question_from_source(today, source_info)
            except DuplicateDateError:
                question = DailyQuestion.query.filter_by(question_date=today).first()
            except Exception as e:
                current_app.logger.error(f"Error creating today's question: {e}")
                db.session.rollback()
                return None
        else:
            current_app.logger.warning("No content available for today's daily question")
            return None
    
    if question and question.status != 'published':
        question.status = 'published'
        question.published_at = utcnow_naive()
        db.session.commit()
        current_app.logger.info(f"Auto-published daily question #{question.question_number}")

    return question


def select_questions_for_weekly_digest(days_back=7, count=5):
    """Re-export — implementation in ``app.daily.question_digest_selection``."""
    from app.daily.question_digest_selection import select_questions_for_weekly_digest as _select

    return _select(days_back=days_back, count=count)


def select_questions_for_monthly_digest(days_back=30, count=10):
    """Re-export — implementation in ``app.daily.question_digest_selection``."""
    from app.daily.question_digest_selection import select_questions_for_monthly_digest as _select

    return _select(days_back=days_back, count=count)
