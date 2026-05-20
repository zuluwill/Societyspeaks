"""
Apply BriefTemplate defaults to a Briefing instance.

Centralises filter/keyword/topic wiring so trial onboarding, marketplace
template use, and manual create-from-template all get the same editorial
intent from the seed data.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask_babel import lazy_gettext as _l

from app.models.briefing import BriefTemplate, Briefing


# Section groupings for paid brief HTML (template slug → sections). Each
# display name is wrapped in :func:`lazy_gettext` so:
#   1. Babel's extractor picks them up as msgids.
#   2. They're translated at render time using the briefing-owner's locale
#      (which the generator activates via ``force_locale``).
# Categories stay as plain strings — they're internal identifiers, not display copy.
TEMPLATE_SECTIONS: Dict[str, List[Tuple[Any, List[str]]]] = {
    'technology-ai-regulation': [
        (_l('Releases & Products'), ['TECHNOLOGY', 'INNOVATION', 'UPDATE']),
        (_l('Regulation & Policy'), ['REGULATION', 'POLICY', 'SECURITY']),
        (_l('Research & Analysis'), ['RESEARCH', 'ANALYSIS', 'MARKETS']),
    ],
    'policy-monitoring': [
        (_l('What Changed'), ['POLICY', 'REGULATION', 'UPDATE']),
        (_l("Who's Affected"), ['MARKETS', 'INFRASTRUCTURE', 'SECURITY']),
        (_l("What's Next"), ['ANALYSIS', 'RESEARCH']),
    ],
    'economy-markets': [
        (_l('Macro & Markets'), ['MARKETS', 'ANALYSIS', 'UPDATE']),
        (_l('Business & Industry'), ['INFRASTRUCTURE', 'INNOVATION', 'TECHNOLOGY']),
        (_l('Policy Context'), ['POLICY', 'REGULATION', 'RESEARCH']),
    ],
    'climate-energy-planet': [
        (_l('Climate & Energy'), ['SUSTAINABILITY', 'RESEARCH', 'UPDATE']),
        (_l('Policy & Regulation'), ['POLICY', 'REGULATION', 'SECURITY']),
        (_l('Science & Impact'), ['ANALYSIS', 'RESEARCH', 'MARKETS']),
    ],
    'world-affairs': [
        (_l('Headlines'), ['POLICY', 'SECURITY', 'UPDATE']),
        (_l('Analysis'), ['ANALYSIS', 'RESEARCH', 'MARKETS']),
        (_l('Regional Context'), ['INFRASTRUCTURE', 'REGULATION', 'SUSTAINABILITY']),
    ],
}

STRUCTURE_SECTIONS: Dict[str, List[Tuple[Any, List[str]]]] = {
    'what_changed': [
        (_l('What Changed'), ['POLICY', 'REGULATION', 'UPDATE']),
        (_l("Who's Affected"), ['MARKETS', 'INFRASTRUCTURE', 'SECURITY']),
        (_l("What's Next"), ['ANALYSIS', 'RESEARCH']),
    ],
}


def _dedupe_strings(values: List[Any]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for raw in values:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s or s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
    return out


def apply_template_config_to_briefing(briefing: Briefing, template: BriefTemplate) -> None:
    """Copy template filters, keywords, and topic weights onto ``briefing``."""
    default_filters = template.default_filters or {}

    include_keywords: List[str] = []
    if template.focus_keywords:
        include_keywords.extend(template.focus_keywords)
    for key in ('focus', 'sub_domains'):
        vals = default_filters.get(key) or []
        if isinstance(vals, list):
            include_keywords.extend(vals)

    exclude_keywords: List[str] = []
    if template.exclude_keywords:
        exclude_keywords.extend(template.exclude_keywords)
    extra_exclude = default_filters.get('exclude_keywords') or []
    if isinstance(extra_exclude, list):
        exclude_keywords.extend(extra_exclude)

    filters_json: Dict[str, List[str]] = {}
    include_clean = _dedupe_strings(include_keywords)
    if include_clean:
        filters_json['include_keywords'] = include_clean
    exclude_clean = _dedupe_strings(exclude_keywords)
    if exclude_clean:
        filters_json['exclude_keywords'] = exclude_clean

    briefing.filters_json = filters_json or None

    topics = default_filters.get('topics') or []
    if isinstance(topics, list) and topics:
        briefing.topic_preferences = {str(t): 2 for t in topics if t}


def get_sections_for_briefing(briefing: Briefing) -> Optional[List[Tuple[str, List[str]]]]:
    """Return ordered section definitions for a briefing, or None for flat layout."""
    template = briefing.template
    if template and template.slug and template.slug in TEMPLATE_SECTIONS:
        return TEMPLATE_SECTIONS[template.slug]

    guardrails = briefing.guardrails or {}
    structure = guardrails.get('structure_template') or (
        (template.guardrails or {}).get('structure_template') if template else None
    )
    if structure and structure in STRUCTURE_SECTIONS:
        return STRUCTURE_SECTIONS[structure]

    return None
