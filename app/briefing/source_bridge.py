"""Bridge NewsSource metadata onto InputSource for paid briefings."""
from __future__ import annotations

from app.models import InputSource, NewsSource


def apply_news_source_metadata(input_source: InputSource, news_source: NewsSource) -> None:
    """Copy editorial metadata from a curated NewsSource onto InputSource.

    Paid brief coverage bars, credibility scoring, and channel filters read
    from InputSource — without this bridge, template sources created on-the-fly
    would behave like anonymous RSS feeds.
    """
    if news_source.political_leaning is not None:
        input_source.political_leaning = news_source.political_leaning

    # Curated allowlist sources are admin-trusted for user briefings.
    input_source.is_verified = True
    input_source.origin_type = 'admin'

    if not input_source.content_domain:
        input_source.content_domain = _infer_content_domain(news_source)

    if not input_source.allowed_channels:
        input_source.allowed_channels = ['user_briefings']


def _infer_content_domain(news_source: NewsSource) -> str:
    name = (news_source.name or '').lower()
    tech_markers = (
        'tech', 'ars technica', 'verge', 'wired', 'mit technology',
        'stratechery', 'github',
    )
    if any(marker in name for marker in tech_markers):
        return 'tech'
    return 'news'
