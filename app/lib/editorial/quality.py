"""Quality gate before auto-sending a brief.

Returns a human-readable reason to hold a brief for review, or ``None`` when
it's good enough to ship. Pure function — no DB writes — so the generator
and the scheduler can both call it without ordering concerns.

The intent is conservative: catch the obvious "this would embarrass us if
we sent it" failure modes (everything from one source; only one item)
without holding legitimately thin days.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional, Protocol

from flask_babel import gettext as _


# Hold if dominance exceeds this. 0.7 means >70% of items from one source —
# that's a "TechCrunch-only" brief by any reasonable definition.
SINGLE_SOURCE_DOMINANCE_THRESHOLD = 0.7

# Hold if fewer than this many items. Two stories isn't a brief.
MIN_ITEMS_FOR_AUTO_SEND = 2

# Hold if fewer than this many distinct sources. One source = no editorial
# value; we're charging the user for synthesis across their feeds.
MIN_DISTINCT_SOURCES_FOR_AUTO_SEND = 2


class _ItemLike(Protocol):
    source_id: int


def _resolve_source_id(item: object) -> Optional[int]:
    """Return the InputSource id for a brief item or ingested row.

    ``BriefRunItem`` only stores ``ingested_item_id`` — the quality gate must
    follow that relationship when callers pass persisted run items rather than
    the ``IngestedItem`` rows the generator selected from.
    """
    sid = getattr(item, 'source_id', None)
    if sid is not None:
        return sid
    ingested = getattr(item, 'ingested_item', None)
    if ingested is not None:
        return getattr(ingested, 'source_id', None)
    return None


@dataclass(frozen=True)
class QualityVerdict:
    """Outcome of the quality gate. ``hold_reason`` non-empty → don't send."""

    hold_reason: Optional[str]
    item_count: int
    distinct_sources: int
    dominance: float  # 0..1 — fraction of items from the most-represented source

    @property
    def should_hold(self) -> bool:
        return self.hold_reason is not None


def assess_brief_quality(items: Iterable[_ItemLike]) -> QualityVerdict:
    """Decide whether a generated brief is ready to auto-send."""
    item_list = list(items)
    item_count = len(item_list)

    # ``hold_reason`` is rendered to the owner — both in the in-app banner and
    # in the notification email — so it must respect their locale. The generator
    # wraps this call in ``force_locale(owner_locale)``, which means ``gettext``
    # here resolves to the right language for the user reading the brief.
    if item_count == 0:
        return QualityVerdict(
            hold_reason=_("No items selected — nothing to send."),
            item_count=0,
            distinct_sources=0,
            dominance=0.0,
        )

    source_ids = [_resolve_source_id(i) for i in item_list]
    source_ids = [s for s in source_ids if s is not None]
    distinct = len(set(source_ids))

    counts = Counter(source_ids)
    most_common_share = (counts.most_common(1)[0][1] / item_count) if counts else 0.0

    if item_count < MIN_ITEMS_FOR_AUTO_SEND:
        return QualityVerdict(
            hold_reason=_(
                "Only %(count)d item(s) available — brief held for review "
                "rather than sending a near-empty edition.",
                count=item_count,
            ),
            item_count=item_count,
            distinct_sources=distinct,
            dominance=most_common_share,
        )

    if distinct < MIN_DISTINCT_SOURCES_FOR_AUTO_SEND:
        return QualityVerdict(
            hold_reason=_(
                "All selected items came from a single source — brief held "
                "for review so we don't ship a single-feed digest."
            ),
            item_count=item_count,
            distinct_sources=distinct,
            dominance=most_common_share,
        )

    if most_common_share > SINGLE_SOURCE_DOMINANCE_THRESHOLD:
        return QualityVerdict(
            hold_reason=_(
                "%(pct)d%% of items came from one source — brief held for review "
                "to avoid a single-outlet edition.",
                pct=round(most_common_share * 100),
            ),
            item_count=item_count,
            distinct_sources=distinct,
            dominance=most_common_share,
        )

    return QualityVerdict(
        hold_reason=None,
        item_count=item_count,
        distinct_sources=distinct,
        dominance=most_common_share,
    )
