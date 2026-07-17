"""
Balanced Seed Statement Generator

Generates diverse seed statements for trending topics or raw content
to kick-start nuanced discussions (Pol.is-style Agree / Disagree / Unsure).

Supports two modes:
1. TrendingTopic mode: Pass a TrendingTopic object to generate statements from its articles
2. Raw content mode: Pass title, excerpt, and optionally source_name to generate statements
"""

import os
import logging
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Iterable, Sequence, Set, Tuple
from functools import partial

from app.models import TrendingTopic
from app.discussions.thresholds import CONSENSUS_RECOMMENDED_STATEMENT_COUNT
from app.lib.claim_craft import is_question_form as _is_question_form
from app.lib.llm_transient_errors import log_llm_error

logger = logging.getLogger(__name__)

# Single source of truth for the recommended seed floor (consensus UX + generation).
DEFAULT_SEED_COUNT = CONSENSUS_RECOMMENDED_STATEMENT_COUNT

# Over-ask the model so de-duplication still leaves enough to hit the floor.
_SEED_OVERSAMPLE = 3

# Maximum provider rounds (initial pass + one targeted retry) before deterministic padding.
_SEED_MAX_ROUNDS = 2

_VALID_POSITIONS = ('pro', 'con', 'neutral')
_VALID_INTENTS = ('divisive', 'bridge')

# Platform hard ceiling (forms / DB). Not a Pol.is-style craft target.
_STATEMENT_HARD_MAX_CHARS = 500

# Soft craft band inspired by Pol.is (~140 chars): prefer concise, never truncate
# a strong claim solely for length.
_SOFT_LENGTH_IDEAL_MAX = 180
_SOFT_LENGTH_STRETCH_MAX = 280

# Near-duplicate Jaccard threshold on content tokens (exact match is separate).
# High enough to catch paraphrases; distinct numbered claims with shared
# scaffolding still need enough unique tokens to survive.
_NEAR_DUPE_JACCARD = 0.78
_NEAR_DUPE_MIN_SHARED = 5

def _openai_seed_model() -> str:
    # Override with SEED_OPENAI_MODEL (e.g. gpt-4o) when seed quality warrants cost.
    return os.environ.get('SEED_OPENAI_MODEL', 'gpt-4o-mini')


def _anthropic_seed_model() -> str:
    return os.environ.get('SEED_ANTHROPIC_MODEL', 'claude-haiku-4-5-20251001')


def _trim_text(text: Optional[str], max_length: int) -> str:
    """Trim text safely at a word boundary."""
    if not text:
        return ""
    clean = " ".join(str(text).split())
    if len(clean) <= max_length:
        return clean
    cutoff = clean[: max_length - 1].rstrip()
    last_space = cutoff.rfind(" ")
    if last_space > int(max_length * 0.6):
        cutoff = cutoff[:last_space]
    return f"{cutoff}..."


def _normalize_content(text: Optional[str]) -> str:
    return " ".join(str(text or "").split())


def _content_key(text: Optional[str]) -> str:
    return _normalize_content(text).lower()


def _normalize_position(position: Optional[str]) -> str:
    pos = (position or 'neutral').strip().lower()
    return pos if pos in _VALID_POSITIONS else 'neutral'


def _normalize_intent(intent: Optional[str], position: str) -> str:
    """
    Intent is orthogonal to stance: divisive vs bridge (consensus-capable).

    Defaults: pro/con → divisive; neutral → bridge when the model omits intent.
    """
    value = (intent or '').strip().lower()
    if value in _VALID_INTENTS:
        return value
    return 'bridge' if position == 'neutral' else 'divisive'


def _min_bridge_count(count: int) -> int:
    """How many bridge (consensus-capable) claims a seed set should include."""
    if count < 3:
        return 0
    if count < 6:
        return 1
    return min(2, max(1, count // 5))


def _bridge_count(statements: Iterable[Dict]) -> int:
    return sum(
        1 for s in statements
        if _normalize_intent(s.get('intent'), _normalize_position(s.get('position'))) == 'bridge'
    )


def _build_topic_context(topic: TrendingTopic) -> str:
    """Build richer topic context with titles + short article summaries."""
    lines = []
    if topic.description:
        lines.append(f"Topic summary:\n{_trim_text(topic.description, 600)}")

    article_lines = []
    for association in topic.articles.limit(5).all():
        article = association.article
        if not article:
            continue
        title = _trim_text(article.title, 180)
        source_name = article.source.name if getattr(article, 'source', None) else None
        summary = _trim_text(article.summary, 280) if article.summary else ""

        parts = [f"- {title}"]
        if source_name:
            parts.append(f"({source_name})")
        if summary:
            parts.append(f": {summary}")
        article_lines.append(" ".join(parts))

    if article_lines:
        lines.append("Related reporting:\n" + "\n".join(article_lines))

    return "\n\n".join(lines)


_COMPOUND_MARKERS = (
    " and also ",
    "; and ",
    ". additionally",
    ". moreover",
    ". meanwhile",
    ". further,",
    " — and ",
    " - and ",
    ", ensuring that ",
    ", ensuring ",
    " while also ",
    " whilst also ",
    ", while also ",
    ", whilst ",
)

_CLAIM_TOKENS = (
    " should ",
    " must ",
    " because ",
    " ought ",
    " needs to ",
    " cannot ",
    " will ",
    " would ",
)

_TOKEN_STOPWORDS = frozenset({
    "the", "and", "for", "that", "this", "with", "from", "are", "was", "were",
    "been", "being", "have", "has", "had", "not", "but", "its", "our", "their",
    "they", "them", "who", "which", "will", "would", "could", "should", "must",
    "into", "onto", "about", "over", "under", "than", "then", "also", "only",
    "more", "most", "some", "any", "all", "each", "other", "such", "than",
})


def _looks_compound_idea(content: str) -> bool:
    """
    Soft signal that a statement packs more than one votable idea.

    Pol.is moderates these out because Agree/Disagree becomes ambiguous.
    Used for ranking preference only — never a hard discard. Atomicity is
    primarily enforced in the few-shot prompt.
    """
    text = _normalize_content(content)
    if not text:
        return False
    lower = f" {text.lower()} "
    if any(marker in lower for marker in _COMPOUND_MARKERS):
        return True

    # Two or more substantial sentence-like chunks ≈ multiple ideas.
    parts = [p.strip() for p in re.split(r"[.!;]", text) if len(p.strip()) >= 20]
    if len(parts) >= 2:
        return True

    claim_parts = 0
    for part in [p.strip() for p in re.split(r"[.!;]", text) if len(p.strip()) >= 12]:
        padded = f" {part.lower()} "
        if any(token in padded for token in _CLAIM_TOKENS):
            claim_parts += 1
    return claim_parts >= 2


def _content_tokens(text: str) -> Set[str]:
    tokens = set(re.findall(r"[a-z0-9']+", _normalize_content(text).lower()))
    return {t for t in tokens if len(t) > 2 and t not in _TOKEN_STOPWORDS}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_near_duplicate(content: str, existing_contents: Iterable[str]) -> bool:
    """Token-overlap near-dedup (not embeddings) to avoid splitting the vote."""
    tokens = _content_tokens(content)
    if len(tokens) < 5:
        return False
    for other in existing_contents:
        other_tokens = _content_tokens(other)
        shared = len(tokens & other_tokens)
        if shared < _NEAR_DUPE_MIN_SHARED:
            continue
        if _jaccard(tokens, other_tokens) >= _NEAR_DUPE_JACCARD:
            return True
    return False


def _looks_specific_enough(content: str) -> bool:
    """
    Soft quality preference for daily-voting stand-alone statements.

    Used only for ordering within a stance bucket — never to discard valid
    statements. Hard filters here previously starved discussions of seeds.
    """
    text = (content or "").strip()
    if len(text) < 40:
        return False
    if _is_question_form(text):
        return False

    words = [w for w in text.split() if w.strip()]
    if len(words) < 6:
        return False

    lower = text.lower()
    vague_starts = ("this ", "these ", "it ", "they ", "there ")
    if lower.startswith(vague_starts):
        return False

    has_alpha = any(ch.isalpha() for ch in text)
    has_claim_structure = any(token in f" {lower} " for token in _CLAIM_TOKENS)
    return has_alpha and has_claim_structure


def _length_soft_penalty(content: str) -> int:
    """
    Mild ranking penalty for verbosity. Never rejects; longer is fine when
    needed for a hard-hitting single claim.
    """
    length = len(_normalize_content(content))
    if length <= _SOFT_LENGTH_IDEAL_MAX:
        return 0
    if length <= _SOFT_LENGTH_STRETCH_MAX:
        return 1
    if length <= 400:
        return 2
    return 3


def _claim_quality_sort_key(content: str) -> tuple:
    """Lower tuple sorts first: specific, single-idea, concise-but-not-truncated."""
    text = _normalize_content(content)
    return (
        not _looks_specific_enough(text),
        _looks_compound_idea(text),
        _length_soft_penalty(text),
        len(text),
        text.lower(),
    )


@dataclass
class _ParseStats:
    parsed: int = 0
    kept: int = 0
    dropped_question: int = 0
    dropped_dupe: int = 0
    dropped_near_dupe: int = 0
    dropped_empty: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            'parsed': self.parsed,
            'kept': self.kept,
            'dropped_question': self.dropped_question,
            'dropped_dupe': self.dropped_dupe,
            'dropped_near_dupe': self.dropped_near_dupe,
            'dropped_empty': self.dropped_empty,
        }


@dataclass
class _GenerationFocus:
    """What the next LLM round should prioritise."""
    request_count: int
    focus_positions: Tuple[str, ...] = field(default_factory=tuple)
    need_bridge: int = 0

    @property
    def is_targeted(self) -> bool:
        return bool(self.focus_positions) or self.need_bridge > 0


def _stance_counts(statements: Iterable[Dict]) -> Counter:
    return Counter(_normalize_position(s.get('position')) for s in statements)


def _generation_shortfall(collected: Sequence[Dict], count: int) -> Optional[_GenerationFocus]:
    """
    Decide whether another LLM round is needed, and what it should ask for.

    Retries on short count, missing stance, or missing bridge claims — not only
    on raw length (which previously left lopsided sets on canned fallbacks).
    """
    present = _stances_present(collected)
    missing_positions = [p for p in _VALID_POSITIONS if p not in present]
    bridges = _bridge_count(collected)
    bridges_needed = max(0, _min_bridge_count(count) - bridges)
    short_on_count = max(0, count - len(collected))

    # Under-weight stances even when count is met (e.g. 8 pro / 1 con / 1 neutral).
    counts = _stance_counts(collected)
    if len(collected) >= count and count >= 3:
        target_each = max(1, count // 3)
        underweight = [
            pos for pos in _VALID_POSITIONS
            if counts.get(pos, 0) < target_each and pos not in missing_positions
        ]
    else:
        underweight = []

    focus_positions = tuple(dict.fromkeys(missing_positions + underweight))
    needs_work = short_on_count > 0 or bool(focus_positions) or bridges_needed > 0
    if not needs_work:
        return None

    request_count = max(
        short_on_count + bridges_needed + len(focus_positions) * 2,
        min(count, _SEED_OVERSAMPLE + max(2, bridges_needed + len(focus_positions))),
    )
    return _GenerationFocus(
        request_count=max(2, request_count),
        focus_positions=focus_positions,
        need_bridge=bridges_needed,
    )


def _fallback_seed_statements(
    title: Optional[str],
    excerpt: Optional[str],
    count: int
) -> List[Dict]:
    """
    Deterministic fallback statements when providers are unavailable/rate-limited.
    Keeps create-discussion endpoints functional under quota pressure.
    """
    subject = _trim_text(title or "this issue", 100)
    # Ignore excerpt in the claim body: appending context creates compound,
    # multi-idea statements that are hard to Agree/Disagree with cleanly.

    # Ordered so any prefix stays balanced across pro / con / neutral + bridge.
    templates = [
        ("pro", "divisive", f"Government should take decisive action on {subject} this year."),
        ("con", "divisive", f"Current plans on {subject} will do more harm than good."),
        ("neutral", "bridge", f"Any credible approach to {subject} must publish clear success metrics first."),
        ("pro", "divisive", f"Targeted public investment in {subject} is overdue and would strengthen society."),
        ("con", "divisive", f"Mandating major changes on {subject} now overburdens people without proven benefit."),
        ("neutral", "bridge", f"Leaders deciding {subject} should be publicly accountable for the trade-offs they accept."),
        ("pro", "divisive", f"People most affected by {subject} must have a real say before decisions are final."),
        ("con", "divisive", f"The costs of acting on {subject} are being understated and demand harder scrutiny."),
        ("neutral", "bridge", f"Debate on {subject} should start from shared facts, not partisan talking points."),
        ("pro", "divisive", f"Delaying action on {subject} is itself a choice that will leave lasting damage."),
        ("con", "divisive", f"Rushing policy on {subject} risks locking in mistakes that are hard to reverse."),
        ("neutral", "bridge", f"Compromise on {subject} is preferable to winner-takes-all outcomes that fracture trust."),
    ]
    return [
        {
            "content": content[:_STATEMENT_HARD_MAX_CHARS],
            "position": position,
            "intent": intent,
        }
        for position, intent, content in templates[:max(1, min(count, len(templates)))]
    ]


def _select_balanced(statements: Iterable[Dict], count: int) -> List[Dict]:
    """
    Build a seed set that spans pro/con/neutral and includes bridge claims.

    Within each bucket, prefer hard-hitting single-idea claims (Pol.is craft),
    with only a soft preference for brevity — never discard a strong longer claim.
    """
    items = []
    for stmt in statements:
        content = _normalize_content(stmt.get('content'))
        if not content:
            continue
        position = _normalize_position(stmt.get('position'))
        intent = _normalize_intent(stmt.get('intent'), position)
        items.append({
            'content': content[:_STATEMENT_HARD_MAX_CHARS],
            'position': position,
            'intent': intent,
            '_rank': _claim_quality_sort_key(content),
        })

    if not items:
        return []

    selected: List[Dict] = []
    selected_keys: Set[str] = set()

    def _take(item: Dict) -> None:
        key = item['content'].lower()
        if key in selected_keys or len(selected) >= count:
            return
        selected_keys.add(key)
        selected.append({
            'content': item['content'],
            'position': item['position'],
            'intent': item['intent'],
        })

    # 1) Guarantee bridge coverage first (Pol.is consensus surface).
    bridges = sorted(
        (i for i in items if i['intent'] == 'bridge'),
        key=lambda s: s['_rank'],
    )
    for item in bridges[:_min_bridge_count(count)]:
        _take(item)

    # 2) Guarantee one of each stance when possible.
    if count >= 3:
        for pos in _VALID_POSITIONS:
            if any(s['position'] == pos for s in selected):
                continue
            candidates = sorted(
                (i for i in items if i['position'] == pos and i['content'].lower() not in selected_keys),
                key=lambda s: s['_rank'],
            )
            if candidates:
                _take(candidates[0])

    # 3) Fill remaining slots round-robin by stance, quality-ordered within stance.
    buckets = {pos: [] for pos in _VALID_POSITIONS}
    for item in items:
        if item['content'].lower() in selected_keys:
            continue
        buckets[item['position']].append(item)
    for pos in _VALID_POSITIONS:
        buckets[pos].sort(key=lambda s: s['_rank'])

    indices = {pos: 0 for pos in _VALID_POSITIONS}
    while len(selected) < count:
        progressed = False
        for pos in _VALID_POSITIONS:
            if len(selected) >= count:
                break
            i = indices[pos]
            if i < len(buckets[pos]):
                _take(buckets[pos][i])
                indices[pos] = i + 1
                progressed = True
        if not progressed:
            break

    return selected


def _stances_present(statements: Iterable[Dict]) -> set:
    return {_normalize_position(s.get('position')) for s in statements}


def _pad_and_finalize(
    collected: List[Dict],
    title: Optional[str],
    excerpt: Optional[str],
    count: int,
    exclude_contents: Optional[Iterable[str]] = None,
) -> List[Dict]:
    """Guarantee ``count`` de-duplicated, spectrum-balanced, bridge-aware statements."""
    working = []
    seen = {_content_key(c) for c in (exclude_contents or []) if c}
    existing_for_near = [c for c in (exclude_contents or []) if c]

    for stmt in collected:
        content = _normalize_content(stmt.get('content'))
        if not content or _is_question_form(content):
            continue
        key = content.lower()
        if key in seen:
            continue
        if _is_near_duplicate(content, existing_for_near):
            continue
        seen.add(key)
        existing_for_near.append(content)
        position = _normalize_position(stmt.get('position'))
        working.append({
            'content': content[:_STATEMENT_HARD_MAX_CHARS],
            'position': position,
            'intent': _normalize_intent(stmt.get('intent'), position),
        })

    need_count = len(working) < count
    need_spectrum = count >= 3 and not set(_VALID_POSITIONS).issubset(_stances_present(working))
    need_bridge = _bridge_count(working) < _min_bridge_count(count)

    if need_count or need_spectrum or need_bridge:
        if need_count:
            logger.warning(
                "Padding seed set to floor (%d/%d) with deterministic fallback",
                len(working), count,
            )
        elif need_spectrum or need_bridge:
            logger.info(
                "Injecting fallback statements to restore spectrum/bridge coverage "
                "(spectrum_ok=%s bridge=%d/%d)",
                not need_spectrum,
                _bridge_count(working),
                _min_bridge_count(count),
            )

        present = _stances_present(working)
        missing = [p for p in _VALID_POSITIONS if p not in present]
        fallback = _fallback_seed_statements(
            title=title, excerpt=excerpt, count=max(count, len(_VALID_POSITIONS) * 4)
        )
        # Prefer missing stances and bridge intents first.
        ordered_fallback = (
            [s for s in fallback if s['position'] in missing]
            + [s for s in fallback if s.get('intent') == 'bridge']
            + [s for s in fallback if s['position'] not in missing and s.get('intent') != 'bridge']
        )
        for stmt in ordered_fallback:
            key = _content_key(stmt.get('content'))
            if not key or key in seen:
                continue
            if _is_near_duplicate(stmt['content'], existing_for_near):
                continue
            pos = _normalize_position(stmt.get('position'))
            intent = _normalize_intent(stmt.get('intent'), pos)
            fills_gap = (
                pos not in _stances_present(working)
                or (intent == 'bridge' and _bridge_count(working) < _min_bridge_count(count))
            )
            if len(working) >= count and not fills_gap:
                if (
                    set(_VALID_POSITIONS).issubset(_stances_present(working))
                    and _bridge_count(working) >= _min_bridge_count(count)
                ):
                    break
                continue
            seen.add(key)
            existing_for_near.append(stmt['content'])
            working.append({
                'content': stmt['content'][:_STATEMENT_HARD_MAX_CHARS],
                'position': pos,
                'intent': intent,
            })
            if (
                len(working) >= count
                and set(_VALID_POSITIONS).issubset(_stances_present(working))
                and _bridge_count(working) >= _min_bridge_count(count)
            ):
                break

    finalized = _select_balanced(working, count)
    if len(finalized) < count:
        logger.error(
            "Seed finalization could only produce %d/%d statements for title=%r",
            len(finalized), count, _trim_text(title, 80),
        )
    else:
        logger.info(
            "Seed finalization complete title=%r count=%d stances=%s bridges=%d",
            _trim_text(title, 80),
            len(finalized),
            dict(_stance_counts(finalized)),
            _bridge_count(finalized),
        )
    # Public payload keeps content + position; intent is generation metadata.
    return [{'content': s['content'], 'position': s['position']} for s in finalized]


def generate_seed_statements(
    topic: Optional[TrendingTopic] = None,
    title: Optional[str] = None,
    excerpt: Optional[str] = None,
    source_name: Optional[str] = None,
    count: int = DEFAULT_SEED_COUNT,
    exclude_contents: Optional[Iterable[str]] = None,
) -> List[Dict]:
    """
    Generate balanced seed statements for a topic or from raw content.

    Guarantees a list of up to ``count`` de-duplicated, spectrum-balanced
    statements with bridge (consensus-capable) coverage: over-asks the LLM,
    retries with a stance/bridge-targeted prompt when short or lopsided, and
    pads with deterministic templates only as a last resort.

    Args:
        topic: TrendingTopic object (existing behavior)
        title: Article/topic title for raw content mode
        excerpt: Article excerpt/summary for raw content mode
        source_name: Optional source attribution for raw content mode
        count: Target number of statements (default: recommended floor of 10)
        exclude_contents: Existing statement texts to skip (backfill / merge)

    Raises:
        ValueError: If neither topic nor title is provided
    """
    if not topic and not title:
        raise ValueError("Either topic or title must be provided")

    count = max(1, int(count))
    resolved_title = title or (topic.title if topic else None)
    resolved_excerpt = excerpt or (topic.description if topic else None)

    openai_key = os.environ.get('OPENAI_API_KEY')
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')

    # OpenAI preferred; Anthropic only runs while still short of quality targets.
    providers = []
    if openai_key:
        providers.append(("openai", partial(_generate_with_openai, api_key=openai_key)))
    if anthropic_key:
        providers.append(("anthropic", partial(_generate_with_anthropic, api_key=anthropic_key)))

    collected: List[Dict] = []
    seen = {_content_key(c) for c in (exclude_contents or []) if c}
    near_existing = [c for c in (exclude_contents or []) if c]
    aggregate_stats = _ParseStats()

    def _merge_stats(stats: _ParseStats) -> None:
        for key, value in stats.as_dict().items():
            setattr(aggregate_stats, key, getattr(aggregate_stats, key) + value)

    def _absorb(candidates: Optional[List[Dict]]) -> int:
        """Add pre-validated candidates; return how many were kept."""
        kept_here = 0
        for stmt in candidates or []:
            content = _normalize_content(stmt.get('content'))
            if not content or _is_question_form(content):
                # Should already be filtered in parse; count defensive drops.
                aggregate_stats.dropped_question += 1
                continue
            key = content.lower()
            if key in seen:
                aggregate_stats.dropped_dupe += 1
                continue
            if _is_near_duplicate(content, near_existing):
                aggregate_stats.dropped_near_dupe += 1
                continue
            seen.add(key)
            near_existing.append(content)
            position = _normalize_position(stmt.get('position'))
            collected.append({
                'content': content[:_STATEMENT_HARD_MAX_CHARS],
                'position': position,
                'intent': _normalize_intent(stmt.get('intent'), position),
            })
            kept_here += 1
        return kept_here

    for round_index in range(_SEED_MAX_ROUNDS):
        if not providers:
            break
        shortfall = _generation_shortfall(collected, count)
        if shortfall is None:
            if round_index == 0:
                focus = _GenerationFocus(request_count=count + _SEED_OVERSAMPLE)
            else:
                break
        else:
            # Round 0 asks for a full oversampled set (still may note bridge need).
            # Round 1+ is stance/bridge-targeted so we don't pad with more of the same.
            if round_index == 0:
                focus = _GenerationFocus(
                    request_count=count + _SEED_OVERSAMPLE,
                    focus_positions=(),
                    need_bridge=_min_bridge_count(count),
                )
            else:
                focus = shortfall

        if round_index > 0:
            logger.warning(
                "Seed generation retry round=%d title=%r focus_positions=%s need_bridge=%d "
                "have=%d/%d stances=%s bridges=%d",
                round_index + 1,
                _trim_text(resolved_title, 80),
                list(focus.focus_positions),
                focus.need_bridge,
                len(collected),
                count,
                dict(_stance_counts(collected)),
                _bridge_count(collected),
            )

        for name, provider in providers:
            if round_index > 0:
                shortfall = _generation_shortfall(collected, count)
                if shortfall is None:
                    break
                focus = shortfall
            elif _generation_shortfall(collected, count) is None and len(collected) > 0:
                break

            try:
                round_stats = _ParseStats()
                result = provider(
                    topic=topic,
                    title=title,
                    excerpt=excerpt,
                    source_name=source_name,
                    count=focus.request_count,
                    focus=focus if focus.is_targeted or round_index > 0 else None,
                    parse_stats=round_stats,
                    existing_contents=near_existing,
                )
                # Parse stats.kept == len(result). Absorb may still drop
                # cross-provider near-dupes; reconcile kept downward only then.
                _merge_stats(round_stats)
                kept_after_absorb = _absorb(result)
                absorb_rejects = max(0, round_stats.kept - kept_after_absorb)
                if absorb_rejects:
                    aggregate_stats.kept = max(0, aggregate_stats.kept - absorb_rejects)
                logger.info(
                    "Seed provider=%s round=%d stats=%s absorbed=%d collected=%d",
                    name,
                    round_index + 1,
                    round_stats.as_dict(),
                    kept_after_absorb,
                    len(collected),
                )
            except Exception as e:
                # Providers already swallow their own errors; keep publishing safe.
                log_llm_error(
                    logger, e,
                    context=f"{name} seed provider raised unexpectedly",
                )

        if _generation_shortfall(collected, count) is None:
            break

    if aggregate_stats.parsed:
        logger.info(
            "Seed generation aggregate title=%r stats=%s",
            _trim_text(resolved_title, 80),
            aggregate_stats.as_dict(),
        )
        drop_rate = (
            (aggregate_stats.dropped_question + aggregate_stats.dropped_dupe
             + aggregate_stats.dropped_near_dupe)
            / max(1, aggregate_stats.parsed)
        )
        if drop_rate >= 0.35:
            logger.warning(
                "High seed rejection rate %.0f%% title=%r stats=%s — prompt may be drifting",
                drop_rate * 100,
                _trim_text(resolved_title, 80),
                aggregate_stats.as_dict(),
            )

    if not providers:
        logger.warning("LLM seed generation unavailable; using deterministic fallback statements")
    elif _generation_shortfall(collected, count) is not None:
        logger.warning(
            "Seed generation still short after %d round(s); "
            "will pad with deterministic fallback statements (have=%d/%d stances=%s bridges=%d)",
            _SEED_MAX_ROUNDS,
            len(collected),
            count,
            dict(_stance_counts(collected)),
            _bridge_count(collected),
        )

    return _pad_and_finalize(
        collected,
        resolved_title,
        resolved_excerpt,
        count,
        exclude_contents=exclude_contents,
    )


# Convenience alias for raw content mode
generate_seed_statements_from_content = partial(generate_seed_statements, topic=None)


_FEW_SHOT_EXAMPLES = """
Examples (pattern-match these; adapt to the topic — do NOT copy verbatim):

✗ Question (invalid): "Can NATO balance old and new roles, or will it divide?"
✓ Claim (valid): "NATO should redirect a fixed share of its budget to cyber and drone defence."
  {"content": "NATO should redirect a fixed share of its budget to cyber and drone defence.", "position": "pro", "intent": "divisive"}

✗ Compound / two tests (invalid as one row): "NATO should prioritise democratic values, ensuring collective defence isn't compromised."
✓ Split into two claims:
  {"content": "NATO should prioritise democratic values among its member states.", "position": "pro", "intent": "divisive"}
  {"content": "NATO must not expand into new global roles if that weakens collective defence.", "position": "con", "intent": "divisive"}

✗ Hedge / non-claim (invalid): "Whether defence spending rises is a matter for governments."
✓ Conditional claim (valid): "Whether or not spending rises, the government must publish defence outcomes."
  {"content": "Whether or not spending rises, the government must publish defence outcomes.", "position": "neutral", "intent": "bridge"}
✓ Bridge claim (valid): "Defence budgets should be debated against clear public outcomes, not slogans."
  {"content": "Defence budgets should be debated against clear public outcomes, not slogans.", "position": "neutral", "intent": "bridge"}
"""


def _build_prompt(
    topic: Optional[TrendingTopic],
    title: Optional[str],
    excerpt: Optional[str],
    source_name: Optional[str],
    count: int,
    focus: Optional[_GenerationFocus] = None,
) -> str:
    """Build the prompt for seed statement generation."""
    if topic:
        topic_title = topic.title
        context_section = _build_topic_context(topic)
    else:
        topic_title = title
        context_parts = []
        if excerpt:
            context_parts.append(f"Summary:\n{excerpt}")
        if source_name:
            context_parts.append(f"Source: {source_name}")
        context_section = "\n\n".join(context_parts) if context_parts else ""

    focus_section = ""
    if focus and focus.is_targeted:
        parts = []
        if focus.focus_positions:
            parts.append(
                "PRIORITY THIS ROUND: return ONLY statements with position in "
                f"{list(focus.focus_positions)}. Do not add more of the already-covered stances."
            )
        if focus.need_bridge > 0:
            parts.append(
                f"PRIORITY THIS ROUND: include at least {focus.need_bridge} "
                'statements with "intent": "bridge" (broadly shareable agreement claims).'
            )
        focus_section = "\n".join(parts) + "\n"

    prompt = f"""Generate {count} diverse seed statements for a public deliberation on this topic:

Topic: {topic_title}

{context_section}

{focus_section}Requirements (Pol.is-style craft for Agree / Disagree / Unsure voting):
- Each item MUST be one clear, declarative, debatable CLAIM — never a question
- Do NOT use question marks, interrogative openers (What/Who/How/Can/Should…), "the question of", or "raises the question" framing
- Conditional claims are fine ("If X, Y must Z" / "Whether or not X, Y should Z"); bare hedges are not ("Whether X is a matter for…")
- ONE idea only per statement — no second testable claim via "ensuring that", "while also", or stacked clauses; if you have two points, emit two separate statements
- Someone must be able to Agree, Disagree, or say Unsure about the claim as written
- Make claims hard-hitting and concrete: name actors, policies, trade-offs, or outcomes
- Cover the full spectrum: strong pro, strong con, and genuine middle/conditional claims
- intent "divisive" = polarising / group-forming; intent "bridge" = broadly shareable agreement many people could accept
- Include both divisive claims AND bridge claims (consensus-capable). Bridge ≠ vague mush — still a crisp claim
- Prefer concise wording (roughly tweet-length) when the claim stays forceful
- Longer is fine when needed for precision or force — never pad, never soften a sharp claim to hit a word count
- Avoid strawmen — represent each position charitably but firmly
- Each statement must stand alone (no vague "this/it/they" unless the subject is named)
- Do not emit near-paraphrases of the same claim

{_FEW_SHOT_EXAMPLES}

Return as JSON array:
[
    {{"content": "statement text", "position": "pro", "intent": "divisive"}},
    {{"content": "statement text", "position": "con", "intent": "divisive"}},
    {{"content": "statement text", "position": "neutral", "intent": "bridge"}},
    ...
]

Return ONLY valid JSON array."""
    return prompt


def _extract_statements_payload(response_text: str) -> list:
    """
    Parse an LLM response into a Python list, tolerating markdown fences and
    truncated JSON where complete statement objects are still recoverable.
    """
    content = (response_text or "").strip()
    if content.startswith('```json'):
        content = content[7:]
    if content.startswith('```'):
        content = content[3:]
    if content.endswith('```'):
        content = content[:-3]
    content = content.strip()

    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get('statements'), list):
            return parsed['statements']
    except json.JSONDecodeError:
        pass

    array_match = re.search(r'\[[\s\S]*\]', content)
    if array_match:
        try:
            parsed = json.loads(array_match.group())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Truncated responses: recover complete objects that contain "content".
    recovered = []
    for match in re.finditer(r'\{[^{}]*"content"\s*:\s*"[^"]*"[^{}]*\}', content):
        try:
            obj = json.loads(match.group())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get('content'):
            recovered.append(obj)
    if recovered:
        logger.warning(
            "Recovered %d seed statement object(s) from truncated/non-JSON LLM response",
            len(recovered),
        )
        return recovered

    raise json.JSONDecodeError("Could not parse seed statements JSON", content, 0)


def _parse_and_validate_statements(
    response_text: str,
    count: int,
    existing_contents: Optional[Iterable[str]] = None,
    stats: Optional[_ParseStats] = None,
) -> List[Dict]:
    """
    Parse raw LLM response into validated statement dicts.

    Drops question-form / hedge text and exact/near duplicates. Soft quality
    scoring only reorders preference via ``_select_balanced``.
    """
    stats = stats if stats is not None else _ParseStats()
    statements = _extract_statements_payload(response_text)
    validated = []
    seen = set()
    near_existing = list(existing_contents or [])

    for stmt in statements:
        stats.parsed += 1
        if not (isinstance(stmt, dict) and 'content' in stmt):
            stats.dropped_empty += 1
            continue
        content_text = _normalize_content(stmt['content'])
        if not content_text:
            stats.dropped_empty += 1
            continue
        if _is_question_form(content_text):
            stats.dropped_question += 1
            continue
        key = content_text.lower()
        if key in seen:
            stats.dropped_dupe += 1
            continue
        if _is_near_duplicate(content_text, near_existing):
            stats.dropped_near_dupe += 1
            continue
        seen.add(key)
        near_existing.append(content_text)
        position = _normalize_position(stmt.get('position'))
        validated.append({
            'content': content_text[:_STATEMENT_HARD_MAX_CHARS],
            'position': position,
            'intent': _normalize_intent(stmt.get('intent'), position),
        })

    # Count kept only for items actually returned — truncating an oversampled
    # valid set is not a rejection and must not inflate the drift metric.
    validated = validated[:count]
    stats.kept = len(validated)
    return validated


def _generate_with_openai(
    topic: Optional[TrendingTopic],
    title: Optional[str],
    excerpt: Optional[str],
    source_name: Optional[str],
    count: int,
    api_key: str,
    focus: Optional[_GenerationFocus] = None,
    parse_stats: Optional[_ParseStats] = None,
    existing_contents: Optional[Iterable[str]] = None,
) -> List[Dict]:
    """Generate seeds using OpenAI."""
    try:
        import openai
    except ImportError:
        logger.error("OpenAI library not installed")
        return []

    try:
        # Match Anthropic: background seed jobs can wait out a 529/5xx burst.
        client = openai.OpenAI(api_key=api_key, timeout=60.0, max_retries=4)
    except Exception as e:
        logger.error(f"Failed to create OpenAI client: {e}")
        return []

    prompt = _build_prompt(topic, title, excerpt, source_name, count, focus=focus)

    try:
        response = client.chat.completions.create(
            model=_openai_seed_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write Pol.is-style seed claims for public deliberation. "
                        "Every item is one atomic declarative claim people can Agree, "
                        "Disagree, or mark Unsure on. Never questions. Never two ideas "
                        "in one sentence. Represent all sides firmly and charitably."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2500,
            temperature=0.7,
        )

        content = response.choices[0].message.content or ""
        return _parse_and_validate_statements(
            content,
            count,
            existing_contents=existing_contents,
            stats=parse_stats,
        )

    except (SystemExit, KeyboardInterrupt):
        logger.error("OpenAI call was interrupted (SystemExit/KeyboardInterrupt)")
        return []
    except Exception as e:
        log_llm_error(logger, e, context="OpenAI seed generation failed")
        return []


def _anthropic_message_text(message) -> str:
    """Extract text from an Anthropic Messages API response safely."""
    for block in getattr(message, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


def _generate_with_anthropic(
    topic: Optional[TrendingTopic],
    title: Optional[str],
    excerpt: Optional[str],
    source_name: Optional[str],
    count: int,
    api_key: str,
    focus: Optional[_GenerationFocus] = None,
    parse_stats: Optional[_ParseStats] = None,
    existing_contents: Optional[Iterable[str]] = None,
) -> List[Dict]:
    """Generate seeds using Anthropic."""
    try:
        import anthropic
    except ImportError:
        logger.error("Anthropic library not installed")
        return []

    try:
        # max_retries above the SDK default of 2: seed generation is a background
        # job, so it can afford to wait out a transient 529/5xx overload burst
        # (exponential backoff) before degrading to the next provider / fallback.
        client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=4)
    except Exception as e:
        logger.error(f"Failed to create Anthropic client: {e}")
        return []

    prompt = _build_prompt(topic, title, excerpt, source_name, count, focus=focus)
    system = (
        "You write Pol.is-style seed claims for public deliberation. "
        "Every item is one atomic declarative claim people can Agree, "
        "Disagree, or mark Unsure on. Never questions. Never two ideas "
        "in one sentence. Represent all sides firmly and charitably."
    )

    try:
        message = client.messages.create(
            model=_anthropic_seed_model(),
            max_tokens=2500,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )

        content = _anthropic_message_text(message)
        return _parse_and_validate_statements(
            content,
            count,
            existing_contents=existing_contents,
            stats=parse_stats,
        )

    except (SystemExit, KeyboardInterrupt):
        logger.error("Anthropic call was interrupted (SystemExit/KeyboardInterrupt)")
        return []
    except Exception as e:
        log_llm_error(logger, e, context="Anthropic seed generation failed")
        return []
