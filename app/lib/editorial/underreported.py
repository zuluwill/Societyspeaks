"""Pick a single 'under the radar' story from the user's feed.

The free brief surfaces civically-valuable stories that didn't get wide
coverage (``app/brief/underreported.py``). For paid briefs we apply the
same intuition to the user's own feed: from items the generator did *not*
pick for the main brief, surface one that:

- comes from a source the user picked (so it's relevant), AND
- did not appear in a cluster with multiple sources (so it's genuinely
  under-covered, not the same Google story everyone else ran), AND
- is recent enough to still be worth reading.

This is intentionally simpler than the free engine's civic-score logic —
on a per-user feed of ~50-200 items there isn't enough data for civic
scoring, but "exactly one source ran this, and you read that source"
is itself a strong editorial signal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence

from app.lib.time import utcnow_naive


def _strip_html(text: str) -> str:
    """Strip HTML tags and collapse whitespace to plain text."""
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = re.sub(r'[ \t]+', ' ', clean)
    return clean.strip()


# Stories older than this aren't "under the radar," they're "missed."
MAX_AGE_HOURS = 36


@dataclass(frozen=True)
class UnderreportedPick:
    """One under-the-radar story to surface in a callout."""

    title: str
    source_name: str
    url: Optional[str]
    summary: Optional[str]
    published_at: Optional[datetime]


def find_underreported_story(
    *,
    candidates: Iterable,
    selected_ids: Sequence[int],
    cluster_source_counts: Optional[dict[int, int]] = None,
) -> Optional[UnderreportedPick]:
    """Pick at most one underreported item from ``candidates``.

    Args:
        candidates: Iterable of ``IngestedItem``-like objects with ``id``,
            ``title``, ``source_name``, ``url``, ``content_text``,
            ``published_at``, ``fetched_at`` attributes.
        selected_ids: IDs of items already in the main brief — these are
            excluded so we never feature what's already on the front page.
        cluster_source_counts: Optional map of ``item.id -> source_count``
            from the clusterer. When present, items in multi-source
            clusters are skipped (they're well-covered).

    Returns:
        A single :class:`UnderreportedPick`, or ``None`` if nothing
        qualifies. The caller decides whether to render the callout.
    """
    selected = set(selected_ids)
    cutoff = utcnow_naive() - timedelta(hours=MAX_AGE_HOURS)
    cluster_counts = cluster_source_counts or {}

    best = None
    best_age_hours: float = float('inf')

    for item in candidates:
        item_id = getattr(item, 'id', None)
        if item_id is None or item_id in selected:
            continue
        if cluster_counts.get(item_id, 1) > 1:
            continue
        title = getattr(item, 'title', None)
        if not title:
            continue

        pub = getattr(item, 'published_at', None) or getattr(item, 'fetched_at', None)
        if pub is None or pub < cutoff:
            continue

        age_h = max(0.0, (utcnow_naive() - pub).total_seconds() / 3600.0)
        if age_h < best_age_hours:
            best = item
            best_age_hours = age_h

    if best is None:
        return None

    summary = _strip_html((getattr(best, 'content_text', None) or '').strip())
    if summary:
        summary = summary[:280].rsplit(' ', 1)[0] + ('…' if len(summary) > 280 else '')

    source_name = getattr(best, 'source_name', None) or ''
    if not source_name:
        source = getattr(best, 'source', None)
        if source is not None:
            source_name = getattr(source, 'name', '') or ''

    return UnderreportedPick(
        title=best.title,
        source_name=source_name,
        url=getattr(best, 'url', None),
        summary=summary or None,
        published_at=getattr(best, 'published_at', None),
    )
