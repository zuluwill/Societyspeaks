"""Screen a statement an audience member suggested.

Every suggestion waits for the host whatever screening says. Screening does
two things: it rejects what should never reach the host's queue, and it tells
the host what to look at. If screening is unavailable the suggestion simply
waits, unscreened: the host still decides.
"""
import logging
from typing import Optional

from app.lib.llm_client import LLMError, complete_json

logger = logging.getLogger(__name__)

RESULT_OK = 'ok'
RESULT_REVIEW = 'review'
RESULT_REJECT = 'reject'
RESULT_UNSCREENED = 'unscreened'

CONCERNS = ('none', 'abusive', 'names_a_person', 'off_topic', 'duplicate', 'not_a_statement')

_SYSTEM = """You screen statements that members of an audience suggest for a consultation. \
Participants vote Agree, Disagree or Unsure on each statement. The organiser reviews every \
suggestion before it is shown, so your job is to help them, not to replace them.

Decide one result:
- "reject": it is abusive, hateful, threatening or sexually explicit, or it names or clearly \
identifies a private individual (for example a named colleague or manager) in a way that \
attaches a claim or complaint to them. These never reach the organiser's queue.
- "review": it may be a problem and the organiser should look closely: it is off the topic of \
the consultation, repeats a statement already in it, is a question or contains several ideas, \
or mentions an individual without attacking them.
- "ok": it is a fair, votable statement on the topic. Disagreeing with the organisation, or \
being blunt, is not a problem. Do not penalise criticism.

Give the single main concern, or "none"."""

_SCHEMA = {
    'type': 'object',
    'properties': {
        'result': {'type': 'string', 'enum': [RESULT_OK, RESULT_REVIEW, RESULT_REJECT]},
        'concern': {'type': 'string', 'enum': list(CONCERNS)},
    },
    'required': ['result', 'concern'],
    'additionalProperties': False,
}


def screen_statement(consultation, content: str, existing: list) -> dict:
    """``{'result', 'concern'}`` for one suggestion. Never raises."""
    listed = '\n'.join(f'- {text}' for text in existing) or '(none yet)'
    prompt = (
        f'The consultation question: {consultation.question}\n\n'
        f'Statements already in the consultation:\n{listed}\n\n'
        f'The suggested statement:\n{content}'
    )
    try:
        data = complete_json(
            purpose='consultation.screen_statement',
            system=_SYSTEM,
            prompt=prompt,
            schema=_SCHEMA,
            effort='low',
            consultation_id=consultation.id,
        )
    except LLMError as exc:
        logger.warning('Screening unavailable for consultation %s: %s', consultation.id, exc)
        return {'result': RESULT_UNSCREENED, 'concern': 'none'}
    result = data.get('result')
    concern: Optional[str] = data.get('concern')
    if result not in (RESULT_OK, RESULT_REVIEW, RESULT_REJECT):
        return {'result': RESULT_UNSCREENED, 'concern': 'none'}
    return {'result': result, 'concern': concern if concern in CONCERNS else 'none'}
