"""Political-coverage distribution that works for any pipeline.

Both the free Daily Brief and the paid Briefings need to say "your sources
today leaned X% left / Y% centre / Z% right, with N outlets unrated." The
free engine had this baked into ``app/brief/coverage_analyzer.py`` coupled
to ``TrendingTopic`` / ``NewsArticle``. This module is the same idea but
protocol-driven so paid briefs (``IngestedItem`` + ``InputSource``) can use it.

Inputs are intentionally minimal: a list of items where each item has a
``source.political_leaning`` (float -1..1, ``None`` for unrated) and a
``source.name``. Anything without a leaning is reported as "unrated" rather
than silently dropped — readers should know how much of their brief is
unlabelled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Protocol, Sequence

from flask_babel import gettext as _


# Same thresholds the free engine uses — keep these aligned so a story
# rated "left" on the free brief reads the same on a paid brief.
LEFT_THRESHOLD = -0.5
RIGHT_THRESHOLD = 0.5

# Below this many sources with rated leaning we don't render a coverage block:
# the percentages are noise and it does more harm than good. Free brief has
# 50+ rated sources so it never hits this; paid briefs often start with 3-5.
MIN_RATED_SOURCES_FOR_BLOCK = 3


class _ArticleLike(Protocol):
    """Duck-typed article. Whatever you pass in just needs a ``source``."""

    source: '_SourceLike'


class _SourceLike(Protocol):
    name: str
    political_leaning: Optional[float]


@dataclass(frozen=True)
class CoverageBlock:
    """Renderable coverage distribution.

    ``has_signal`` is the gate templates check — when False, the block has
    too few rated sources to be meaningful and should be hidden, not shown
    as a near-empty bar.
    """

    left_count: int
    center_count: int
    right_count: int
    unrated_count: int
    sources_by_leaning: dict[str, list[str]]  # {'left': [...], 'center': [...], 'right': [...]}
    unrated_sources: list[str]
    imbalance: float  # 0=balanced, 1=single-perspective
    notes: str

    @property
    def total_rated(self) -> int:
        return self.left_count + self.center_count + self.right_count

    @property
    def has_signal(self) -> bool:
        return self.total_rated >= MIN_RATED_SOURCES_FOR_BLOCK

    @property
    def left_pct(self) -> int:
        return _safe_pct(self.left_count, self.total_rated)

    @property
    def center_pct(self) -> int:
        return _safe_pct(self.center_count, self.total_rated)

    @property
    def right_pct(self) -> int:
        return _safe_pct(self.right_count, self.total_rated)

    @property
    def blindspot(self) -> Optional[str]:
        """Return 'left'/'right' if one side is conspicuously absent.

        Heuristic matches the free brief's blindspot detector: a side with
        ≤15% coverage while the opposite side has ≥30% is flagged. Centre
        absence isn't a blindspot — that's just "no centrist coverage today."
        """
        if not self.has_signal:
            return None
        if self.left_pct <= 15 and self.right_pct >= 30:
            return 'left'
        if self.right_pct <= 15 and self.left_pct >= 30:
            return 'right'
        return None


def _safe_pct(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round(100 * numerator / denominator)


def compute_coverage_distribution(items: Iterable[_ArticleLike]) -> CoverageBlock:
    """Bucket items by source political leaning.

    De-duplicates by source name so a cluster of three Guardian articles
    counts as one left-leaning source, not three. This matches reader
    intuition ("two outlets agreed") and matches the free brief's behaviour.
    """
    left: list[str] = []
    center: list[str] = []
    right: list[str] = []
    unrated: list[str] = []
    seen: set[str] = set()

    for item in items:
        source = getattr(item, 'source', None)
        if not source:
            continue
        name = getattr(source, 'name', None)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        leaning = getattr(source, 'political_leaning', None)
        if leaning is None:
            unrated.append(name)
        elif leaning < LEFT_THRESHOLD:
            left.append(name)
        elif leaning > RIGHT_THRESHOLD:
            right.append(name)
        else:
            center.append(name)

    total_rated = len(left) + len(center) + len(right)
    if total_rated == 0:
        imbalance = 0.0
    else:
        max_share = max(len(left), len(center), len(right)) / total_rated
        # Normalise to 0..1 with 0.33 = perfectly balanced.
        imbalance = max(0.0, min(1.0, (max_share - 1 / 3) / (2 / 3)))

    return CoverageBlock(
        left_count=len(left),
        center_count=len(center),
        right_count=len(right),
        unrated_count=len(unrated),
        sources_by_leaning={'left': left, 'center': center, 'right': right},
        unrated_sources=unrated,
        imbalance=round(imbalance, 2),
        notes=_describe(len(left), len(center), len(right), len(unrated)),
    )


def coverage_block_for_items(items: Sequence[_ArticleLike]) -> Optional[CoverageBlock]:
    """Convenience: compute a coverage block and return ``None`` when it
    lacks signal. Templates use this so they don't have to check
    ``has_signal`` themselves."""
    block = compute_coverage_distribution(items)
    return block if block.has_signal else None


def _describe(left: int, center: int, right: int, unrated: int) -> str:
    """Human-readable coverage note. Generated inside ``force_locale`` so
    ``gettext`` resolves to the briefing owner's language."""
    total = left + center + right
    if total == 0:
        return _("Coverage perspective not available — sources unrated.")

    if total == 1:
        if left == 1:
            return _("Today's stories came from one left-leaning source.")
        if right == 1:
            return _("Today's stories came from one right-leaning source.")
        return _("Today's stories came from one centrist source.")

    # Single perspective dominance check
    if left >= total - 1 and total >= 3:
        return _("Coverage skewed left (%(n)d of %(total)d rated outlets).",
                 n=left, total=total)
    if right >= total - 1 and total >= 3:
        return _("Coverage skewed right (%(n)d of %(total)d rated outlets).",
                 n=right, total=total)
    if center >= total - 1 and total >= 3:
        return _("Coverage clustered in the centre (%(n)d of %(total)d rated outlets).",
                 n=center, total=total)

    parts = []
    if left:
        parts.append(_("%(n)dL", n=left))
    if center:
        parts.append(_("%(n)dC", n=center))
    if right:
        parts.append(_("%(n)dR", n=right))
    breakdown = ' · '.join(str(p) for p in parts)
    if unrated:
        return _(
            "Today's brief drew on %(total)d rated outlets (%(breakdown)s), plus %(unrated)d unrated.",
            total=total, breakdown=breakdown, unrated=unrated,
        )
    return _(
        "Today's brief drew on %(total)d rated outlets (%(breakdown)s).",
        total=total, breakdown=breakdown,
    )
