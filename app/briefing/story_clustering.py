"""
Cluster similar ingested articles into single editorial stories.

Groups near-duplicate headlines across sources so a paid brief reads as
"Google launches X — also covered by Ars Technica, The Verge" rather than
three separate Google posts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.models import IngestedItem


HEADLINE_SIMILARITY_THRESHOLD = 0.55

# Common stop-words stripped before entity overlap checks.
_STOP_WORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'must', 'shall', 'can',
    'its', 'it', 'this', 'that', 'these', 'those', 's', 't', 're', 've',
    'll', 'd', 'new', 'says', 'said', 'after', 'over', 'into', 'about',
})


@dataclass
class StoryCluster:
    """One editorial story, possibly backed by multiple source articles."""

    primary: IngestedItem
    related: List[IngestedItem] = field(default_factory=list)
    score: float = 0.0

    @property
    def all_items(self) -> List[IngestedItem]:
        return [self.primary] + self.related

    @property
    def source_names(self) -> List[str]:
        names: List[str] = []
        seen: Set[str] = set()
        for item in self.all_items:
            name = _item_source_name(item)
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                names.append(name)
        return names


def _item_source_name(item: IngestedItem) -> str:
    if item.source_name:
        return item.source_name
    if item.source:
        return item.source.name
    return ''


def _normalize_title(title: str) -> str:
    normalized = re.sub(r'[^\w\s]', ' ', (title or '').lower())
    return ' '.join(normalized.split())


def _content_words(title: str) -> Set[str]:
    words = set(_normalize_title(title).split())
    return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}


def headline_similarity(a: str, b: str) -> float:
    """Jaccard similarity on meaningful title words."""
    words_a = _content_words(a)
    words_b = _content_words(b)
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _same_story(a: IngestedItem, b: IngestedItem) -> bool:
    if headline_similarity(a.title or '', b.title or '') >= HEADLINE_SIMILARITY_THRESHOLD:
        return True
    # Shared prominent entity tokens (e.g. "google", "openai") with moderate overlap.
    words_a = _content_words(a.title or '')
    words_b = _content_words(b.title or '')
    shared = words_a & words_b
    if len(shared) >= 2 and headline_similarity(a.title or '', b.title or '') >= 0.35:
        return True
    return False


def cluster_scored_items(
    scored_items: Sequence[Tuple[IngestedItem, float]],
    *,
    similarity_threshold: float = HEADLINE_SIMILARITY_THRESHOLD,
) -> List[StoryCluster]:
    """
    Group scored items into story clusters (highest score per cluster wins).

    Args:
        scored_items: (IngestedItem, score) pairs, any order.
        similarity_threshold: Minimum Jaccard overlap to merge (unused override
            kept for tests — primary check uses module constant via _same_story).

    Returns:
        Clusters sorted by primary score descending.
    """
    del similarity_threshold  # reserved for future tuning

    if not scored_items:
        return []

    sorted_items = sorted(scored_items, key=lambda x: x[1], reverse=True)
    clusters: List[StoryCluster] = []

    for item, score in sorted_items:
        placed = False
        for cluster in clusters:
            if _same_story(item, cluster.primary) or any(
                _same_story(item, r) for r in cluster.related
            ):
                cluster.related.append(item)
                placed = True
                break
        if not placed:
            clusters.append(StoryCluster(primary=item, score=score))

    clusters.sort(key=lambda c: c.score, reverse=True)
    return clusters


def attach_cluster_metadata(cluster: StoryCluster) -> IngestedItem:
    """
    Copy cluster context onto the primary item for downstream HTML/LLM.

    Sets transient attributes:
      ``_cluster_also_covered``: list of (source_name, url)
      ``_cluster_source_count``: int
    """
    primary = cluster.primary
    also_covered: List[Tuple[str, str]] = []
    for related in cluster.related:
        name = _item_source_name(related)
        url = related.url or ''
        if name:
            also_covered.append((name, url))

    primary._cluster_also_covered = also_covered  # type: ignore[attr-defined]
    primary._cluster_source_count = len(cluster.source_names)  # type: ignore[attr-defined]
    return primary
