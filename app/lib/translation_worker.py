"""
Background translation worker.

Finds untranslated discussions, statements, and programmes and fills the DB
cache using Claude Haiku. Called by the APScheduler job in app/scheduler.py
every 5 minutes. The request path uses get_cached_* functions (DB-only) and
serves English on a miss; this worker fills the cache so subsequent requests
get translated content without any API latency.

Throughput per run (all 10 non-English languages):
  Statements : up to STATEMENTS_PER_LANGUAGE per language
  Discussions: up to DISCUSSIONS_PER_LANGUAGE per language (title + description
               + info panel in a single batched API call)
  Programmes : up to PROGRAMMES_PER_LANGUAGE per language

Each language is independent — a failure in one does not block the others.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from app.lib.locale_utils import SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)

# Tune these to stay within Haiku rate limits.
# Each constant = max items translated per language per 5-minute run.
STATEMENTS_PER_LANGUAGE = 30
DISCUSSIONS_PER_LANGUAGE = 10
PROGRAMMES_PER_LANGUAGE = 5

# Pause between languages to avoid burst rate limiting.
_INTER_LANGUAGE_DELAY_SECS = 0.5

_NON_ENGLISH = [code for code in SUPPORTED_LANGUAGES if code != 'en']


# ---------------------------------------------------------------------------
# Queries — LEFT JOIN + IS NULL is more efficient than NOT IN on large tables
# ---------------------------------------------------------------------------

def _untranslated_statements(language_code: str, limit: int) -> list:
    from sqlalchemy import and_
    from app.models import Statement, StatementTranslation

    return (
        Statement.query
        .outerjoin(
            StatementTranslation,
            and_(
                StatementTranslation.statement_id == Statement.id,
                StatementTranslation.language_code == language_code,
            ),
        )
        .filter(
            Statement.is_deleted.is_(False),
            Statement.mod_status >= 0,
            StatementTranslation.id.is_(None),
        )
        .order_by(Statement.id.desc())   # newest first — most likely to be viewed soon
        .limit(limit)
        .all()
    )


def _untranslated_discussions(language_code: str, limit: int) -> list:
    """Discussions with no DiscussionTranslation row for this language."""
    from sqlalchemy import and_
    from app.models import Discussion, DiscussionTranslation

    return (
        Discussion.query
        .outerjoin(
            DiscussionTranslation,
            and_(
                DiscussionTranslation.discussion_id == Discussion.id,
                DiscussionTranslation.language_code == language_code,
            ),
        )
        .filter(
            Discussion.has_native_statements.is_(True),
            DiscussionTranslation.id.is_(None),
        )
        .order_by(Discussion.id.desc())
        .limit(limit)
        .all()
    )


def _discussions_missing_info(language_code: str, limit: int) -> list[tuple]:
    """
    Discussions that have a DiscussionTranslation row but are missing
    information_title or information_body that exist on the English original.
    Returns (Discussion, DiscussionTranslation) pairs.
    """
    from sqlalchemy import and_, or_
    from app import db
    from app.models import Discussion, DiscussionTranslation

    return (
        db.session.query(Discussion, DiscussionTranslation)
        .join(
            DiscussionTranslation,
            and_(
                DiscussionTranslation.discussion_id == Discussion.id,
                DiscussionTranslation.language_code == language_code,
            ),
        )
        .filter(
            Discussion.has_native_statements.is_(True),
            or_(
                and_(
                    Discussion.information_title.isnot(None),
                    DiscussionTranslation.information_title.is_(None),
                ),
                and_(
                    Discussion.information_body.isnot(None),
                    DiscussionTranslation.information_body.is_(None),
                ),
            ),
        )
        .order_by(Discussion.id.desc())
        .limit(limit)
        .all()
    )


def _untranslated_programmes(language_code: str, limit: int) -> list:
    from sqlalchemy import and_
    from app.models import Programme, ProgrammeTranslation

    return (
        Programme.query
        .outerjoin(
            ProgrammeTranslation,
            and_(
                ProgrammeTranslation.programme_id == Programme.id,
                ProgrammeTranslation.language_code == language_code,
            ),
        )
        .filter(
            Programme.status == 'active',
            ProgrammeTranslation.id.is_(None),
        )
        .order_by(Programme.id.desc())
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# Per-content-type processors — one API call per content type per language
# ---------------------------------------------------------------------------

def _process_statements(language_code: str) -> int:
    """
    Translate up to STATEMENTS_PER_LANGUAGE untranslated statements.
    Groups by discussion to provide topic context per batch.
    Returns count of rows persisted.
    """
    from app import db
    from app.models import Discussion, StatementTranslation
    from app.lib.time import utcnow_naive
    from app.lib.translation import _translate_batch

    stmts = _untranslated_statements(language_code, STATEMENTS_PER_LANGUAGE)
    if not stmts:
        return 0

    # Group by discussion so each batch gets an accurate topic hint.
    by_disc: dict[int, list] = defaultdict(list)
    for s in stmts:
        by_disc[s.discussion_id].append(s)

    disc_map = {
        d.id: d
        for d in Discussion.query.filter(Discussion.id.in_(list(by_disc))).all()
    }

    now = utcnow_naive()
    persisted = 0

    for disc_id, batch in by_disc.items():
        disc = disc_map.get(disc_id)
        topic = disc.title if disc else ''
        translated = _translate_batch([s.content for s in batch], language_code, topic=topic)

        for stmt, text in zip(batch, translated):
            if not text:
                continue
            db.session.add(StatementTranslation(
                statement_id=stmt.id,
                language_code=language_code,
                content=text,
                translation_source='machine',
                created_at=now,
            ))
            persisted += 1

    if persisted:
        try:
            db.session.commit()
        except Exception as exc:
            logger.error('Worker: statement commit failed [%s]: %s', language_code, exc)
            db.session.rollback()
            return 0

    return persisted


def _process_discussions(language_code: str) -> int:
    """
    Translate discussions missing a DiscussionTranslation row, and discussions
    with a row that is missing info panel fields. All texts across all
    candidates are batched into a single API call per language.
    Returns count of rows created or updated.
    """
    from app import db
    from app.models import DiscussionTranslation
    from app.lib.time import utcnow_naive
    from app.lib.translation import _translate_batch

    new_discs = _untranslated_discussions(language_code, DISCUSSIONS_PER_LANGUAGE)
    info_pairs = _discussions_missing_info(language_code, DISCUSSIONS_PER_LANGUAGE)

    if not new_discs and not info_pairs:
        return 0

    # Build a flat (texts, index_map) where index_map records what each text
    # belongs to so we can reconstruct after the single API call returns.
    texts: list[str] = []
    index_map: list[tuple] = []   # (disc, existing_row_or_None, field_name)

    for disc in new_discs:
        index_map.append((disc, None, 'title'))
        texts.append(disc.title)
        if disc.description:
            index_map.append((disc, None, 'description'))
            texts.append(disc.description)
        if disc.information_title:
            index_map.append((disc, None, 'information_title'))
            texts.append(disc.information_title)
        if disc.information_body:
            index_map.append((disc, None, 'information_body'))
            texts.append(disc.information_body)

    for disc, existing in info_pairs:
        if disc.information_title and existing.information_title is None:
            index_map.append((disc, existing, 'information_title'))
            texts.append(disc.information_title)
        if disc.information_body and existing.information_body is None:
            index_map.append((disc, existing, 'information_body'))
            texts.append(disc.information_body)

    if not texts:
        return 0

    translated = _translate_batch(texts, language_code)

    # Accumulate translated fields per discussion before writing to DB.
    # disc_results[disc.id][field] = (existing_row | None, translated_text)
    disc_results: dict[int, dict[str, tuple]] = defaultdict(dict)
    for (disc, existing, field), text in zip(index_map, translated):
        if text:
            disc_results[disc.id][field] = (existing, text)

    now = utcnow_naive()
    persisted = 0

    # Create rows for fully new discussions.
    for disc in new_discs:
        data = disc_results.get(disc.id, {})
        if 'title' not in data:
            continue   # Title translation failed — skip to avoid a row with a null title

        _, t_title = data['title']
        _, t_desc = data.get('description', (None, disc.description or ''))
        _, t_info_title = data.get('information_title', (None, None))
        _, t_info_body = data.get('information_body', (None, None))

        db.session.add(DiscussionTranslation(
            discussion_id=disc.id,
            language_code=language_code,
            title=t_title,
            description=t_desc,
            information_title=t_info_title,
            information_body=t_info_body,
            translation_source='machine',
            created_at=now,
        ))
        persisted += 1

    # Patch info fields on existing rows.
    for disc, existing in info_pairs:
        data = disc_results.get(disc.id, {})
        updated = False
        if 'information_title' in data:
            _, text = data['information_title']
            existing.information_title = text
            updated = True
        if 'information_body' in data:
            _, text = data['information_body']
            existing.information_body = text
            updated = True
        if updated:
            persisted += 1

    if persisted:
        try:
            db.session.commit()
        except Exception as exc:
            logger.error('Worker: discussion commit failed [%s]: %s', language_code, exc)
            db.session.rollback()
            return 0

    return persisted


def _process_programmes(language_code: str) -> int:
    """
    Translate programmes missing a ProgrammeTranslation row.
    All names and descriptions are batched into a single API call.
    Returns count of rows persisted.
    """
    from app import db
    from app.models import ProgrammeTranslation
    from app.lib.time import utcnow_naive
    from app.lib.translation import _translate_batch

    progs = _untranslated_programmes(language_code, PROGRAMMES_PER_LANGUAGE)
    if not progs:
        return 0

    texts: list[str] = []
    index_map: list[tuple] = []   # (programme, field)
    for prog in progs:
        index_map.append((prog, 'name'))
        texts.append(prog.name)
        if getattr(prog, 'description', None):
            index_map.append((prog, 'description'))
            texts.append(prog.description)

    translated = _translate_batch(texts, language_code)

    prog_data: dict[int, dict[str, str]] = defaultdict(dict)
    for (prog, field), text in zip(index_map, translated):
        if text:
            prog_data[prog.id][field] = text

    now = utcnow_naive()
    persisted = 0
    for prog in progs:
        data = prog_data.get(prog.id, {})
        if 'name' not in data:
            continue
        db.session.add(ProgrammeTranslation(
            programme_id=prog.id,
            language_code=language_code,
            name=data['name'],
            description=data.get('description', getattr(prog, 'description', None) or ''),
            translation_source='machine',
            created_at=now,
        ))
        persisted += 1

    if persisted:
        try:
            db.session.commit()
        except Exception as exc:
            logger.error('Worker: programme commit failed [%s]: %s', language_code, exc)
            db.session.rollback()
            return 0

    return persisted


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_translation_worker() -> dict[str, Any]:
    """
    Process all non-English languages in sequence. Called by the APScheduler
    job in app/scheduler.py. Each language is fully independent — a failure
    in one does not block the rest. Returns a summary dict for logging.
    """
    totals: dict[str, Any] = {'statements': 0, 'discussions': 0, 'programmes': 0, 'errors': []}

    for lang_code in _NON_ENGLISH:
        try:
            stmts = _process_statements(lang_code)
            discs = _process_discussions(lang_code)
            progs = _process_programmes(lang_code)
            totals['statements'] += stmts
            totals['discussions'] += discs
            totals['programmes'] += progs
            if stmts or discs or progs:
                logger.info(
                    'Translation worker [%s]: %d statements, %d discussions, %d programmes',
                    lang_code, stmts, discs, progs,
                )
        except Exception as exc:
            logger.error('Translation worker failed for language %s: %s', lang_code, exc)
            totals['errors'].append(lang_code)

        # Brief pause between languages to avoid burst rate limiting.
        time.sleep(_INTER_LANGUAGE_DELAY_SECS)

    return totals
