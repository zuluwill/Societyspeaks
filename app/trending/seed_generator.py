"""
Balanced Seed Statement Generator

Generates diverse seed statements for trending topics or raw content
to kick-start nuanced discussions.

Supports two modes:
1. TrendingTopic mode: Pass a TrendingTopic object to generate statements from its articles
2. Raw content mode: Pass title, excerpt, and optionally source_name to generate statements
"""

import os
import logging
import json
import re
from typing import List, Dict, Optional, Iterable
from functools import partial

from app.models import TrendingTopic
from app.discussions.thresholds import CONSENSUS_RECOMMENDED_STATEMENT_COUNT

logger = logging.getLogger(__name__)

# Single source of truth for the recommended seed floor (consensus UX + generation).
DEFAULT_SEED_COUNT = CONSENSUS_RECOMMENDED_STATEMENT_COUNT

# Over-ask the model so de-duplication still leaves enough to hit the floor.
_SEED_OVERSAMPLE = 3

# Maximum provider rounds (initial pass + one retry) before deterministic padding.
_SEED_MAX_ROUNDS = 2

_VALID_POSITIONS = ('pro', 'con', 'neutral')


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


def _looks_specific_enough(content: str) -> bool:
    """
    Soft quality preference for daily-voting stand-alone statements.

    Used only for ordering within a stance bucket — never to discard valid
    statements. Hard filters here previously starved discussions of seeds.
    """
    text = (content or "").strip()
    if len(text) < 40:
        return False

    words = [w for w in text.split() if w.strip()]
    if len(words) < 8:
        return False

    lower = text.lower()
    vague_starts = ("this ", "these ", "it ", "they ", "there ")
    if lower.startswith(vague_starts):
        return False

    has_alpha = any(ch.isalpha() for ch in text)
    has_claim_structure = any(
        token in lower
        for token in (" should ", " must ", " because ", " ought ", " needs to ", " cannot ", " will ")
    )
    return has_alpha and has_claim_structure


def _is_rate_limit_error(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "rate limit" in text
        or "too many requests" in text
        or "429" in text
        or "quota" in text
    )


def _is_timeout_error(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "timed out" in text
        or "timeout" in text
        or type(error).__name__ in ("APITimeoutError", "ReadTimeout", "ConnectTimeout")
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
    subject = _trim_text(title or "this issue", 120)
    summary = _trim_text(excerpt or "", 200)
    summary_tail = f" Context: {summary}" if summary else ""

    # Ordered so any prefix stays balanced across pro / con / neutral.
    templates = [
        ("pro", f"Public institutions should take stronger action on {subject} within the next year.{summary_tail}"),
        ("con", f"Current proposals on {subject} risk unintended harms and should be scaled back until the evidence improves.{summary_tail}"),
        ("neutral", f"What measurable outcomes should define success for policies related to {subject}, and over what timeframe?{summary_tail}"),
        ("pro", f"Targeted investment in {subject} could improve long-term social and economic resilience if it is delivered transparently.{summary_tail}"),
        ("con", f"Mandating major changes on {subject} now may overburden communities without delivering proportional benefits.{summary_tail}"),
        ("neutral", f"Who should be accountable for decisions on {subject}, and how should that accountability be enforced?{summary_tail}"),
        ("pro", f"Ordinary people affected by {subject} should have a direct say before any major decision is finalised.{summary_tail}"),
        ("con", f"The costs and trade-offs of acting on {subject} are being understated and deserve far closer scrutiny.{summary_tail}"),
        ("neutral", f"What evidence would change your mind about the right approach to {subject}?{summary_tail}"),
    ]
    return [
        {"content": content[:500], "position": position}
        for position, content in templates[:max(1, min(count, len(templates)))]
    ]


def _select_balanced(statements: Iterable[Dict], count: int) -> List[Dict]:
    """
    Round-robin across pro/con/neutral so the published seed set spans the spectrum.

    Within each stance, prefer statements that clear the soft specificity gate.
    """
    buckets = {pos: [] for pos in _VALID_POSITIONS}
    for stmt in statements:
        content = _normalize_content(stmt.get('content'))
        if not content:
            continue
        position = _normalize_position(stmt.get('position'))
        buckets[position].append({
            'content': content[:500],
            'position': position,
            '_specific': _looks_specific_enough(content),
        })

    for pos in _VALID_POSITIONS:
        buckets[pos].sort(key=lambda s: (not s['_specific'], s['content']))

    selected: List[Dict] = []
    indices = {pos: 0 for pos in _VALID_POSITIONS}
    while len(selected) < count:
        progressed = False
        for pos in _VALID_POSITIONS:
            if len(selected) >= count:
                break
            i = indices[pos]
            if i < len(buckets[pos]):
                item = buckets[pos][i]
                selected.append({'content': item['content'], 'position': item['position']})
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
    """Guarantee ``count`` de-duplicated, spectrum-balanced statements."""
    working = []
    seen = {_content_key(c) for c in (exclude_contents or []) if c}
    for stmt in collected:
        content = _normalize_content(stmt.get('content'))
        if not content:
            continue
        key = content.lower()
        if key in seen:
            continue
        seen.add(key)
        working.append({
            'content': content[:500],
            'position': _normalize_position(stmt.get('position')),
        })

    need_count = len(working) < count
    need_spectrum = count >= 3 and not set(_VALID_POSITIONS).issubset(_stances_present(working))

    if need_count or need_spectrum:
        if need_count:
            logger.warning(
                "Padding seed set to floor (%d/%d) with deterministic fallback",
                len(working), count,
            )
        elif need_spectrum:
            logger.info(
                "Injecting fallback statements to restore pro/con/neutral coverage"
            )

        present = _stances_present(working)
        missing = [p for p in _VALID_POSITIONS if p not in present]
        fallback = _fallback_seed_statements(
            title=title, excerpt=excerpt, count=max(count, len(_VALID_POSITIONS) * 3)
        )
        # Prefer missing stances first so an all-pro LLM result still spans the spectrum.
        ordered_fallback = (
            [s for s in fallback if s['position'] in missing]
            + [s for s in fallback if s['position'] not in missing]
        )
        for stmt in ordered_fallback:
            key = _content_key(stmt.get('content'))
            if not key or key in seen:
                continue
            pos = _normalize_position(stmt.get('position'))
            fills_gap = pos not in _stances_present(working)
            if len(working) >= count and not fills_gap:
                if set(_VALID_POSITIONS).issubset(_stances_present(working)):
                    break
                continue
            seen.add(key)
            working.append({'content': stmt['content'][:500], 'position': pos})
            if len(working) >= count and set(_VALID_POSITIONS).issubset(_stances_present(working)):
                break

    finalized = _select_balanced(working, count)
    if len(finalized) < count:
        logger.error(
            "Seed finalization could only produce %d/%d statements for title=%r",
            len(finalized), count, _trim_text(title, 80),
        )
    return finalized


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
    statements: over-asks the LLM, retries when a round comes back short, and
    pads with deterministic templates only as a last resort.

    Args:
        topic: TrendingTopic object (existing behavior)
        title: Article/topic title for raw content mode
        excerpt: Article excerpt/summary for raw content mode
        source_name: Optional source attribution for raw content mode
        count: Target number of statements (default: recommended floor of 7)
        exclude_contents: Existing statement texts to skip (backfill / merge)

    Raises:
        ValueError: If neither topic nor title is provided
    """
    if not topic and not title:
        raise ValueError("Either topic or title must be provided")

    count = max(1, int(count))
    request_count = count + _SEED_OVERSAMPLE
    resolved_title = title or (topic.title if topic else None)
    resolved_excerpt = excerpt or (topic.description if topic else None)

    openai_key = os.environ.get('OPENAI_API_KEY')
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')

    # OpenAI preferred; Anthropic only runs while still short of the target.
    providers = []
    if openai_key:
        providers.append(("openai", partial(_generate_with_openai, api_key=openai_key)))
    if anthropic_key:
        providers.append(("anthropic", partial(_generate_with_anthropic, api_key=anthropic_key)))

    collected: List[Dict] = []
    seen = {_content_key(c) for c in (exclude_contents or []) if c}

    def _absorb(candidates: Optional[List[Dict]]) -> None:
        for stmt in candidates or []:
            key = _content_key(stmt.get('content'))
            if not key or key in seen:
                continue
            seen.add(key)
            collected.append({
                'content': _normalize_content(stmt.get('content'))[:500],
                'position': _normalize_position(stmt.get('position')),
            })

    for round_index in range(_SEED_MAX_ROUNDS):
        if len(collected) >= count or not providers:
            break
        for name, provider in providers:
            if len(collected) >= count:
                break
            try:
                _absorb(provider(
                    topic=topic,
                    title=title,
                    excerpt=excerpt,
                    source_name=source_name,
                    count=request_count,
                ))
            except Exception as e:
                # Providers already swallow their own errors; keep publishing safe.
                logger.error("%s seed provider raised unexpectedly: %s", name, e)
        if len(collected) < count and round_index + 1 < _SEED_MAX_ROUNDS:
            logger.warning(
                "Seed generation short (%d/%d) after round %d; retrying providers",
                len(collected), count, round_index + 1,
            )

    if not providers:
        logger.warning("LLM seed generation unavailable; using deterministic fallback statements")
    elif len(collected) < count:
        logger.warning(
            "Seed generation still short (%d/%d) after %d round(s); "
            "will pad with deterministic fallback statements",
            len(collected), count, _SEED_MAX_ROUNDS,
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


def _build_prompt(
    topic: Optional[TrendingTopic],
    title: Optional[str],
    excerpt: Optional[str],
    source_name: Optional[str],
    count: int
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

    prompt = f"""Generate {count} diverse seed statements for a public deliberation on this topic:

Topic: {topic_title}

{context_section}

Requirements:
- Generate statements representing DIFFERENT viewpoints (some pro, some con, some neutral/questioning)
- Aim for a balanced mix across pro, con, and neutral — not clustered on one stance
- Each statement should be 20-80 words
- Statements should be substantive and invite thoughtful responses
- Avoid strawman arguments - represent each position charitably
- Include at least one statement from each perspective
- Each statement must be understandable on its own (avoid unclear pronouns like "this/it/they" unless the subject is explicitly named)
- Prefer concrete actors, policies, or outcomes over abstract wording

Return as JSON array:
[
    {{"content": "statement text", "position": "pro"}},
    {{"content": "statement text", "position": "con"}},
    {{"content": "statement text", "position": "neutral"}},
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


def _parse_and_validate_statements(response_text: str, count: int) -> List[Dict]:
    """
    Parse raw LLM response into validated statement dicts.

    Soft specificity scoring reorders preference within the caller via
    ``_select_balanced``; this function never drops otherwise-valid statements.
    """
    statements = _extract_statements_payload(response_text)
    validated = []
    seen = set()
    for stmt in statements:
        if not (isinstance(stmt, dict) and 'content' in stmt):
            continue
        content_text = _normalize_content(stmt['content'])
        if not content_text:
            continue
        key = content_text.lower()
        if key in seen:
            continue
        seen.add(key)
        validated.append({
            'content': content_text[:500],
            'position': _normalize_position(stmt.get('position')),
        })

    return validated[:count]


def _generate_with_openai(
    topic: Optional[TrendingTopic],
    title: Optional[str],
    excerpt: Optional[str],
    source_name: Optional[str],
    count: int,
    api_key: str
) -> List[Dict]:
    """Generate seeds using OpenAI."""
    try:
        import openai
    except ImportError:
        logger.error("OpenAI library not installed")
        return []

    try:
        client = openai.OpenAI(api_key=api_key, timeout=60.0)
    except Exception as e:
        logger.error(f"Failed to create OpenAI client: {e}")
        return []

    prompt = _build_prompt(topic, title, excerpt, source_name, count)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a civic discourse facilitator who presents all viewpoints fairly."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.8
        )

        content = response.choices[0].message.content
        return _parse_and_validate_statements(content, count)

    except (SystemExit, KeyboardInterrupt):
        logger.error("OpenAI call was interrupted (SystemExit/KeyboardInterrupt)")
        return []
    except Exception as e:
        if _is_rate_limit_error(e):
            logger.warning(f"OpenAI seed generation rate-limited/quota-limited: {e}")
        elif _is_timeout_error(e):
            logger.warning(f"OpenAI seed generation timed out (transient): {e}")
        else:
            logger.error(f"Seed generation failed: {e}")
        return []


def _generate_with_anthropic(
    topic: Optional[TrendingTopic],
    title: Optional[str],
    excerpt: Optional[str],
    source_name: Optional[str],
    count: int,
    api_key: str
) -> List[Dict]:
    """Generate seeds using Anthropic."""
    try:
        import anthropic
    except ImportError:
        logger.error("Anthropic library not installed")
        return []

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=60.0)
    except Exception as e:
        logger.error(f"Failed to create Anthropic client: {e}")
        return []

    prompt = _build_prompt(topic, title, excerpt, source_name, count)

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        content = message.content[0].text
        return _parse_and_validate_statements(content, count)

    except (SystemExit, KeyboardInterrupt):
        logger.error("Anthropic call was interrupted (SystemExit/KeyboardInterrupt)")
        return []
    except Exception as e:
        if _is_rate_limit_error(e):
            logger.warning(f"Anthropic seed generation rate-limited/quota-limited: {e}")
        elif _is_timeout_error(e):
            logger.warning(f"Anthropic seed generation timed out (transient): {e}")
        else:
            logger.error(f"Seed generation failed: {e}")
        return []
