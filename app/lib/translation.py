"""
Translation cache layer for civic discourse statements, discussions, and programmes.

Architecture
------------
The request path uses get_cached_* functions — pure DB lookups that return
English when a translation is not yet in the cache. The background worker in
translation_worker.py calls _translate_batch (Haiku API) and populates the
cache asynchronously. This keeps page load time unaffected by API latency.

Votes always target the canonical statement_id — translation is a display
layer only. Language resolution delegates to locale_utils.resolve_locale()
so Flask-Babel and content translation share the same priority chain.
"""
import logging
import re
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)

# Single source of truth — imported by translation_worker.py as well.
from app.lib.locale_utils import SUPPORTED_LANGUAGES  # noqa: E402
from app.lib.llm_transient_errors import log_llm_error  # noqa: E402


class DiscussionTranslationCache(TypedDict):
    title: str
    description: str


class ProgrammeTranslationCache(TypedDict):
    name: str
    description: str


# ---------------------------------------------------------------------------
# Language resolution
# ---------------------------------------------------------------------------

def resolve_language(request=None) -> str:
    """
    Return the active language code for the current request.
    Delegates to Flask-Babel's get_locale() so UI strings and dynamic content
    use the same priority chain. The request parameter is kept for
    backward-compat but is unused.
    """
    try:
        from flask_babel import get_locale
        locale = get_locale()
        if locale:
            return str(locale.language)
    except Exception:
        pass
    from app.lib.locale_utils import resolve_locale
    try:
        return resolve_locale()
    except Exception:
        return 'en'


# ---------------------------------------------------------------------------
# Claude Haiku API — private, used only by translation_worker.py
# ---------------------------------------------------------------------------

def _anthropic_client():
    import os
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None
    try:
        import anthropic
        # max_retries=3 gives automatic exponential backoff on 429s.
        return anthropic.Anthropic(api_key=api_key, max_retries=3)
    except ImportError:
        logger.warning('anthropic package not installed; translation disabled')
        return None


def _translate_batch(texts: list[str], target_lang: str, topic: str = '') -> list[Optional[str]]:
    """
    Translate a list of texts to target_lang in a single Haiku API call.
    Returns a parallel list; None entries indicate a failed translation for
    that item. Called exclusively by translation_worker.py — never on the
    request path.
    """
    if target_lang == 'en' or not texts:
        return list(texts)

    client = _anthropic_client()
    if not client:
        return [None] * len(texts)

    lang_name = SUPPORTED_LANGUAGES[target_lang]['name']
    numbered = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(texts))
    topic_hint = f' The discussion topic is: "{topic}".' if topic else ''

    prompt = (
        f'Translate the following civic discussion content from English to {lang_name}.{topic_hint}\n'
        'Rules:\n'
        '- Preserve the precise meaning and the debatable, civic nature of each item\n'
        '- Keep the same register and directness as the original\n'
        '- Return ONLY the numbered translations in the exact same format (1. text  2. text  etc.)\n'
        '- Do not add commentary, explanations, or change the numbering\n\n'
        f'{numbered}'
    )

    try:
        response = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=4096,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return _parse_numbered_response(response.content[0].text.strip(), len(texts))
    except Exception as exc:
        log_llm_error(logger, exc, context=f'Translation batch failed (lang={target_lang})')
        return [None] * len(texts)


def _parse_numbered_response(raw: str, expected: int) -> list[Optional[str]]:
    results: list[Optional[str]] = [None] * expected
    for line in raw.splitlines():
        m = re.match(r'^(\d+)\.\s*(.+)$', line.strip())
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < expected:
                results[idx] = m.group(2).strip()
    return results


# ---------------------------------------------------------------------------
# Request-path cache lookups — DB only, no API calls
# ---------------------------------------------------------------------------

def get_cached_statement_translations(
    statements: list,
    language_code: str,
) -> dict[int, str]:
    """
    Return {statement_id: translated_content} from DB cache.
    Missing entries are absent from the dict — callers display the original English.
    The background worker populates the cache; this function never calls the API.
    """
    if language_code == 'en' or not statements:
        return {}

    from app.models import StatementTranslation

    stmt_ids = [s.id for s in statements]
    rows = StatementTranslation.query.filter(
        StatementTranslation.statement_id.in_(stmt_ids),
        StatementTranslation.language_code == language_code,
    ).all()
    return {r.statement_id: r.content for r in rows}


def get_cached_discussion_translation(discussion, language_code: str) -> Optional[DiscussionTranslationCache]:
    """
    Return {'title': ..., 'description': ...} from DB cache, or None on a miss.
    None means the translation is not yet available; callers fall back to English originals.
    The background worker will populate the cache within the next 5-minute run.
    """
    if language_code == 'en':
        return None

    from app.models import DiscussionTranslation

    cached = DiscussionTranslation.query.filter_by(
        discussion_id=discussion.id,
        language_code=language_code,
    ).first()
    if cached:
        return {'title': cached.title, 'description': cached.description or ''}
    return None


def get_cached_discussion_info_translation(discussion, language_code: str) -> dict[str, str]:
    """
    Return {'information_title': ..., 'information_body': ...} from DB cache.
    Falls back to English originals when not yet translated.
    """
    info_title = discussion.information_title or ''
    info_body = discussion.information_body or ''
    fallback = {'information_title': info_title, 'information_body': info_body}

    if language_code == 'en' or (not info_title and not info_body):
        return fallback

    from app.models import DiscussionTranslation

    cached = DiscussionTranslation.query.filter_by(
        discussion_id=discussion.id,
        language_code=language_code,
    ).first()
    if cached and (cached.information_title is not None or cached.information_body is not None):
        return {
            'information_title': cached.information_title or info_title,
            'information_body': cached.information_body or info_body,
        }
    return fallback


def get_cached_programme_translation(programme, language_code: str) -> Optional[ProgrammeTranslationCache]:
    """
    Return {'name': ..., 'description': ...} from DB cache, or None on a miss.
    None means the translation is not yet available; callers fall back to English originals.
    """
    if language_code == 'en':
        return None

    from app.models import ProgrammeTranslation

    cached = ProgrammeTranslation.query.filter_by(
        programme_id=programme.id,
        language_code=language_code,
    ).first()
    if cached:
        return {'name': cached.name, 'description': cached.description or ''}
    return None


def get_cached_discussion_translations_map(discussions: list, language_code: str) -> dict[int, Optional[DiscussionTranslationCache]]:
    """
    Return {discussion_id: {'title': str, 'description': str}} from DB cache.
    Used for listing pages. Missing rows return None — callers fall back to English originals.
    """
    if not discussions or language_code == 'en':
        return {}

    from app.models import DiscussionTranslation

    ids = [d.id for d in discussions]
    rows = DiscussionTranslation.query.filter(
        DiscussionTranslation.discussion_id.in_(ids),
        DiscussionTranslation.language_code == language_code,
    ).all()
    return {r.discussion_id: {'title': r.title, 'description': r.description or ''} for r in rows}


def get_cached_programme_translations_map(programmes: list, language_code: str) -> dict[int, ProgrammeTranslationCache]:
    """
    Return {programme_id: {'name': str, 'description': str}} from DB cache.
    Used for list pages. Missing rows fall back to the English Programme row.
    """
    if not programmes:
        return {}
    if language_code == 'en':
        return {
            p.id: {'name': p.name, 'description': getattr(p, 'description', None) or ''}
            for p in programmes
        }

    from app.models import ProgrammeTranslation

    ids = [p.id for p in programmes]
    rows = ProgrammeTranslation.query.filter(
        ProgrammeTranslation.programme_id.in_(ids),
        ProgrammeTranslation.language_code == language_code,
    ).all()
    cached = {r.programme_id: {'name': r.name, 'description': r.description or ''} for r in rows}
    return {
        p.id: cached.get(p.id, {
            'name': p.name,
            'description': getattr(p, 'description', None) or '',
        })
        for p in programmes
    }


def discussion_display_title(discussion, translation: Optional[DiscussionTranslationCache]) -> str:
    """
    Resolved discussion title for Python-built copy and Jinja templates.

    ``get_cached_discussion_translation`` returns a plain dict; use this helper in
    Python (attribute access on dicts raises AttributeError). Registered as a
    Jinja global so templates use the same contract.
    """
    if translation is not None:
        return translation['title']
    return discussion.title or ''


def discussion_display_description(discussion, translation: Optional[DiscussionTranslationCache]) -> str:
    """Resolved description with English fallback when the cache row is empty."""
    if translation is not None:
        translated = translation['description']
        if translated:
            return translated
    return discussion.description or ''


def programme_display_name(programme, translation: Optional[ProgrammeTranslationCache]) -> str:
    """Resolved programme name — same dict-vs-attribute contract as discussions."""
    if translation is not None:
        return translation['name']
    return programme.name or ''


def programme_display_description(programme, translation: Optional[ProgrammeTranslationCache]) -> str:
    """Resolved programme description with English fallback when the cache row is empty."""
    if translation is not None:
        translated = translation['description']
        if translated:
            return translated
    return getattr(programme, 'description', None) or ''
