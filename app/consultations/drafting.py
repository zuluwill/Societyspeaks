"""Draft the statements a consultation's audience will vote on."""
from typing import Iterable, List, Optional

from flask import current_app

from app.lib.claim_craft import is_question_form
from app.lib.llm_client import complete_json
# Text helpers shared with the public-site seed generator.
from app.trending.seed_generator import (
    _is_near_duplicate as is_near_duplicate,
    _looks_compound_idea as looks_compound_idea,
)

_SOFT_LENGTH = 160
_STANCES = {'supportive': 'pro', 'critical': 'con', 'exploratory': 'neutral'}

_SYSTEM = """You draft the statements for a consultation an organisation runs with its own \
audience: its members, staff, customers, readers or event attendees.

Each participant sees one statement at a time and answers Agree, Disagree or Unsure. The \
organisation then learns where its audience agrees, disagrees, is unsure or is split. That only \
works when the set of statements covers the question fairly and each statement can be answered \
on its own.

What makes a statement work:
- It makes one claim. Someone who agrees with half of it has no honest answer, so never join two \
ideas with "and", "while" or "so that".
- It is a statement, not a question, and it stands alone without the others.
- It is specific to this organisation's question and uses only what the organiser told you. Do \
not invent facts, figures, names or history.
- It is in plain words the audience would use themselves, usually under 25 words.
- It is fair. A reasonable person could agree and another reasonable person could disagree, and \
neither would feel the wording had been chosen to push them.
- It never names or describes an identifiable individual.

What makes the set work:
- It gives people who favour change something to agree with, gives sceptics something to agree \
with, and includes statements about trade-offs, priorities and practical concerns.
- No two statements say the same thing in different words.
- It is written in the language the organiser used for the question."""

_SCHEMA = {
    'type': 'object',
    'properties': {
        'statements': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'content': {'type': 'string'},
                    'stance': {'type': 'string', 'enum': sorted(_STANCES)},
                },
                'required': ['content', 'stance'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['statements'],
    'additionalProperties': False,
}


def _prompt(consultation, count: int, existing: List[str]) -> str:
    parts = [
        f'Organisation: {consultation.organisation_name}',
        f'The question they want answered: {consultation.question}',
    ]
    if consultation.audience_label:
        parts.append(f'Who will take part: {consultation.audience_label}')
    if consultation.context:
        parts.append(f'Background from the organiser:\n{consultation.context}')
    if existing:
        listed = '\n'.join(f'- {content}' for content in existing)
        parts.append(
            'These statements are already in the consultation. Draft different ones that cover '
            f'angles they miss:\n{listed}'
        )
    parts.append(
        f'Draft {count} statements. For each, say whether it is "supportive" of change or the '
        'proposal in the question, "critical" of it, or "exploratory" (a trade-off, priority or '
        'condition that either side might accept).'
    )
    return '\n\n'.join(parts)


def statement_warnings(content: str) -> List[str]:
    """Plain-language problems with a statement, for the host's review screen."""
    warnings = []
    if is_question_form(content):
        warnings.append('question')
    if looks_compound_idea(content):
        warnings.append('two_ideas')
    if len(content or '') > _SOFT_LENGTH:
        warnings.append('long')
    return warnings


def draft_statements(
    consultation,
    *,
    count: Optional[int] = None,
    existing: Iterable[str] = (),
) -> List[dict]:
    """Ask the model for statements; return the usable ones as ``{content, stance}``.

    Raises ``LLMError`` when the model cannot be reached or declines. Drops
    questions, out-of-range lengths and near-duplicates rather than repairing
    them: the host reviews everything that is returned.
    """
    from app.consultations.service import STATEMENT_MAX_LENGTH, STATEMENT_MIN_LENGTH

    count = count or current_app.config.get('CONSULTATION_DRAFT_STATEMENT_COUNT', 12)
    existing = [content for content in existing if content]
    data = complete_json(
        purpose='consultation.draft_statements',
        system=_SYSTEM,
        # Over-ask slightly so dropping a duplicate still leaves a full set.
        prompt=_prompt(consultation, count + 3, existing),
        schema=_SCHEMA,
        effort='medium',
        consultation_id=consultation.id,
    )

    kept: List[dict] = []
    seen = list(existing)
    for item in data.get('statements') or []:
        content = ' '.join(str(item.get('content') or '').split())
        if not (STATEMENT_MIN_LENGTH <= len(content) <= STATEMENT_MAX_LENGTH):
            continue
        if is_question_form(content):
            continue
        if any(content.lower() == other.lower() for other in seen) or is_near_duplicate(content, seen):
            continue
        seen.append(content)
        kept.append({'content': content, 'stance': _STANCES.get(item.get('stance'), 'neutral')})
        if len(kept) >= count:
            break
    return kept
