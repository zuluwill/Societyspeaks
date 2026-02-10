"""
Brief Section Definitions

Central configuration for brief sections, category mappings, region definitions,
and depth levels. Used by topic_selector, generator, and templates.

Single source of truth — update section definitions here and they propagate
throughout the entire brief pipeline.
"""

from collections import OrderedDict


# =============================================================================
# SECTION DEFINITIONS
# =============================================================================

# Ordered dict preserves display order in email and web templates.
# Each section has a display name, color (for templates), icon, and max items.

SECTIONS = OrderedDict([
    ('lead', {
        'display_name': 'Lead Story',
        'description': '',
        'email_color': '#1e40af',   # Blue-800
        'web_color_class': 'text-blue-800',
        'icon': '',
        'max_items': 1,
        'default_depth': 'full',
        'sort_order': 0,
    }),
    ('politics', {
        'display_name': 'Policy & Governance',
        'description': "What's shaping policy and public institutions",
        'email_color': '#ea580c',   # Orange-600
        'web_color_class': 'text-orange-600',
        'icon': '',
        'max_items': 2,
        'default_depth': 'standard',
        'sort_order': 1,
    }),
    ('economy', {
        'display_name': 'Economy & Business',
        'description': 'Markets, trade, and corporate developments',
        'email_color': '#059669',   # Emerald-600
        'web_color_class': 'text-emerald-600',
        'icon': '',
        'max_items': 2,
        'default_depth': 'standard',
        'sort_order': 2,
    }),
    ('society', {
        'display_name': 'Society & Culture',
        'description': 'How communities and culture are evolving',
        'email_color': '#c026d3',   # Fuchsia-600
        'web_color_class': 'text-fuchsia-600',
        'icon': '',
        'max_items': 2,
        'default_depth': 'standard',
        'sort_order': 3,
    }),
    ('science', {
        'display_name': 'Science, Tech & Environment',
        'description': 'Innovation, discovery, and our planet',
        'email_color': '#0d9488',   # Teal-600
        'web_color_class': 'text-teal-600',
        'icon': '',
        'max_items': 2,
        'default_depth': 'standard',
        'sort_order': 4,
    }),
    ('global_roundup', {
        'display_name': 'Around the World',
        'description': 'Quick-hit stories from across the globe',
        'email_color': '#2563eb',   # Blue-600
        'web_color_class': 'text-blue-600',
        'icon': '',
        'max_items': 5,
        'default_depth': 'quick',
        'sort_order': 5,
    }),
    ('world_events', {
        'display_name': 'What the World is Watching',
        'description': 'Where prediction markets see the biggest stakes',
        'email_color': '#0ea5e9',   # Sky-500
        'web_color_class': 'text-sky-600',
        'icon': '',
        'max_items': 5,
        'default_depth': 'quick',
        'sort_order': 6,
    }),
    ('week_ahead', {
        'display_name': 'The Week Ahead',
        'description': 'Key dates and events to watch',
        'email_color': '#7c3aed',   # Violet-600
        'web_color_class': 'text-violet-600',
        'icon': '',
        'max_items': 5,
        'default_depth': 'quick',
        'sort_order': 7,
    }),
    ('market_pulse', {
        'display_name': 'Market Pulse',
        'description': 'What prediction markets are pricing in',
        'email_color': '#6366f1',   # Indigo-500
        'web_color_class': 'text-indigo-600',
        'icon': '',
        'max_items': 3,
        'default_depth': 'quick',
        'sort_order': 8,
    }),
    ('underreported', {
        'display_name': 'Under the Radar',
        'description': 'Stories that deserve more attention',
        'email_color': '#f59e0b',   # Amber-500
        'web_color_class': 'text-amber-600',
        'icon': '',
        'max_items': 1,
        'default_depth': 'standard',
        'sort_order': 9,
    }),
    ('lens_check', {
        'display_name': 'Same Story, Different Lens',
        'description': 'How the same event is framed differently',
        'email_color': '#7c3aed',   # Violet-600
        'web_color_class': 'text-purple-600',
        'icon': '',
        'max_items': 1,
        'default_depth': 'full',
        'sort_order': 10,
    }),
])

# Valid section keys for model validation
VALID_SECTIONS = set(SECTIONS.keys())


# =============================================================================
# DEPTH LEVELS
# =============================================================================

DEPTH_FULL = 'full'
DEPTH_STANDARD = 'standard'
DEPTH_QUICK = 'quick'

VALID_DEPTHS = {DEPTH_FULL, DEPTH_STANDARD, DEPTH_QUICK}

# What content is generated at each depth level
DEPTH_CONFIG = {
    DEPTH_FULL: {
        'headline': True,
        'bullets': 4,           # Max bullets
        'personal_impact': True,
        'so_what': True,
        'perspectives': True,
        'deeper_context': True,
        'verification_links': True,
        'blindspot': True,
        'coverage_bar': True,
        'discussion_cta': True,
    },
    DEPTH_STANDARD: {
        'headline': True,
        'bullets': 2,           # Fewer bullets
        'personal_impact': False,
        'so_what': True,
        'perspectives': False,
        'deeper_context': False,
        'verification_links': True,
        'blindspot': False,
        'coverage_bar': True,
        'discussion_cta': False,
    },
    DEPTH_QUICK: {
        'headline': True,
        'bullets': 0,           # No bullets — one-sentence summary instead
        'personal_impact': False,
        'so_what': False,
        'perspectives': False,
        'deeper_context': False,
        'verification_links': False,
        'blindspot': False,
        'coverage_bar': False,
        'discussion_cta': False,
    },
}


# =============================================================================
# CATEGORY-TO-SECTION MAPPING
# =============================================================================

# Maps TrendingTopic.primary_topic values to brief sections.
# This is the bridge between the trending pipeline and the brief structure.
# Keys are lowercase for case-insensitive matching.

CATEGORY_TO_SECTION = {
    # Politics & Governance
    'politics': 'politics',
    'governance': 'politics',
    'legislation': 'politics',
    'elections': 'politics',
    'democracy': 'politics',
    'government': 'politics',
    'policy': 'politics',
    'law': 'politics',
    'justice': 'politics',
    'regulation': 'politics',

    # Economy & Business
    'economy': 'economy',
    'business': 'economy',
    'finance': 'economy',
    'markets': 'economy',
    'trade': 'economy',
    'employment': 'economy',
    'housing': 'economy',
    'infrastructure': 'economy',
    'capital': 'economy',
    'tax': 'economy',

    # Society & Culture
    'society': 'society',
    'culture': 'society',
    'education': 'society',
    'health': 'society',
    'healthcare': 'society',
    'immigration': 'society',
    'media': 'society',
    'arts': 'society',
    'religion': 'society',
    'social': 'society',
    'welfare': 'society',

    # Science, Tech & Environment
    'science': 'science',
    'technology': 'science',
    'tech': 'science',
    'environment': 'science',
    'climate': 'science',
    'energy': 'science',
    'ai': 'science',
    'space': 'science',
    'digital': 'science',
    'innovation': 'science',

    # Geopolitics maps to politics (covered in global roundup by geography)
    'international': 'politics',
    'geopolitics': 'politics',
    'world': 'politics',
    'global': 'politics',
    'diplomacy': 'politics',
    'defence': 'politics',
    'defense': 'politics',
    'military': 'politics',
    'conflict': 'politics',
}


def get_section_for_category(primary_topic: str) -> str:
    """
    Map a TrendingTopic.primary_topic to a brief section.

    Args:
        primary_topic: The topic's primary_topic field value

    Returns:
        Section key (e.g., 'politics', 'economy'). Defaults to 'society'
        if the category is unknown — 'society' is the broadest catch-all.
    """
    if not primary_topic:
        return 'society'  # Default catch-all
    return CATEGORY_TO_SECTION.get(primary_topic.lower(), 'society')


# =============================================================================
# THEMATIC SECTION DISPLAY NAMES
# =============================================================================

# Maps primary_topic to the Tortoise Media–style display labels used in
# templates (email and web). Kept separate from section names so the label
# can be more evocative while the section key stays programmatic.

TOPIC_DISPLAY_LABELS = {
    'economy': 'CAPITAL',
    'business': 'CAPITAL',
    'finance': 'CAPITAL',
    'capital': 'CAPITAL',
    'technology': 'TECHNOLOGY',
    'tech': 'TECHNOLOGY',
    'digital': 'TECHNOLOGY',
    'ai': 'TECHNOLOGY',
    'health': '100-YEAR LIFE',
    'healthcare': '100-YEAR LIFE',
    'medicine': '100-YEAR LIFE',
    'environment': 'OUR PLANET',
    'climate': 'OUR PLANET',
    'energy': 'OUR PLANET',
    'culture': 'CULTURE',
    'society': 'CULTURE',
    'arts': 'CULTURE',
    'international': 'WORLD',
    'world': 'WORLD',
    'global': 'WORLD',
    'geopolitics': 'WORLD',
    'policy': 'POLICY',
    'politics': 'POLICY',
    'government': 'POLICY',
    'education': 'LEARNING',
    'science': 'SCIENCE',
    'space': 'SCIENCE',
}

# Color mapping for topic display labels (email inline styles)
TOPIC_DISPLAY_COLORS = {
    'CAPITAL': '#059669',
    'TECHNOLOGY': '#7c3aed',
    '100-YEAR LIFE': '#dc2626',
    'OUR PLANET': '#0d9488',
    'CULTURE': '#c026d3',
    'WORLD': '#2563eb',
    'POLICY': '#ea580c',
    'LEARNING': '#6366f1',
    'SCIENCE': '#0d9488',
}


def get_topic_display_label(primary_topic: str) -> str:
    """Get the Tortoise Media–style display label for a topic category."""
    if not primary_topic:
        return 'NEWS'
    return TOPIC_DISPLAY_LABELS.get(primary_topic.lower(), primary_topic.upper())


def get_topic_display_color(primary_topic: str) -> str:
    """Get the color for a topic display label (for email inline styles)."""
    label = get_topic_display_label(primary_topic)
    return TOPIC_DISPLAY_COLORS.get(label, '#64748b')


# =============================================================================
# GEOGRAPHIC REGIONS (for Global Roundup)
# =============================================================================

# Regions and their associated countries for geographic diversity detection.
# Used by the topic selector to identify gaps in geographic coverage and
# fill the "Around the World" section.

REGIONS = OrderedDict([
    ('asia_pacific', {
        'display_name': 'Asia-Pacific',
        'countries': [
            'China', 'Japan', 'India', 'Australia', 'South Korea',
            'Indonesia', 'Thailand', 'Vietnam', 'Philippines', 'Malaysia',
            'Taiwan', 'Singapore', 'New Zealand', 'Pakistan', 'Bangladesh',
            'Myanmar', 'Sri Lanka', 'Nepal', 'Cambodia', 'Laos',
        ],
        'emoji': '',
    }),
    ('europe', {
        'display_name': 'Europe',
        'countries': [
            'UK', 'France', 'Germany', 'Italy', 'Spain', 'Poland',
            'Netherlands', 'Belgium', 'Sweden', 'Norway', 'Denmark',
            'Finland', 'Ireland', 'Portugal', 'Greece', 'Austria',
            'Switzerland', 'Czech Republic', 'Romania', 'Hungary',
            'Ukraine', 'EU',
        ],
        'emoji': '',
    }),
    ('americas', {
        'display_name': 'Americas',
        'countries': [
            'US', 'USA', 'United States', 'Canada', 'Brazil', 'Mexico',
            'Argentina', 'Colombia', 'Chile', 'Peru', 'Venezuela',
            'Ecuador', 'Cuba', 'Guatemala', 'Haiti',
        ],
        'emoji': '',
    }),
    ('middle_east_africa', {
        'display_name': 'Middle East & Africa',
        'countries': [
            'Israel', 'Palestine', 'Saudi Arabia', 'Iran', 'Iraq',
            'Turkey', 'UAE', 'Qatar', 'Egypt', 'Nigeria', 'South Africa',
            'Kenya', 'Ethiopia', 'Morocco', 'Algeria', 'Tunisia',
            'Sudan', 'Libya', 'Congo', 'Ghana', 'Tanzania', 'Uganda',
            'Somalia', 'Lebanon', 'Syria', 'Jordan', 'Yemen',
        ],
        'emoji': '',
    }),
])


def get_region_for_countries(countries_str: str) -> str:
    """
    Determine region from a comma-separated countries string.

    Args:
        countries_str: e.g., "UK, France" or "China"

    Returns:
        Region key (e.g., 'europe', 'asia_pacific') or 'global' if unknown
    """
    if not countries_str:
        return 'global'

    countries = [c.strip() for c in countries_str.split(',')]

    for region_key, region_data in REGIONS.items():
        for country in countries:
            if country in region_data['countries']:
                return region_key

    return 'global'


def get_covered_regions(topics) -> set:
    """
    Determine which regions are already covered by a list of topics.

    Args:
        topics: List of TrendingTopic instances

    Returns:
        Set of region keys that have coverage
    """
    covered = set()
    for topic in topics:
        geo_countries = getattr(topic, 'geographic_countries', None)
        if geo_countries:
            region = get_region_for_countries(geo_countries)
            if region != 'global':
                covered.add(region)

        # Also check geographic_scope
        geo_scope = getattr(topic, 'geographic_scope', None)
        if geo_scope == 'global':
            # Global stories don't count as covering any specific region
            pass

    return covered


# =============================================================================
# BRIEF TYPE DEFINITIONS (Daily vs Weekly)
# =============================================================================

BRIEF_TYPE_DAILY = 'daily'
BRIEF_TYPE_WEEKLY = 'weekly'
VALID_BRIEF_TYPES = {BRIEF_TYPE_DAILY, BRIEF_TYPE_WEEKLY}

# Subscriber cadence options
CADENCE_DAILY = 'daily'
CADENCE_WEEKLY = 'weekly'
VALID_CADENCES = {CADENCE_DAILY, CADENCE_WEEKLY}

# Default day for weekly brief delivery (0=Monday, 6=Sunday)
DEFAULT_WEEKLY_DAY = 6  # Sunday


# =============================================================================
# HELPER: Group items by section for template rendering
# =============================================================================

def group_items_by_section(items) -> OrderedDict:
    """
    Group BriefItem instances by section for template rendering.

    Items without a section are placed in a '_unsectioned' group.
    Sections are ordered according to SECTIONS sort_order.

    Args:
        items: Iterable of BriefItem instances

    Returns:
        OrderedDict of {section_key: [item, ...]} preserving section order.
        Only includes sections that have items.
    """
    groups = {}

    for item in items:
        section = getattr(item, 'section', None) or '_unsectioned'
        if section not in groups:
            groups[section] = []
        groups[section].append(item)

    # Sort items within each group by position
    for section_items in groups.values():
        section_items.sort(key=lambda x: x.position or 0)

    # Order groups by section sort_order
    ordered = OrderedDict()
    for section_key in SECTIONS:
        if section_key in groups:
            ordered[section_key] = groups[section_key]

    # Append unsectioned items at the end (backward compat for old briefs)
    if '_unsectioned' in groups:
        ordered['_unsectioned'] = groups['_unsectioned']

    return ordered


def is_sectioned_brief(items) -> bool:
    """
    Check if a brief uses the new sectioned format.

    Returns True if any item has a section assigned.
    Used by templates to decide between sectioned and flat layout.
    """
    for item in items:
        if getattr(item, 'section', None):
            return True
    return False
