"""The words around a report's findings.

Two writers produce the same shape::

    {'headline': str,
     'themes': [{'title': str, 'summary': str, 'verdict': str, 'statement_ids': [int]}],
     'next_questions': [str]}

``template_narrative`` is deterministic and always available.
``ai_narrative`` asks the model for better prose and returns it only when it
passes ``validate_narrative``: the model may describe findings, never
quantify them. Every figure a reader sees comes from the report data.

What validation cannot do is read prose for meaning. It proves that each theme
cites statements with the result it claims and that no figure was introduced;
it does not prove the headline's wording is the fairest summary. The report
therefore always prints the counted results beside the narrative.
"""
import logging
import re
import unicodedata
from typing import List, Optional

from babel.lists import format_list
from flask_babel import get_locale, gettext as _

from app.lib.llm_client import LLMError, complete_json
from app.lib.statement_results import Verdict

logger = logging.getLogger(__name__)

_MAX_THEMES = 4
_MAX_QUESTIONS = 4
_HEADLINE_MAX = 220
_SUMMARY_MAX = 420
_QUESTION_MAX = 220

# A narrative that quantifies is rejected. Numbers written as digits are
# caught in any language. Numbers and proportions written as words can only be
# caught with a word list, so a narrative is accepted only in a language that
# has one; in any other language the report keeps the template.
_NUMBER_TOKEN = re.compile(r'\d+(?:[.,]\d+)*(?:\s?[%٪％])?|[%٪％]')


def _words(pattern: str) -> 're.Pattern':
    return re.compile(rf'\b(?:{pattern})\b', re.IGNORECASE)


_QUANTITY_WORDS = {
    'en': _words(
        r'two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|sixty|'
        r'seventy|eighty|ninety|hundreds?|thousands?|dozens?|'
        r'per ?cent|percentages?|half|halves|thirds?|quarters?|fifths?|tenths?|twice|thrice|doubled?|tripled?|'
        r'unanimous(?:ly)?|everyone|everybody|nobody|no one|all participants|overwhelming(?:ly)?|'
        r'(?:nearly|almost|virtually) (?:all|every\w*)|margins?|'
        r'(?:vast|large|huge|great|big|slim|narrow|small|bare|strong) majority'
    ),
    'es': _words(
        r'dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|veinte|treinta|cuarenta|cincuenta|'
        r'cien|ciento|cientos|mil|miles|docenas?|'
        r'por ciento|porcentajes?|mitad|tercios?|cuartos?|doble|triple|'
        r'unánime(?:s|mente)?|unanimidad|todos los participantes|nadie|casi tod[oa]s|'
        r'(?:gran|amplia|inmensa|abrumadora|estrecha) mayoría|mayoría (?:amplia|abrumadora|estrecha)'
    ),
    'fr': _words(
        r'deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|vingt|trente|quarante|cinquante|'
        r'soixante|cent|cents|mille|milliers?|douzaines?|'
        r'pour cent|pourcentages?|moitié|tiers|quarts?|double|triple|'
        r'unanime(?:s|ment)?|unanimité|tout le monde|tous les participants|presque tou(?:s|tes)|'
        r'(?:large|grande|vaste|immense|écrasante|courte|faible) majorité|majorité (?:écrasante|large|courte)'
    ),
    'de': _words(
        r'zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf|zwanzig|dreißig|vierzig|fünfzig|'
        r'hundert\w*|tausend\w*|dutzend\w*|'
        r'prozent\w*|hälfte|drittel|viertel|doppelt\w*|dreifach\w*|zweimal|'
        r'einstimmig\w*|alle teilnehmer\w*|niemand|fast alle|'
        r'(?:große|grosse|überwältigende|breite|knappe|klare|deutliche)n? mehrheit'
    ),
    'nl': _words(
        r'twee|drie|vier|vijf|zes|zeven|acht|negen|tien|elf|twaalf|twintig|dertig|veertig|vijftig|'
        r'honderd\w*|duizend\w*|dozijn\w*|'
        r'procent\w*|percentages?|helft|derde|kwart|dubbel\w*|tweemaal|'
        r'unaniem|iedereen|niemand|bijna (?:alle|iedereen)|alle deelnemers|'
        r'(?:grote|overweldigende|ruime|krappe|kleine) meerderheid'
    ),
    'pt': _words(
        r'dois|duas|três|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|vinte|trinta|quarenta|cinquenta|'
        r'cem|cento|centenas?|mil|milhares|dúzias?|'
        r'por cento|porcentage(?:m|ns)|percentage(?:m|ns)|metade|terços?|quartos?|dobro|triplo|'
        r'unânime(?:s|mente)?|unanimidade|todos os participantes|ninguém|quase tod[oa]s|'
        r'(?:grande|ampla|imensa|esmagadora|estreita) maioria|maioria (?:esmagadora|ampla|estreita)'
    ),
}
_CHECKED_LANGUAGES = tuple(_QUANTITY_WORDS)

_FINDING_VERDICTS = (Verdict.AGREES.value, Verdict.DISAGREES.value, Verdict.UNSURE.value, Verdict.SPLIT.value)

_SYSTEM = """You write the short narrative for a consultation report. An organisation asked \
its own audience one question; participants answered Agree, Disagree or Unsure to a set of \
statements. Code has already worked out the result for each statement. You are given those \
results as labels:

- agrees: a clear majority agreed
- disagrees: a clear majority disagreed
- unsure: "unsure" was the largest response
- split: agreement and disagreement were both substantial and close
- no_clear_result: the votes lean one way but not clearly enough to call
- too_few_votes: not enough votes to say anything

Write for a busy reader who will forward this report. Be plain and specific. Describe what the \
results show and nothing more: do not say what the organisation ought to do, and do not explain \
why people voted as they did, because you cannot know.

Rules the report depends on:
- Never state a number, percentage, fraction or proportion, in digits or in words. The report \
prints the exact figures next to each statement.
- Each theme gathers statements that share one result. Give that result as the theme's verdict \
and cite only statements that have it. Use only agrees, disagrees, unsure or split.
- The results describe the people who took part, not anyone else. Say "participants" or \
"those who took part", never "your members", "staff" or "the public" as a whole.
- Suggested next questions are things the organisation could ask or look into next. Phrase them \
as questions. They are suggestions, not findings.
- Write in the language of the question, and give that language's code as "language" \
(or "other" if it is not one of the codes offered)."""

_SCHEMA = {
    'type': 'object',
    'properties': {
        'language': {'type': 'string', 'enum': [*_CHECKED_LANGUAGES, 'other']},
        'headline': {'type': 'string'},
        'themes': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'summary': {'type': 'string'},
                    'verdict': {'type': 'string', 'enum': list(_FINDING_VERDICTS)},
                    'statement_ids': {'type': 'array', 'items': {'type': 'integer'}},
                },
                'required': ['title', 'summary', 'verdict', 'statement_ids'],
                'additionalProperties': False,
            },
        },
        'next_questions': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['language', 'headline', 'themes', 'next_questions'],
    'additionalProperties': False,
}


def _has_findings(data: dict) -> bool:
    counts = data.get('counts') or {}
    return any(counts.get(verdict) for verdict in _FINDING_VERDICTS)


def template_narrative(data: dict) -> dict:
    """A plain narrative built from the data alone.

    Written in the active locale: callers outside a request wrap this in
    ``force_locale`` for the host's language.
    """
    counts = data.get('counts') or {}
    if not _has_findings(data):
        headline = _(
            'Too few people have taken part to say where this audience stands. '
            'The votes so far are shown below as counts.'
        )
    else:
        parts = []
        for verdict, phrase in (
            (Verdict.AGREES.value, _('clearly agreed with %(n)d')),
            (Verdict.DISAGREES.value, _('clearly disagreed with %(n)d')),
            (Verdict.UNSURE.value, _('were unsure about %(n)d')),
            (Verdict.SPLIT.value, _('were split on %(n)d')),
        ):
            n = counts.get(verdict) or 0
            if n:
                parts.append(phrase % {'n': n})
        headline = _(
            'Of %(total)d statements, participants %(findings)s.',
            total=data.get('statement_count') or 0,
            findings=format_list(parts, locale=get_locale() or 'en'),
        )

    questions: List[str] = []
    for row in data.get('statements') or []:
        if len(questions) >= 3:
            break
        if row['verdict'] == Verdict.SPLIT.value:
            questions.append(_('What lies behind the division over “%(statement)s”?', statement=row['content']))
        elif row['verdict'] == Verdict.UNSURE.value:
            questions.append(_(
                'What would people need to know to take a view on “%(statement)s”?',
                statement=row['content'],
            ))
    return {'headline': headline, 'themes': [], 'next_questions': questions}


def validate_narrative(narrative: dict, data: dict) -> Optional[str]:
    """Why this narrative cannot be published, or None when it can."""
    verdict_by_id = {row['statement_id']: row['verdict'] for row in data.get('statements') or []}

    headline = (narrative.get('headline') or '').strip()
    if not headline or len(headline) > _HEADLINE_MAX:
        return 'headline missing or too long'
    themes = narrative.get('themes') or []
    questions = narrative.get('next_questions') or []
    if len(themes) > _MAX_THEMES or len(questions) > _MAX_QUESTIONS:
        return 'too many themes or questions'

    texts = [headline]
    for theme in themes:
        title = (theme.get('title') or '').strip()
        summary = (theme.get('summary') or '').strip()
        if not title or not summary or len(summary) > _SUMMARY_MAX:
            return 'theme missing text or too long'
        ids = theme.get('statement_ids') or []
        if not ids:
            return 'theme cites no statements'
        if theme.get('verdict') not in _FINDING_VERDICTS:
            return 'theme has no valid verdict'
        for statement_id in ids:
            if verdict_by_id.get(statement_id) != theme['verdict']:
                return f'theme cites statement {statement_id} with a different result'
        texts.extend([title, summary])
    for question in questions:
        question = (question or '').strip()
        if not question or len(question) > _QUESTION_MAX:
            return 'question missing or too long'
        texts.append(question)

    quantity_words = _QUANTITY_WORDS.get(narrative.get('language'))
    if quantity_words is None:
        return 'written in a language whose wording cannot be checked'
    source = _source_text(data)
    source_numbers = set(_number_tokens(source))
    foreign = _unchecked_letters(' '.join(texts)) - _unchecked_letters(source)
    if foreign:
        return 'written in a script whose wording cannot be checked'
    for text in texts:
        # A figure is allowed only where it repeats the host's own words
        # ("a 4-day week"), never as a description of the result.
        for token in _number_tokens(text):
            if token not in source_numbers:
                return f'quantifies a finding ({token!r})'
        for match in quantity_words.finditer(text):
            if not re.search(rf'\b{re.escape(match.group(0))}\b', source, re.IGNORECASE):
                return f'quantifies a finding ({match.group(0)!r})'
    return None


def _source_text(data: dict) -> str:
    """The host's and participants' own words: the question and the statements."""
    parts = [data.get('question') or '']
    parts.extend(row.get('content') or '' for row in data.get('statements') or [])
    return '\n'.join(parts)


def _number_tokens(text: str) -> List[str]:
    return [re.sub(r'\s', '', token) for token in _NUMBER_TOKEN.findall(text)]


def _unchecked_letters(text: str) -> set:
    """Letters outside the Latin script, which the word lists cannot read."""
    return {
        char for char in text
        if char.isalpha() and not unicodedata.name(char, '').startswith('LATIN')
    }


def _is_checkable(data: dict) -> bool:
    """Whether a narrative in the question's language could pass validation."""
    letters = [char for char in (data.get('question') or '') if char.isalpha()]
    if not letters:
        return False
    return len(_unchecked_letters(''.join(letters))) == 0 or (
        sum(1 for char in letters if unicodedata.name(char, '').startswith('LATIN')) / len(letters) >= 0.5
    )


def _prompt(data: dict, *, rejected_for: Optional[str] = None) -> str:
    lines = [
        f'Organisation: {data.get("organisation_name")}',
        f'Question: {data.get("question")}',
    ]
    if data.get('audience_label'):
        lines.append(f'Who was invited: {data["audience_label"]}')
    lines.append('')
    lines.append('Statements and their results:')
    for row in data.get('statements') or []:
        label = row['verdict']
        if label == Verdict.NO_CLEAR_RESULT.value and row.get('lean'):
            label = f'{label} (leans {row["lean"]})'
        lines.append(f'- id {row["statement_id"]} [{label}]: {row["content"]}')
    lines.append('')
    lines.append(
        f'Write a headline of one or two sentences, up to {_MAX_THEMES} themes, and up to '
        f'{_MAX_QUESTIONS} suggested next questions.'
    )
    if rejected_for:
        lines.append('')
        lines.append(
            f'Your previous draft could not be used because it {rejected_for}. '
            'Write it again without doing that.'
        )
    return '\n'.join(lines)


def ai_narrative(data: dict, *, consultation_id: Optional[int] = None) -> Optional[dict]:
    """A model-written narrative that passed validation, or None.

    None means "keep the template": no findings to describe, the model was
    unavailable, or what it wrote broke a rule.
    """
    if not _has_findings(data) or not _is_checkable(data):
        return None
    problem = None
    for attempt in (1, 2):
        try:
            narrative = complete_json(
                purpose='consultation.report_narrative',
                system=_SYSTEM,
                prompt=_prompt(data, rejected_for=problem),
                schema=_SCHEMA,
                effort='medium',
                consultation_id=consultation_id,
            )
        except LLMError as exc:
            logger.warning('Report narrative unavailable (attempt %s): %s', attempt, exc)
            if not exc.retryable:
                return None
            continue
        problem = validate_narrative(narrative, data)
        if problem is None:
            return {
                'headline': narrative['headline'].strip(),
                'themes': narrative.get('themes') or [],
                'next_questions': [q.strip() for q in narrative.get('next_questions') or []],
            }
        logger.warning('Report narrative rejected (attempt %s): %s', attempt, problem)
        if narrative.get('language') not in _QUANTITY_WORDS:
            # Asking again would get the same language back.
            return None
    return None
