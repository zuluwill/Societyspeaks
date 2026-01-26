"""
Shared constants and utilities for the trending module.
"""

# Import centralized text processing utilities (DRY)
from app.utils.text_processing import strip_html_tags

VALID_TOPICS = [
    'Healthcare', 'Environment', 'Education', 'Technology', 'Economy',
    'Politics', 'Society', 'Infrastructure', 'Geopolitics', 'Business', 'Culture'
]

# Diversity monitoring thresholds
# A ratio of 1.0 means perfect left-right balance
DIVERSITY_BALANCED_MIN = 0.7  # Below this triggers warning (right-leaning)
DIVERSITY_BALANCED_MAX = 1.4  # Above this triggers warning (left-leaning)
DIVERSITY_IMBALANCED_MIN = 0.5  # Below this triggers imbalance alert
DIVERSITY_IMBALANCED_MAX = 2.0  # Above this triggers imbalance alert

# Diversity monitoring defaults
DIVERSITY_DEFAULT_DAYS = 30
DIVERSITY_DEFAULT_TARGET_DISCUSSIONS = 3
DIVERSITY_STATS_LIMIT = 10000  # Max records to process for stats

# Geographic scope mappings
GEOGRAPHIC_SCOPE_GLOBAL = 'global'
GEOGRAPHIC_SCOPE_COUNTRY = 'country'
GEOGRAPHIC_SCOPE_UNKNOWN = 'unknown'

# Valid geographic scopes from article analysis
ARTICLE_SCOPE_TO_DISCUSSION_SCOPE = {
    'national': GEOGRAPHIC_SCOPE_COUNTRY,
    'local': GEOGRAPHIC_SCOPE_COUNTRY,
    'regional': GEOGRAPHIC_SCOPE_COUNTRY,
    'global': GEOGRAPHIC_SCOPE_GLOBAL,
}

TARGET_AUDIENCE_DESCRIPTION = """
Our target audience follows podcasts like: The Rest is Politics, Newsagents, Triggernometry,
All-In Podcast, UnHerd, Diary of a CEO, Modern Wisdom, Tim Ferriss Show, Louis Theroux.

They value:
- Nuanced political/policy discussion (not partisan culture war)
- Geopolitics and international affairs
- Technology, economics, and entrepreneurship
- Intellectual depth over sensationalism
- Contrarian or heterodox perspectives
- Long-form substantive debate
"""


# strip_html_tags is imported from app.utils.text_processing (DRY)


def extract_geographic_info_from_articles(articles) -> tuple:
    """
    Extract geographic scope and countries from a list of articles.
    Consolidates logic used by both publisher.py and podcast_publisher.py (DRY).

    Args:
        articles: Iterable of objects with .article attribute containing
                  geographic_scope, geographic_countries, and source.country

    Returns:
        (geographic_scope, country_string) tuple
    """
    from collections import Counter

    scopes = []
    countries_list = []

    for item in articles:
        article = getattr(item, 'article', item)
        if not article:
            continue

        if hasattr(article, 'geographic_scope') and article.geographic_scope:
            scope = article.geographic_scope
            if scope != GEOGRAPHIC_SCOPE_UNKNOWN:
                scopes.append(scope)

        if hasattr(article, 'geographic_countries') and article.geographic_countries:
            countries_list.append(article.geographic_countries)
        elif hasattr(article, 'source') and article.source and article.source.country:
            countries_list.append(article.source.country)

    if scopes:
        scope_counts = Counter(scopes)
        most_common_scope = scope_counts.most_common(1)[0][0]
        geographic_scope = ARTICLE_SCOPE_TO_DISCUSSION_SCOPE.get(
            most_common_scope, GEOGRAPHIC_SCOPE_GLOBAL
        )
    else:
        geographic_scope = GEOGRAPHIC_SCOPE_GLOBAL

    country = None
    if countries_list:
        all_countries = []
        for c in countries_list:
            all_countries.extend([x.strip() for x in c.split(',')])

        if 'Global' not in all_countries:
            country_counts = Counter(all_countries)
            country = country_counts.most_common(1)[0][0]

    return geographic_scope, country


def get_unique_slug(model_class, base_slug: str, max_attempts: int = 100) -> str:
    """
    Generate a unique slug for a model, handling race conditions gracefully.
    Uses database-level uniqueness check with retry logic.

    Args:
        model_class: SQLAlchemy model class with 'slug' field
        base_slug: The base slug to start from
        max_attempts: Maximum number of suffix attempts

    Returns:
        A unique slug string

    Raises:
        ValueError: If unable to generate unique slug after max_attempts
    """
    import random
    import string

    slug = base_slug

    for attempt in range(max_attempts):
        existing = model_class.query.filter_by(slug=slug).first()
        if not existing:
            return slug

        if attempt < 10:
            slug = f"{base_slug}-{attempt + 1}"
        else:
            suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
            slug = f"{base_slug}-{suffix}"

    raise ValueError(f"Unable to generate unique slug after {max_attempts} attempts")
