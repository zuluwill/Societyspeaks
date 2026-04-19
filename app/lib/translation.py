"""
Translation service for civic discourse statements, discussions, and programmes.

Uses Claude Haiku for context-aware, cost-effective translation.
Results are cached in the DB (statement_translation, discussion_translation,
programme_translation tables). First request per language triggers a single batched
API call; subsequent requests hit the cache with zero translation cost.

Votes always target the canonical statement_id — translation is purely a display layer.

Language resolution delegates to locale_utils.resolve_locale() so Flask-Babel's
locale selector and content translation use exactly the same priority chain.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Single source of truth — imported from locale_utils to avoid duplication.
from app.lib.locale_utils import SUPPORTED_LANGUAGES  # noqa: E402


# ---------------------------------------------------------------------------
# Language resolution — delegates to locale_utils for single source of truth
# ---------------------------------------------------------------------------

def resolve_language(request=None) -> str:
    """
    Return the active language code for the current request.
    Delegates to Flask-Babel's get_locale() so the priority chain is identical
    for both UI strings (Babel) and dynamic content (this service).
    The `request` parameter is kept for backward-compat but is unused.
    """
    try:
        from flask_babel import get_locale
        locale = get_locale()
        if locale:
            return str(locale.language)
    except Exception:
        pass
    # Fallback when called outside a request context (e.g. background tasks)
    from app.lib.locale_utils import resolve_locale
    try:
        return resolve_locale()
    except Exception:
        return 'en'


# ---------------------------------------------------------------------------
# Claude Haiku translation
# ---------------------------------------------------------------------------

def _anthropic_client():
    import os
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        logger.warning('anthropic package not installed; translation disabled')
        return None


def _translate_batch(texts: list[str], target_lang: str, topic: str = '') -> list[Optional[str]]:
    """
    Translate a list of short texts to target_lang in a single Haiku API call.
    Returns a parallel list; entries are None when translation failed for that item.
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
        f'Translate the following civic discussion statements from English to {lang_name}.{topic_hint}\n'
        'Rules:\n'
        '- Preserve the precise meaning and the debatable, civic nature of each statement\n'
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
        logger.error('Translation batch failed (lang=%s): %s', target_lang, exc)
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
# Statement translation (cached)
# ---------------------------------------------------------------------------

def get_or_create_statement_translations(
    statements: list,
    language_code: str,
    discussion_title: str = '',
) -> dict[int, str]:
    """
    Return {statement_id: translated_content} for the given language.

    Fetches all cached translations in one query; translates any missing entries
    with a single batched API call; persists results. Falls back gracefully —
    if a statement's translation fails, it is simply absent from the returned dict
    and the caller should display the original English content.
    """
    if language_code == 'en' or not statements:
        return {}

    from app import db
    from app.models import StatementTranslation
    from app.lib.time import utcnow_naive

    stmt_ids = [s.id for s in statements]

    cached = StatementTranslation.query.filter(
        StatementTranslation.statement_id.in_(stmt_ids),
        StatementTranslation.language_code == language_code,
    ).all()
    result: dict[int, str] = {t.statement_id: t.content for t in cached}

    missing = [s for s in statements if s.id not in result]
    if not missing:
        return result

    translated = _translate_batch(
        [s.content for s in missing],
        language_code,
        topic=discussion_title,
    )

    now = utcnow_naive()
    for stmt, text in zip(missing, translated):
        if not text:
            continue
        db.session.add(StatementTranslation(
            statement_id=stmt.id,
            language_code=language_code,
            content=text,
            translation_source='machine',
            created_at=now,
        ))
        result[stmt.id] = text

    try:
        db.session.commit()
    except Exception as exc:
        logger.error('Failed to persist statement translations: %s', exc)
        db.session.rollback()

    return result


# ---------------------------------------------------------------------------
# Discussion translation (cached)
# ---------------------------------------------------------------------------

def get_or_create_discussion_translation(discussion, language_code: str) -> dict[str, str]:
    """
    Return {'title': ..., 'description': ...} in the target language.
    Falls back to the original English values on any failure.
    """
    description = discussion.description or ''
    fallback = {'title': discussion.title, 'description': description}

    if language_code == 'en':
        return fallback

    from app import db
    from app.models import DiscussionTranslation
    from app.lib.time import utcnow_naive

    cached = DiscussionTranslation.query.filter_by(
        discussion_id=discussion.id,
        language_code=language_code,
    ).first()
    if cached:
        return {'title': cached.title, 'description': cached.description or ''}

    texts = [discussion.title]
    if description:
        texts.append(description)

    translated = _translate_batch(texts, language_code)
    if not translated or translated[0] is None:
        return fallback

    obj = DiscussionTranslation(
        discussion_id=discussion.id,
        language_code=language_code,
        title=translated[0],
        description=translated[1] if len(translated) > 1 and translated[1] else description,
        translation_source='machine',
        created_at=utcnow_naive(),
    )
    db.session.add(obj)
    try:
        db.session.commit()
    except Exception as exc:
        logger.error('Failed to persist discussion translation: %s', exc)
        db.session.rollback()
        return fallback

    return {'title': obj.title, 'description': obj.description or ''}


# ---------------------------------------------------------------------------
# Programme translation (cached)
# ---------------------------------------------------------------------------

def get_or_create_programme_translation(programme, language_code: str) -> dict[str, str]:
    """
    Return {'name': ..., 'description': ...} for the programme in the target language.
    Falls back to the original English values on any failure.
    """
    description = getattr(programme, 'description', '') or ''
    fallback = {'name': programme.name, 'description': description}

    if language_code == 'en':
        return fallback

    from app import db
    from app.models import ProgrammeTranslation
    from app.lib.time import utcnow_naive

    cached = ProgrammeTranslation.query.filter_by(
        programme_id=programme.id,
        language_code=language_code,
    ).first()
    if cached:
        return {'name': cached.name, 'description': cached.description or ''}

    texts = [programme.name]
    if description:
        texts.append(description)

    translated = _translate_batch(texts, language_code)
    if not translated or translated[0] is None:
        return fallback

    obj = ProgrammeTranslation(
        programme_id=programme.id,
        language_code=language_code,
        name=translated[0],
        description=translated[1] if len(translated) > 1 and translated[1] else description,
        translation_source='machine',
        created_at=utcnow_naive(),
    )
    db.session.add(obj)
    try:
        db.session.commit()
    except Exception as exc:
        logger.error('Failed to persist programme translation: %s', exc)
        db.session.rollback()
        return fallback

    return {'name': obj.name, 'description': obj.description or ''}


def get_cached_programme_translations_map(programmes: list, language_code: str) -> dict[int, dict[str, str]]:
    """
    Return {programme_id: {'name': str, 'description': str}} from DB cache only.

    No API calls — used for list pages. Missing rows fall back to canonical
    English from the Programme row. Detail pages call get_or_create_programme_translation
    to populate the cache.
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
    out: dict[int, dict[str, str]] = {}
    for p in programmes:
        if p.id in cached:
            out[p.id] = cached[p.id]
        else:
            out[p.id] = {
                'name': p.name,
                'description': getattr(p, 'description', None) or '',
            }
    return out


# ---------------------------------------------------------------------------
# Discussion information_body translation (cached — long-form markdown)
# ---------------------------------------------------------------------------

def get_or_create_discussion_info_translation(discussion, language_code: str) -> dict[str, str]:
    """
    Return {'information_title': ..., 'information_body': ...} for journey info panels.
    Falls back to the original English values.
    """
    info_title = discussion.information_title or ''
    info_body = discussion.information_body or ''
    fallback = {'information_title': info_title, 'information_body': info_body}

    if language_code == 'en' or (not info_title and not info_body):
        return fallback

    from app import db
    from app.models import DiscussionTranslation
    from app.lib.time import utcnow_naive

    cached = DiscussionTranslation.query.filter_by(
        discussion_id=discussion.id,
        language_code=language_code,
    ).first()
    if cached and (cached.information_title is not None or cached.information_body is not None):
        return {
            'information_title': cached.information_title or info_title,
            'information_body': cached.information_body or info_body,
        }

    texts = []
    idx_title = idx_body = -1
    if info_title:
        idx_title = len(texts)
        texts.append(info_title)
    if info_body:
        idx_body = len(texts)
        texts.append(info_body)

    if not texts:
        return fallback

    translated = _translate_batch(texts, language_code)
    if not translated:
        return fallback

    t_title = translated[idx_title] if idx_title >= 0 and translated[idx_title] else info_title
    t_body = translated[idx_body] if idx_body >= 0 and translated[idx_body] else info_body

    if cached:
        cached.information_title = t_title
        cached.information_body = t_body
    else:
        # Upsert — only save information fields; title/description handled separately
        cached = DiscussionTranslation(
            discussion_id=discussion.id,
            language_code=language_code,
            title=discussion.title,  # placeholder — overwritten when full translation runs
            description=discussion.description or '',
            information_title=t_title,
            information_body=t_body,
            translation_source='machine',
            created_at=utcnow_naive(),
        )
        db.session.add(cached)

    try:
        db.session.commit()
    except Exception as exc:
        logger.error('Failed to persist discussion info translation: %s', exc)
        db.session.rollback()
        return fallback

    return {'information_title': t_title, 'information_body': t_body}
