"""
Guided journey programme variants — metadata only (no DB, no Flask app).

Single source of truth for slug env keys, geographic scope, and display names.
Curriculum content lives in journey_seed.py; this module avoids import cycles
between journey.py and journey_seed.py.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, NamedTuple, Optional


class JourneyVariantMeta(NamedTuple):
    geographic_scope: str
    country: Optional[str]
    config_env_key: str
    default_slug: str
    display_name: str


VARIANT_METADATA: Dict[str, JourneyVariantMeta] = {
    "global": JourneyVariantMeta(
        "global",
        None,
        "GUIDED_JOURNEY_PROGRAMME_SLUG",
        "humanity-big-questions",
        "Humanity's big questions",
    ),
    "uk": JourneyVariantMeta(
        "country",
        "United Kingdom",
        "GUIDED_JOURNEY_UK_PROGRAMME_SLUG",
        "humanity-big-questions-uk",
        "Humanity's big questions (United Kingdom)",
    ),
    "us": JourneyVariantMeta(
        "country",
        "United States",
        "GUIDED_JOURNEY_US_PROGRAMME_SLUG",
        "humanity-big-questions-us",
        "Humanity's big questions (United States)",
    ),
    "nl": JourneyVariantMeta(
        "country",
        "Netherlands",
        "GUIDED_JOURNEY_NL_PROGRAMME_SLUG",
        "humanity-big-questions-nl",
        "Humanity's big questions (Netherlands)",
    ),
    "ie": JourneyVariantMeta(
        "country",
        "Ireland",
        "GUIDED_JOURNEY_IE_PROGRAMME_SLUG",
        "humanity-big-questions-ie",
        "Humanity's big questions (Ireland)",
    ),
    "de": JourneyVariantMeta(
        "country",
        "Germany",
        "GUIDED_JOURNEY_DE_PROGRAMME_SLUG",
        "humanity-big-questions-de",
        "Humanity's big questions (Germany)",
    ),
    "fr": JourneyVariantMeta(
        "country",
        "France",
        "GUIDED_JOURNEY_FR_PROGRAMME_SLUG",
        "humanity-big-questions-fr",
        "Humanity's big questions (France)",
    ),
    "ca": JourneyVariantMeta(
        "country",
        "Canada",
        "GUIDED_JOURNEY_CA_PROGRAMME_SLUG",
        "humanity-big-questions-ca",
        "Humanity's big questions (Canada)",
    ),
    "sg": JourneyVariantMeta(
        "country",
        "Singapore",
        "GUIDED_JOURNEY_SG_PROGRAMME_SLUG",
        "humanity-big-questions-sg",
        "Humanity's big questions (Singapore)",
    ),
    "jp": JourneyVariantMeta(
        "country",
        "Japan",
        "GUIDED_JOURNEY_JP_PROGRAMME_SLUG",
        "humanity-big-questions-jp",
        "Humanity's big questions (Japan)",
    ),
    "cn": JourneyVariantMeta(
        "country",
        "China",
        "GUIDED_JOURNEY_CN_PROGRAMME_SLUG",
        "humanity-big-questions-cn",
        "Humanity's big questions (China)",
    ),
}

VALID_VARIANTS: FrozenSet[str] = frozenset(VARIANT_METADATA.keys())
