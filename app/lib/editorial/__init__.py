"""Editorial primitives shared between free Daily Brief and paid Briefings.

The pieces in this package operate on plain article-like objects, not on
``TrendingTopic`` or ``IngestedItem`` directly. That keeps the two pipelines
decoupled while giving paid briefs the same coverage / underreported logic
the free brief uses.
"""
from app.lib.editorial.coverage import (
    CoverageBlock,
    compute_coverage_distribution,
    coverage_block_for_items,
)
from app.lib.editorial.quality import (
    QualityVerdict,
    assess_brief_quality,
)
from app.lib.editorial.underreported import (
    UnderreportedPick,
    find_underreported_story,
)

__all__ = [
    'CoverageBlock',
    'compute_coverage_distribution',
    'coverage_block_for_items',
    'QualityVerdict',
    'assess_brief_quality',
    'UnderreportedPick',
    'find_underreported_story',
]
