"""Locale resolution for paid briefing generation, email, and notifications."""
from __future__ import annotations

from typing import Optional

from app.lib.locale_utils import SUPPORTED_LANGUAGES, resolve_user_locale


# Natural-language instruction the LLM understands. Keep aligned with
# ``SUPPORTED_LANGUAGES`` — anything missing falls back to English so we
# never ship empty prompts.
_LLM_LANGUAGE_INSTRUCTION = {
    'en': 'British English (analyse, centre, organisation)',
    'es': 'European Spanish (español de España)',
    'nl': 'Dutch (Nederlands)',
    'zh': 'Simplified Chinese (简体中文)',
    'de': 'German (Deutsch)',
    'fr': 'French (français de France)',
    'ja': 'Japanese (日本語), polite register',
    'pt': 'European Portuguese (português europeu)',
    'ar': 'Modern Standard Arabic (العربية الفصحى)',
    'hi': 'Hindi (हिन्दी), Devanagari script',
    'ko': 'Korean (한국어), polite register',
}


def get_briefing_owner_user(briefing):
    """Return the User who owns or administers ``briefing``, if any."""
    from app import db
    from app.models import CompanyProfile, User

    if briefing.owner_type == 'user':
        return db.session.get(User, briefing.owner_id)
    if briefing.owner_type == 'org':
        org = db.session.get(CompanyProfile, briefing.owner_id)
        return org.user if org else None
    return None


def resolve_briefing_locale(briefing) -> str:
    """Locale for generating or notifying about a briefing outside a request."""
    return resolve_user_locale(get_briefing_owner_user(briefing))


def llm_language_instruction(locale_code: Optional[str]) -> str:
    """Render a ``WRITE IN:`` instruction the LLM can follow.

    Used in every paid-brief LLM prompt so a French-speaking subscriber gets
    French intro / bullets / context / deeper-dive, not English content with
    a translated chrome. Falls back to British English on unknown codes —
    we'd rather ship correct English than break.
    """
    if not locale_code:
        return _LLM_LANGUAGE_INSTRUCTION['en']
    base = locale_code.split('-')[0].lower()
    return _LLM_LANGUAGE_INSTRUCTION.get(base, _LLM_LANGUAGE_INSTRUCTION['en'])
